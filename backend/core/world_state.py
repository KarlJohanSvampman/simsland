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
import threading
import time
from contextlib import contextmanager

PERSIST_EVERY_TICKS = 15

_lock = threading.Lock()              # protects _residents / the snapshot cache bookkeeping
_residents = {}
_local = threading.local()            # per-thread: does this thread hold the world lock?
_writer_q = queue.Queue()
_writer_started = False
_stats = {"snapshots": 0, "persists": 0, "persist_ms": 0.0, "last_persist_tick": None, "last_persist_bytes": 0,
          "snapshot_ms": 0.0, "queued": 0, "write_errors": 0}


class _Resident:
    __slots__ = ("world", "version", "snap_key", "snap_json", "persisted_tick", "persisted_version")

    def __init__(self, world):
        self.world = world
        self.version = 0
        self.snap_key = None
        self.snap_json = None
        self.persisted_tick = world.get("tick", 0)
        self.persisted_version = 0


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


def resident(sim_id):
    """The live world, loaded once (from the cache or Postgres) on first use."""
    entry = _residents.get(sim_id)
    if entry is None:
        with _lock:
            entry = _residents.get(sim_id)
            if entry is None:
                import db
                entry = _residents[sim_id] = _Resident(db._load_world_cold(sim_id))
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
    body = {k: v for k, v in entry.world.items() if k not in static}
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
        text = entry.snap_json if entry.snap_key == (entry.world.get("tick"), entry.version) and entry.snap_json else _render(entry)
        entry.persisted_tick = entry.world.get("tick", 0)
        entry.persisted_version = entry.version
        _stats["persist_ms"] += (time.perf_counter() - t0) * 1000
        _stats["last_persist_bytes"] = len(text)
        _stats["queued"] += 1
        _ensure_writer()
        _writer_q.put((sim_id, text, entry.world.get("tick", 0), reason))

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
        entry.persisted_tick = entry.world.get("tick", 0)
    _writer_q.join()
    _write(sim_id, text, entry.world.get("tick", 0), "shutdown")
    return True


def _write(sim_id, text, tick, reason):
    import db
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
            # only the newest queued snapshot matters: drop older ones waiting behind it
            while True:
                try:
                    nxt = _writer_q.get_nowait()
                    _writer_q.task_done()
                    sim_id, text, tick, reason = nxt
                except queue.Empty:
                    break
            _write(sim_id, text, tick, reason)
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
