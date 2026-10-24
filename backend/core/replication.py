"""
core/replication.py -- a read replica of the live world, for gateway processes.

The simulation core owns the world (core/world_state.py). A gateway process (SIM_ROLE=api: REST
reads and the websocket) keeps a copy of it fed over Redis, so serving clients costs the core
nothing, and sends every mutation back as a command (core/commands.py).

    core     Publisher.publish()  after every tick, under the world lock
                 -> stream <prefix>:frames   one JSON frame per tick: what changed
                 -> key    <prefix>:snap     the whole dynamic world (zlib JSON) + :meta {epoch, seq, tick}
                 -> key    <prefix>:static   world_tiles, when the map was (re)built or edited
    gateway  Feed (a thread) bootstraps from snap, then applies frames in order

Cost control: publishing only happens while at least one gateway's heartbeat (<prefix>:sub:<id>)
is current -- a monolith pays nothing. When one appears, the publisher starts a new epoch with a
fresh snapshot. A frame carries

    chars       characters that changed: whole (never sent before) or a patch of changed top-level
                keys, found with the same per-key digests the websocket uses (core/entity_versions)
    del_chars   characters that no longer exist
    up          dirty props / placed_items / world_objects, whole, by id
    set / del   other top-level keys of the world whose JSON digest changed (big, slow ones are
                looked at every BIG_EVERY ticks; every FULL_EVERY ticks, and after any route saved
                the world, EVERYTHING is re-checked, so something nobody marked dirty is at most
                FULL_EVERY ticks late)
    dirty       the ids marked dirty this tick -- what the gateway builds websocket deltas from

Every operation is idempotent (set a key, upsert by id, delete if present), so a snapshot that is
newer than the frames replayed after it is harmless. A gateway that finds a gap in the sequence, or
a new epoch, simply bootstraps again.
"""

import json
import os
import threading
import time
import zlib

import redis

from core.cache import r, REDIS_HOST
from core import entity_versions as ev

FULL_EVERY = 15
BIG_BYTES = 20_000
BIG_EVERY = 10
SNAP_EVERY_TICKS = 300
FRAME_MAXLEN = 2500
SUB_TTL = 10
OWNER_TTL = 10
ENTITY_KINDS = ("props", "placed_items", "world_objects")
SKIP_KEYS = frozenset({"characters", "_dirty"})

_rb = redis.Redis(host=REDIS_HOST, port=6379)           # binary-safe (snapshots are zlib bytes)

static_gen = 0                                           # bumped when the map was rebuilt or edited


def note_static_changed():
    global static_gen
    static_gen += 1


class Channel:
    def __init__(self, prefix="replica"):
        self.rename(prefix)

    def rename(self, prefix):
        self.prefix = prefix
        self.stream = f"{prefix}:frames"
        self.snap = f"{prefix}:snap"
        self.meta = f"{prefix}:meta"
        self.static = f"{prefix}:static"
        self.want = f"{prefix}:want_snap"
        self.owner = f"{prefix}:owner"
        self.sub_prefix = f"{prefix}:sub:"


channel = Channel()


def _dumps(obj):
    return json.dumps(obj, default=str, separators=(",", ":"))


def _static_keys():
    from db import _STATIC_WORLD_KEYS
    return set(_STATIC_WORLD_KEYS)


# ---------------------------------------------------------------------------
# core side
# ---------------------------------------------------------------------------

class Publisher:
    def __init__(self, ch=None):
        self.ch = ch or channel
        self.alive_cache = {"t": 0.0, "n": 0}
        self.alive_cache_seconds = 2.0
        self.sim_id = "default"
        self.forced = False
        self.token = os.urandom(6).hex()
        self.owner_checked = 0.0
        self.owns = False
        self.stats = {"frames": 0, "snapshots": 0, "bytes": 0, "ms": 0.0, "last_ms": 0.0, "last_bytes": 0}
        self._reset()

    def _reset(self):
        self.epoch = None
        self.seq = 0
        self.chars = {}                 # cid -> {key: digest} as the replica has it
        self.keys = {}                  # top-level key -> digest as the replica has it
        self.sizes = {}                 # top-level key -> last JSON length
        self.last_full_tick = -10**9
        self.last_snap_tick = -10**9
        self.static_sent = None

    def force_full(self):
        """A route saved the world: re-check everything at the next frame."""
        self.forced = True

    def subscribers_alive(self):
        now = time.time()
        if now - self.alive_cache["t"] < self.alive_cache_seconds:
            return self.alive_cache["n"]
        try:
            n = sum(1 for _ in r.scan_iter(match=self.ch.sub_prefix + "*", count=100))
        except Exception:
            n = 0
        self.alive_cache.update(t=now, n=n)
        return n

    def forget_alive_cache(self):
        self.alive_cache["t"] = 0.0

    def _is_owner(self):
        """Only one process may publish to a channel: whoever holds <prefix>:owner. A second one (a test
        harness, a stray second core) would otherwise interleave its own world into the stream.
        The claim lasts OWNER_TTL seconds and is renewed every couple of seconds."""
        now = time.time()
        if self.owns and now - self.owner_checked < 2.0:
            return True
        cur = r.get(self.ch.owner)
        if cur == self.token:
            r.expire(self.ch.owner, OWNER_TTL)
            self.owns = True
        elif cur is None and r.set(self.ch.owner, self.token, nx=True, ex=OWNER_TTL):
            self.owns = True
        else:
            if self.owns:
                print("[replication] another process owns the replica channel; not publishing")
            self.owns = False
            self._reset()
        self.owner_checked = now
        return self.owns

    def release(self):
        """Give the channel up (shutdown), so a successor does not wait for the claim to lapse."""
        try:
            if r.get(self.ch.owner) == self.token:
                r.delete(self.ch.owner)
        except Exception:
            pass
        self.owns = False

    # -- publishing ----------------------------------------------------------------------

    def publish(self, sim_id, world, dirty):
        """Called after each tick with the world lock held. `dirty` is sim_loop.collect_dirty()'s
        result. Never raises."""
        try:
            self.sim_id = sim_id
            if not self.subscribers_alive():
                if self.epoch is not None:
                    self._reset()
                return
            if not self._is_owner():
                return
            t0 = time.perf_counter()
            if self.epoch is None:
                self._start_epoch(world)
            else:
                want = False
                try:
                    want = bool(r.get(self.ch.want))
                except Exception:
                    pass
                self._frame(world, dirty, want_snap=want)
            ms = (time.perf_counter() - t0) * 1000
            self.stats["last_ms"] = round(ms, 2)
            self.stats["ms"] += ms
        except Exception as exc:
            print(f"[replication] publish failed: {exc!r}")
            self._reset()

    def _dynamic_keys(self, world):
        static = _static_keys()
        return [k for k in world if k not in static and k not in SKIP_KEYS]

    def _digest_all(self, world):
        tick = world.get("tick", 0)
        self.chars = {cid: dict(ev.char_digests(c, tick, fresh_cold=True))
                      for cid, c in world.get("characters", {}).items() if isinstance(c, dict)}
        self.keys, self.sizes = {}, {}
        for k in self._dynamic_keys(world):
            text = _dumps(world[k])
            self.keys[k] = zlib.crc32(text.encode("utf-8", "replace"))
            self.sizes[k] = len(text)

    def _start_epoch(self, world):
        self.epoch = os.urandom(6).hex()
        self.seq = 0
        r.delete(self.ch.stream)              # frames of an earlier epoch mean nothing to anyone now
        self._digest_all(world)
        self.last_full_tick = self.last_snap_tick = world.get("tick", 0)
        self._write_static(world, force=True)
        self._write_snapshot(world)

    def _write_static(self, world, force=False):
        if not force and self.static_sent == static_gen:
            return
        import db
        cached = db._static_world_cache.get(self.sim_id) or {}
        tiles = cached.get("world_tiles") or world.get("world_tiles")
        if not tiles:
            return
        blob = zlib.compress(_dumps(tiles).encode("utf-8"), 3)
        _rb.set(self.ch.static, blob)
        self.static_sent = static_gen
        self.static_blob_bytes = len(blob)

    def _write_snapshot(self, world):
        static = _static_keys()
        body = {k: v for k, v in world.items() if k not in static and k != "_dirty"}
        blob = zlib.compress(_dumps(body).encode("utf-8"), 3)
        meta = {"epoch": self.epoch, "seq": self.seq, "tick": world.get("tick", 0),
                "static_gen": self.static_sent if self.static_sent is not None else -1, "defs_mtime": _defs_mtime(world)}
        pipe = _rb.pipeline()
        pipe.set(self.ch.snap, blob)
        pipe.set(self.ch.meta, _dumps(meta))
        pipe.delete(self.ch.want)
        pipe.execute()
        self.last_snap_tick = world.get("tick", 0)
        self.stats["snapshots"] += 1
        self.stats["last_snapshot_bytes"] = len(blob)

    def _frame(self, world, dirty, want_snap=False):
        tick = world.get("tick", 0)
        forced = self.forced                # a route saved the world: look at everything now
        self.forced = False
        chars_now = world.get("characters", {})
        frame = {"epoch": self.epoch, "seq": self.seq + 1, "tick": tick}

        # characters
        # every tick: the characters marked dirty, plus those whose staggered re-check of their rarely
        # changing keys is due (each character once per FULL_EVERY ticks, so the cost is spread)
        if forced:
            examine = list(chars_now)
        else:
            due = {cid for cid in chars_now if ev._is_cold_tick(cid, tick) or cid not in self.chars}
            examine = [cid for cid in (set(dirty.get("chars") or ()) | due) if cid in chars_now]
        out = {}
        for cid in examine:
            c = chars_now[cid]
            if not isinstance(c, dict):
                continue
            digests = ev.char_digests(c, tick, fresh_cold=forced)
            have = self.chars.get(cid)
            if have is None:
                out[cid] = c
            else:
                changed = [k for k, d in digests.items() if have.get(k) != d]
                deleted = [k for k in have if k not in digests]
                if not changed and not deleted:
                    continue
                patch = {"__patch__": True}
                for k in changed:
                    patch[k] = c[k]
                if deleted:
                    patch["__deleted__"] = deleted
                out[cid] = patch
            self.chars[cid] = dict(digests)
        if out:
            frame["chars"] = out
        gone = [cid for cid in self.chars if cid not in chars_now]
        if gone:
            frame["del_chars"] = gone
            for cid in gone:
                self.chars.pop(cid, None)
                ev.forget("char", cid)

        # dirty entities, whole, by id
        up = {}
        for kind in ENTITY_KINDS:
            ents = (dirty.get(kind) or {})
            if ents:
                up[kind] = ents
        if up:
            frame["up"] = up

        # everything else, by digest. Small keys are looked at every tick; big slow ones, and the
        # entity lists (which dirty ids already cover), once per BIG_EVERY / FULL_EVERY ticks,
        # staggered by name. A forced pass looks at all of them.
        sets, dels = {}, []
        live = set()
        for k in self._dynamic_keys(world):
            live.add(k)
            if not forced:
                if k in ENTITY_KINDS:
                    if (tick + zlib.crc32(k.encode())) % FULL_EVERY:
                        continue
                elif self.sizes.get(k, 0) > BIG_BYTES and (tick + zlib.crc32(k.encode())) % BIG_EVERY:
                    continue
            text = _dumps(world[k])
            d = zlib.crc32(text.encode("utf-8", "replace"))
            self.sizes[k] = len(text)
            if self.keys.get(k) != d:
                self.keys[k] = d
                sets[k] = text                 # already serialised; spliced into the frame below
        for k in [k for k in self.keys if k not in live]:
            del self.keys[k]
            dels.append(k)
        if dels:
            frame["del"] = dels
        frame["dirty"] = {"chars": list(set(dirty.get("chars") or ()) | set(out)), "props": list(dirty.get("props") or ()),
                          "placed_items": list(dirty.get("placed_items") or ()),
                          "world_objects": list(dirty.get("world_objects") or ())}
        if static_gen != self.static_sent:
            self._write_static(world)
        frame["static_gen"] = self.static_sent if self.static_sent is not None else -1
        frame["defs_mtime"] = _defs_mtime(world)

        text = _dumps(frame)
        if sets:
            text = text[:-1] + ',"set":{' + ",".join(f"{json.dumps(k)}:{v}" for k, v in sets.items()) + "}}"
        self.seq += 1
        r.xadd(self.ch.stream, {"p": text}, maxlen=FRAME_MAXLEN, approximate=True)
        self.stats["frames"] += 1
        self.stats["bytes"] += len(text)
        self.stats["last_bytes"] = len(text)
        if want_snap or tick - self.last_snap_tick >= SNAP_EVERY_TICKS:
            self._write_snapshot(world)


_defs_stat = {"t": 0.0, "v": 0}


def _defs_mtime(world):
    """mtime of definitions.json (a stat on a bind mount is slow, so at most every few seconds)."""
    now = time.time()
    if now - _defs_stat["t"] > 3.0:
        try:
            from core.definitions import defs_path
            _defs_stat["v"] = os.path.getmtime(defs_path(publisher.sim_id))
        except Exception:
            _defs_stat["v"] = 0
        _defs_stat["t"] = now
    return _defs_stat["v"]


publisher = Publisher()
current_feed = None                                       # the gateway's Feed, once started


# ---------------------------------------------------------------------------
# applying frames (pure; the gateway and the tests use it)
# ---------------------------------------------------------------------------

class NeedResync(Exception):
    pass


def _upsert(world, kind, ents):
    cur = world.get(kind)
    if cur is None:
        cur = world[kind] = {} if kind == "placed_items" else []
    if isinstance(cur, dict):
        cur.update(ents)
        return
    index = {e.get("id"): i for i, e in enumerate(cur) if isinstance(e, dict)}
    for eid, ent in ents.items():
        if eid in index:
            cur[index[eid]] = ent
        else:
            cur.append(ent)
            index[eid] = len(cur) - 1


def apply_frame(world, frame):
    """Apply one frame to the replica's dynamic world dict, in place."""
    chars = world.setdefault("characters", {})
    for cid, payload in (frame.get("chars") or {}).items():
        if isinstance(payload, dict) and payload.get("__patch__"):
            c = chars.get(cid)
            if c is None:
                raise NeedResync(f"patch for unknown character {cid}")
            for k, v in payload.items():
                if k not in ("__patch__", "__deleted__"):
                    c[k] = v
            for k in payload.get("__deleted__") or ():
                c.pop(k, None)
        else:
            chars[cid] = payload
    for cid in frame.get("del_chars") or ():
        chars.pop(cid, None)
    for kind, ents in (frame.get("up") or {}).items():
        _upsert(world, kind, ents)
    for k, v in (frame.get("set") or {}).items():
        world[k] = v
    for k in frame.get("del") or ():
        world.pop(k, None)


# ---------------------------------------------------------------------------
# gateway side
# ---------------------------------------------------------------------------

class Feed:
    """Keeps this process's resident world equal to the core's.

    A reader thread fetches snapshots and frames from Redis; pump() applies them. With
    manual=True the owner calls pump() itself (the gateway does, on its event-loop thread, so the
    world never changes under a websocket broadcast); otherwise the reader pumps as it goes."""

    def __init__(self, sim_id, ch=None, manual=False):
        self.sim_id = sim_id
        self.ch = ch or channel
        self.manual = manual
        self.id = f"{os.getenv('HOSTNAME', 'gw')}-{os.getpid()}"
        self.epoch = None                # None: waiting for a snapshot
        self.applied_seq = 0
        self.static_gen = None
        self.defs_mtime = None
        self.ready = threading.Event()
        self.cv = threading.Condition()
        self.counter = 0
        self.dirty = {"chars": set(), "props": set(), "placed_items": set(), "world_objects": set()}
        self.stats = {"frames": 0, "resyncs": 0, "last_tick": None}
        self._inbox = []
        self._inbox_lock = threading.Lock()
        self.need_boot = True
        self._stop = threading.Event()
        self._thread = None

    # -- lifecycle ----------------------------------------------------------------------

    def start(self):
        global current_feed
        current_feed = self
        threading.Thread(target=self._heartbeat, daemon=True, name="replica-heartbeat").start()
        self._thread = threading.Thread(target=self._run, daemon=True, name="replica-feed")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            r.delete(self.ch.sub_prefix + self.id)
        except Exception:
            pass

    def _heartbeat(self):
        while not self._stop.is_set():
            try:
                r.set(self.ch.sub_prefix + self.id, str(time.time()), ex=SUB_TTL)
            except Exception as exc:
                print(f"[replica] heartbeat failed: {exc!r}")
            self._stop.wait(3.0)

    def wait_ready(self, timeout=15.0):
        return self.ready.wait(timeout)

    def wait_for_update(self, last_counter, timeout=1.0):
        """Block until something new has arrived; returns the new counter."""
        with self.cv:
            self.cv.wait_for(lambda: self.counter != last_counter, timeout)
            return self.counter

    def take_dirty(self):
        with self.cv:
            out, self.dirty = self.dirty, {k: set() for k in self.dirty}
        return out

    def wait_applied(self, epoch, seq, timeout=5.0):
        """Block until frame `seq` of `epoch` has been applied (or the replica started over).
        True if it was applied -- what a gateway waits for after a command, so a read that follows
        a write sees it."""
        with self.cv:
            return self.cv.wait_for(
                lambda: self.epoch != epoch or self.applied_seq >= seq, timeout) and self.epoch == epoch

    # -- reader thread ------------------------------------------------------------------

    def _post(self, item):
        with self._inbox_lock:
            self._inbox.append(item)
        if self.manual:
            with self.cv:
                self.counter += 1
                self.cv.notify_all()
        else:
            self.pump()

    def _run(self):
        last_id = "0-0"
        while not self._stop.is_set():
            try:
                if self.need_boot:
                    if not self._fetch_snapshot():
                        self._stop.wait(1.0)
                        continue
                    self.need_boot = False
                    last_id = "0-0"
                resp = r.xread({self.ch.stream: last_id}, count=200, block=1000)
                for _s, entries in resp or []:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        self._post(("frame", json.loads(fields["p"])))
                        if self.need_boot:
                            break
                    if self.need_boot:
                        break
            except Exception as exc:
                print(f"[replica] feed error: {exc!r}")
                self.need_boot = True
                self._stop.wait(1.0)

    def _fetch_snapshot(self):
        meta_raw = _rb.get(self.ch.meta)
        blob = _rb.get(self.ch.snap)
        if not meta_raw or not blob:
            r.set(self.ch.want, "1", ex=30)
            return False
        meta = json.loads(meta_raw)
        world = json.loads(zlib.decompress(blob))
        tiles = None
        if self.static_gen is None or meta.get("static_gen") != self.static_gen:
            tblob = _rb.get(self.ch.static)
            if tblob:
                tiles = json.loads(zlib.decompress(tblob))
        self._post(("snapshot", world, meta, tiles))
        return True

    # -- applying (pump) ------------------------------------------------------------------

    def pump(self):
        """Apply everything fetched so far. Returns the number of frames applied."""
        with self._inbox_lock:
            items, self._inbox = self._inbox, []
        applied = 0
        for item in items:
            if item[0] == "snapshot":
                self._install(*item[1:])
            else:
                applied += self._on_frame(item[1])
        if items:
            with self.cv:
                self.counter += 1
                self.cv.notify_all()
        return applied

    def _resync(self, why):
        self.epoch = None
        self.need_boot = True
        self.stats["last_resync_reason"] = why
        try:
            r.set(self.ch.want, "1", ex=30)
        except Exception:
            pass

    def _install(self, world, meta, tiles):
        import db
        from core import world_state
        if tiles:
            db.refresh_static_world_cache(self.sim_id, tiles)
        self.static_gen = meta.get("static_gen")
        with db._world_lock:
            world_state.install_replica(self.sim_id, world)
        self.epoch = meta["epoch"]
        self.applied_seq = meta["seq"]
        self.defs_mtime = None
        self._check_defs(meta.get("defs_mtime"))
        self.stats["resyncs"] += 1
        self.stats["last_tick"] = meta.get("tick")
        self.ready.set()

    def _check_defs(self, mtime):
        if mtime and mtime != self.defs_mtime:
            if self.defs_mtime is not None:
                from core.definitions import invalidate_definitions_cache
                invalidate_definitions_cache(self.sim_id)
            self.defs_mtime = mtime

    def _on_frame(self, frame):
        from core import world_state
        import db
        if self.epoch is None:
            return 0                                    # waiting for a snapshot; frames before it mean nothing
        if frame.get("epoch") != self.epoch:
            if frame.get("epoch"):
                print(f"[replica] new epoch {frame.get('epoch')} (was {self.epoch}): starting over")
                self._resync("new epoch")
            return 0
        seq = frame.get("seq", 0)
        if seq <= self.applied_seq:
            return 0
        if seq != self.applied_seq + 1:
            self._resync(f"gap {self.applied_seq} -> {seq}")
            return 0
        entry = world_state.replica_entry(self.sim_id)
        try:
            with db._world_lock:
                apply_frame(entry.world, frame)
                entry.version += 1
                entry.snap_key = None
        except NeedResync as exc:
            self._resync(str(exc))
            return 0
        self.applied_seq = seq
        if frame.get("static_gen") != self.static_gen:
            self._resync("map changed")                 # the snapshot fetch brings the new map with it
        self._check_defs(frame.get("defs_mtime"))
        self.stats["frames"] += 1
        self.stats["last_tick"] = frame.get("tick")
        with self.cv:
            for kind, ids in (frame.get("dirty") or {}).items():
                self.dirty.setdefault(kind, set()).update(ids)
        return 1


def collect_dirty(world, ids):
    """The same shape as sim_loop.collect_dirty(), built from a replica world and dirty id sets."""
    chars = {cid: world["characters"][cid] for cid in ids.get("chars", ()) if cid in world.get("characters", {})}
    props_raw = world.get("props", {})
    props_map = props_raw if isinstance(props_raw, dict) else {p["id"]: p for p in props_raw if isinstance(p, dict) and p.get("id")}
    props = {pid: props_map[pid] for pid in ids.get("props", ()) if pid in props_map}
    placed_map = world.get("placed_items", {})
    placed = {iid: placed_map[iid] for iid in ids.get("placed_items", ()) if iid in placed_map}
    objs_by_id = {o["id"]: o for o in world.get("world_objects", []) if isinstance(o, dict) and o.get("id")}
    objs = {oid: objs_by_id[oid] for oid in ids.get("world_objects", ()) if oid in objs_by_id}
    return {"chars": chars, "props": props, "placed_items": placed, "world_objects": objs}
