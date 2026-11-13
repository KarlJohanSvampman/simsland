"""
core/world_state.py

The authoritative world lives in memory, in the process that runs the simulation
(docs/distributed_architecture_plan.md, "the state store").

Before, every tick re-read the whole world from Redis as JSON, validated and re-serialised
all of it back (~1 MB even with two characters, growing with every character, stock and
market item), and updated the Postgres row with jsonb_set -- measured at ~130 ms per tick of
pure persistence overhead, plus 210 ms every 30 ticks for the durable save. That cost scales
with world size, not with how much actually happens in a tick.

Now:

  resident(sim_id)       the one live world dict. The tick works on it directly, so there is
                         no per-tick load, serialisation or database write.
  load(sim_id)           what db.load_world() returns:
                           * inside the world lock -> the resident world itself, so a route's
                             load -> mutate -> save works in place;
                           * outside it (read-only callers) -> a private snapshot copy, built
                             from a JSON rendering of the resident world that is made at most
                             once per tick and only when somebody asks for it.
  save(sim_id, world)    in place: mark the version and queue a durable write. A foreign dict
                         (a freshly generated world, an editor import) replaces the contents.
  after_tick(...)        every PERSIST_EVERY_TICKS ticks the world is serialised under the lock
                         and written to Postgres by a background writer thread; nothing
                         blocks on the database. persist_now() on shutdown.

Static map data (world_tiles, navigation, ...) and the definitions are never persisted or
snapshotted: they are process-local (db._STATIC_WORLD_KEYS), exactly as before.

A note on what changed semantically: the old per-tick JSON round trip silently turned tuples
into lists and int dict keys into strings. A differential run of 1500 ticks across a week
boundary (resident vs round trip, same seed) differed in only one place -- a "once per day"
guard that compared a tuple with the list it had become and therefore never matched.
"""

import json
import queue
import os
import threading
import time
from contextlib import contextmanager

PERSIST_EVERY_TICKS = int(os.getenv("WORLD_PERSIST_EVERY_TICKS", "15"))
# How the world is made durable (core/entity_store.py): "entities" -- per-entity rows, only what changed, one
# transaction per flush -- or "blob" (the whole world as one JSON value, the old way). With entities the blob is still
# written every BLOB_EVERY_TICKS (and at shutdown) as a backup and for tools that read it.
WORLD_STORE = os.getenv("WORLD_STORE", "entities").lower()
if WORLD_STORE == "entities" and "WORLD_PERSIST_EVERY_TICKS" not in os.environ:
    # only what changed is written, and with the WorldView only what was touched is rendered (~5 ms for a few
    # characters): a flush every 2 ticks, so a crash loses at most a tick or two
    PERSIST_EVERY_TICKS = 2
BLOB_EVERY_TICKS = int(os.getenv("WORLD_BLOB_EVERY_TICKS", "300"))

_lock = threading.Lock()              # protects _residents / the snapshot cache bookkeeping
_residents = {}
_local = threading.local()            # per-thread: does this thread hold the world lock?
_writer_q = queue.Queue()
_writer_started = False
_stats = {"snapshots": 0, "persists": 0, "persist_ms": 0.0, "last_persist_tick": None, "last_persist_bytes": 0,
          "snapshot_ms": 0.0, "queued": 0, "write_errors": 0}


class _Resident:
    __slots__ = ("world", "version", "snap_key", "snap_json", "persisted_tick", "persisted_version", "blob_tick")

    def __init__(self, world):
        self.world = world
        self.version = 0
        self.snap_key = None
        self.snap_json = None
        self.persisted_tick = world.get("tick", 0)
        self.persisted_version = 0
        self.blob_tick = world.get("tick", 0)


# ── who holds the world lock ──────────────────────────────────────────────────

def holding():
    return getattr(_local, "depth", 0) > 0


@contextmanager
def hold():
    """Mark this thread as holding the world lock (db.world_lock() and the tick runner do)."""
    _local.depth = getattr(_local, "depth", 0) + 1
    try:
        yield
    finally:
        _local.depth -= 1


# ── access ─────────────────────────────────────────────────────────────────────

def _static_keys():
    from db import _STATIC_WORLD_KEYS
    return set(_STATIC_WORLD_KEYS)


import os
REPLICA_MODE = os.getenv("SIM_ROLE", "all").lower() == "api"     # a gateway: the world is a copy fed by the core
REPLICA = False                                                    # ... and it has synced at least once


WORLD_VIEW = os.getenv("WORLD_VIEW", "on").lower() == "on"
FULL_FLUSH_EVERY = int(os.getenv("WORLD_FULL_FLUSH_EVERY", "20"))
_flush_count = {}


def _view(world, sim_id):
    """The resident world as a WorldView (core/world_view.py): it learns which entities each step touched."""
    if not WORLD_VIEW:
        return world
    from core import world_view
    return world_view.install(world, sim_id)


def install_replica(sim_id, world):
    """Gateway: (re)place the world with a snapshot from the core. Caller holds the world lock."""
    global REPLICA
    REPLICA = True
    entry = _residents.get(sim_id)
    if entry is None:
        _residents[sim_id] = _Resident(world)
        return
    entry.world.clear()
    entry.world.update(world)
    entry.version += 1
    entry.snap_key = None


def replica_entry(sim_id):
    return _residents[sim_id]


def resident(sim_id):
    """The live world, loaded once (from the cache or Postgres) on first use."""
    entry = _residents.get(sim_id)
    if entry is None and REPLICA_MODE:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="the world replica has not synced with the simulation core yet")
    if entry is None:
        with _lock:
            entry = _residents.get(sim_id)
            if entry is None:
                import db
                entry = _residents[sim_id] = _Resident(_view(db._load_world_cold(sim_id), sim_id))
    return entry.world


def _entry(sim_id):
    resident(sim_id)
    return _residents[sim_id]


def is_resident(sim_id, world):
    e = _residents.get(sim_id)
    return e is not None and e.world is world


def load(sim_id):
    if holding():
        return resident(sim_id)
    return snapshot(sim_id)


def _render(entry):
    """JSON of the persisted part of the world (no static map data). Caller holds the lock."""
    static = _static_keys()
    body = {k: v for k, v in dict.items(entry.world) if k not in static}      # raw: rendering touches nothing
    try:
        return json.dumps(body)
    except TypeError:
        from core.cache import safe_json_dumps
        return safe_json_dumps(body)         # raises with the path of the offending value


def snapshot(sim_id):
    """A private, mutable copy of the world for a caller that doesn't hold the world lock.
    The JSON rendering is shared by every reader within one tick."""
    import db
    entry = _entry(sim_id)
    key = (entry.world.get("tick"), entry.version)
    text = entry.snap_json if entry.snap_key == key else None
    if text is None:
        with db._world_lock:                 # the tick holds it while it mutates the world
            key = (entry.world.get("tick"), entry.version)
            if entry.snap_key != key:
                t0 = time.perf_counter()
                entry.snap_json = _render(entry)
                entry.snap_key = key
                _stats["snapshots"] += 1
                _stats["snapshot_ms"] += (time.perf_counter() - t0) * 1000
            text = entry.snap_json
    world = json.loads(text)
    static = _static_keys()
    cached = db._static_world_cache.get(sim_id)
    if cached is None:
        with db._world_lock:
            db._ensure_static_world_data(world, sim_id)
            cached = db._static_world_cache.get(sim_id) or {}
    for k in static:
        if k in cached:
            world[k] = cached[k]
    if "definitions" not in world:
        from core.definitions import load_definitions
        world["definitions"] = load_definitions(sim_id)
    return world


def save(sim_id, world):
    """Apply a route's changes. In place when `world` is the resident world."""
    import db
    if REPLICA_MODE:
        raise RuntimeError("this process serves a read replica of the world; a mutation must be a command "
                           "(core/commands.py) run by the simulation core")
    entry = _entry(sim_id)
    if entry.world is not world:
        # a foreign dict (generated world, editor import, or a stale snapshot): replace the
        # contents so everyone holding the resident object sees it
        def replace():
            static = _static_keys()
            keep = {k: entry.world[k] for k in static if k in entry.world and k not in world}
            entry.world.clear()
            entry.world.update(world)
            entry.world.update(keep)
        if holding():
            replace()
        else:
            with db._world_lock:
                replace()
    entry.version += 1
    entry.snap_key = None
    # A route changed the world (the editor, an admin or director action): whatever it changed about anyone, their
    # update sees it on the next step (brain/agent_wake.py) rather than at their next heartbeat. A declared command
    # (core/entity_locks.py) changed only what it declared: just those are woken, and the durable save is left to the
    # exclusive pass after the next step -- rendering the whole world here would read entities a running step holds.
    from core import entity_locks
    unit = entity_locks._unit() if entity_locks.ENABLED else None
    try:
        from brain import agent_wake
        chars = dict.get(entry.world, "characters") or {}
        ids = [i for k, i in unit.declared if k == "characters"] if unit is not None else list(dict.keys(chars))
        for cid in ids:
            if dict.__contains__(chars, cid):
                agent_wake.wake_now(dict.__getitem__(chars, cid), "route")
    except Exception as exc:
        print(f"[world_state] could not wake characters after a save: {exc!r}")
    try:
        from core import replication
        replication.publisher.force_full()
    except Exception:
        pass
    if unit is None:
        persist_async(sim_id, "save")


def after_tick(sim_id, world):
    """Called by the tick runner at the end of every tick, under the lock."""
    entry = _entry(sim_id)
    entry.version += 1
    if world.get("tick", 0) - entry.persisted_tick >= PERSIST_EVERY_TICKS:
        persist_async(sim_id, "interval")


# ── durable writes ──────────────────────────────────────────────────────────────

def persist_async(sim_id, reason="interval"):
    """Serialise now (the world is only safe to read while the lock is held) and let the
    writer thread do the database round trip."""
    import db
    entry = _entry(sim_id)

    def go():
        t0 = time.perf_counter()
        tick = entry.world.get("tick", 0)
        if WORLD_STORE == "entities":
            from core import entity_store
            only = _touched_since_flush(sim_id)
            n = _flush_count[sim_id] = _flush_count.get(sim_id, 0) + 1
            if only is not None and n % FULL_FLUSH_EVERY == 0:
                # every so often: compare everything, and report what changed without being touched (world_view)
                upserts, deletes, _m = entity_store.diff(sim_id, entry.world)
                from core import world_view
                world_view.note_missed([k for k in upserts if k not in only and k[0] != "meta"])
            else:
                upserts, deletes, _m = entity_store.diff(sim_id, entry.world, only=only)
            entity_store.note_written(sim_id, upserts, deletes)
            payload = ("entities", upserts, deletes)
            _stats["last_persist_bytes"] = sum(len(t) for t in upserts.values())
            if tick - entry.blob_tick >= BLOB_EVERY_TICKS or reason in ("save", "shutdown"):
                entry.blob_tick = tick
                _ensure_writer()
                _writer_q.put((sim_id, _render(entry), tick, reason + "+blob"))
        else:
            payload = entry.snap_json if entry.snap_key == (entry.world.get("tick"), entry.version) and entry.snap_json else _render(entry)
            _stats["last_persist_bytes"] = len(payload)
        entry.persisted_tick = tick
        entry.persisted_version = entry.version
        _stats["persist_ms"] += (time.perf_counter() - t0) * 1000
        _stats["queued"] += 1
        _ensure_writer()
        _writer_q.put((sim_id, payload, tick, reason))

    if holding():
        go()
    else:
        with db._world_lock:
            go()


def persist_now(sim_id):
    """Synchronous durable save (shutdown). Waits for the writer to drain first."""
    import db
    entry = _residents.get(sim_id)
    if entry is None:
        return False
    with db._world_lock:
        text = _render(entry)
        payload = None
        if WORLD_STORE == "entities":
            from core import entity_store
            upserts, deletes, _m = entity_store.diff(sim_id, entry.world)
            entity_store.note_written(sim_id, upserts, deletes)
            payload = ("entities", upserts, deletes)
        entry.persisted_tick = entry.world.get("tick", 0)
    _writer_q.join()
    _write(sim_id, text, entry.world.get("tick", 0), "shutdown")
    if payload is not None:
        _write(sim_id, payload, entry.world.get("tick", 0), "shutdown")
    return True


def _touched_since_flush(sim_id):
    """The entities the WorldView façade saw touched since the last flush (core/world_view.py), or None (compare all)."""
    try:
        from core import world_view
        return world_view.take_touched(sim_id)
    except Exception:
        return None


def _write(sim_id, text, tick, reason):
    import db
    if isinstance(text, tuple) and text and text[0] == "entities":
        from core import entity_store
        entity_store.write(sim_id, text[1], text[2], tick)
        _stats["persists"] += 1
        _stats["last_persist_tick"] = tick
        return
    if reason == "initial" and WORLD_STORE == "entities":
        _replace_entities(sim_id, json.loads(text), tick)
    t0 = time.perf_counter()
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO world (simulation_id, data)
                VALUES (%s, %s)
                ON CONFLICT (simulation_id)
                DO UPDATE SET data = EXCLUDED.data
                """,
                (sim_id, text),
            )
    _stats["persists"] += 1
    _stats["last_persist_tick"] = tick
    _stats["write_ms"] = round((time.perf_counter() - t0) * 1000, 1)


def _replace_entities(sim_id, world, tick):
    """A whole new world saved outside the resident one (a generated world, the fixture builder): its entity rows
    replace whatever this sim had, so an older set can never be loaded instead of it."""
    import db
    from core import entity_store
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            entity_store.ensure_tables(cur)
            cur.execute("DELETE FROM entities WHERE sim_id=%s", (sim_id,))
    entity_store.forget(sim_id)
    upserts, deletes, _m = entity_store.diff(sim_id, world)
    entity_store.note_written(sim_id, upserts, deletes)
    entity_store.write(sim_id, upserts, [], tick)


def _merge_payloads(a, b):
    """Two queued entity diffs as one (b is newer)."""
    ups, dels = dict(a[1]), set(a[2])
    for k, v in b[1].items():
        ups[k] = v
        dels.discard(k)
    for k in b[2]:
        ups.pop(k, None)
        dels.add(k)
    return ("entities", ups, sorted(dels))


def _ensure_writer():
    global _writer_started
    if _writer_started:
        return
    with _lock:
        if _writer_started:
            return
        _writer_started = True
    threading.Thread(target=_writer_loop, name="world-writer", daemon=True).start()


def _writer_loop():
    while True:
        sim_id, text, tick, reason = _writer_q.get()
        try:
            # Whole snapshots: only the newest queued one matters. Entity diffs are increments: merged, never dropped.
            pending = [(sim_id, text, tick, reason)]
            while True:
                try:
                    pending.append(_writer_q.get_nowait())
                    _writer_q.task_done()
                except queue.Empty:
                    break
            blob = None
            diffs = {}
            for s_id, payload, t, why in pending:
                if isinstance(payload, tuple):
                    prev = diffs.get(s_id)
                    diffs[s_id] = (_merge_payloads(prev[0], payload) if prev else payload, t, why)
                else:
                    blob = (s_id, payload, t, why)
            for s_id, (payload, t, why) in diffs.items():
                _write(s_id, payload, t, why)
            if blob:
                _write(*blob)
        except Exception as exc:
            _stats["write_errors"] += 1
            print(f"[world_state] durable write failed: {exc!r}")
        finally:
            _writer_q.task_done()


def stats():
    out = dict(_stats)
    out["residents"] = {k: {"tick": v.world.get("tick"), "version": v.version, "persisted_tick": v.persisted_tick}
                        for k, v in _residents.items()}
    return out


def reset_for_tests():
    _residents.clear()
