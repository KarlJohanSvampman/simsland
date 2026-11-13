"""
core/entity_locks.py -- per-entity locks in place of the one world lock (docs/distributed_architecture_plan.md, step 4).

ENTITY_LOCKS=off (the default): db._world_lock is one exclusive lock, exactly as before.
ENTITY_LOCKS=on: the world lock is a READ/WRITE lock and entities have their own locks.

    the tick's step          SHARED world lock; every entity it reaches (through the WorldView façade,
                             core/world_view.py) is locked when first reached and held to the end of the step
    a declared command       SHARED world lock; @command(name, entities=fn) names the entities it changes
                             (fn(kwargs) -> [(kind, id)]); they are all locked up front, all-or-nothing (if one is busy,
                             none is kept and it waits for a release), so it runs alongside the tick when they differ
    everything else          EXCLUSIVE world lock -- an undeclared route, a snapshot, the replication publish and the
                             persistence diff after a step: nothing else runs meanwhile, exactly as before

Deadlock: a command that reaches an entity it did not declare, held by someone else, waits for it; before anyone waits,
the waits-for chain is checked, and a command found in a cycle is aborted (LockConflict, a 409 to the caller) and lets
its locks go -- the tick is never the one aborted. An undeclared access is logged (the declaration should name it).

    lock()                    the object db._world_lock is: `with db._world_lock:` / acquire() / release() = EXCLUSIVE
    tick_unit()               context for one step (shared + entity locks)
    command_unit(entities)    context for a declared command
    stats()                   waits, conflicts, undeclared accesses, how often a command ran alongside the tick
"""

import os
import threading
import time
from contextlib import contextmanager

ENABLED = os.getenv("ENTITY_LOCKS", "off").lower() == "on"
if ENABLED and os.getenv("WORLD_VIEW", "on").lower() != "on":
    raise RuntimeError("ENTITY_LOCKS=on needs the WorldView facade (WORLD_VIEW=on): it is what sees which entities a step "
                       "reaches")


class LockConflict(Exception):
    """A command was in a lock cycle with the tick (or another command) and was aborted."""


_stats = {"tick_units": 0, "command_units": 0, "exclusive": 0, "entity_waits": 0, "conflicts": 0,
          "undeclared": 0, "concurrent_with_tick": 0}
_undeclared = {}


# ── the read/write world lock ─────────────────────────────────────────────────────────────────────────────────────────

class _RW:
    """Writer-preferring read/write lock. Shared holders are counted per thread (re-entrant); exclusive is re-entrant
    for its owner, and a thread holding exclusive may also take shared."""

    def __init__(self):
        self._cv = threading.Condition(threading.Lock())
        self._shared = {}            # thread id -> depth
        self._writer = None
        self._writer_depth = 0
        self._writers_waiting = 0

    def acquire_shared(self, timeout=None):
        me = threading.get_ident()
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            if self._writer == me or me in self._shared:
                self._shared[me] = self._shared.get(me, 0) + 1
                return True
            while self._writer is not None or self._writers_waiting:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cv.wait(left)
            self._shared[me] = 1
            return True

    def release_shared(self):
        me = threading.get_ident()
        with self._cv:
            d = self._shared.get(me, 0) - 1
            if d <= 0:
                self._shared.pop(me, None)
            else:
                self._shared[me] = d
            self._cv.notify_all()

    def acquire_exclusive(self, timeout=None):
        me = threading.get_ident()
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            if self._writer == me:
                self._writer_depth += 1
                return True
            self._writers_waiting += 1
            try:
                while self._writer is not None or any(t != me for t in self._shared):
                    left = None if deadline is None else deadline - time.monotonic()
                    if left is not None and left <= 0:
                        return False
                    self._cv.wait(left)
                self._writer, self._writer_depth = me, 1
                return True
            finally:
                self._writers_waiting -= 1

    def release_exclusive(self):
        with self._cv:
            self._writer_depth -= 1
            if self._writer_depth <= 0:
                self._writer, self._writer_depth = None, 0
            self._cv.notify_all()

    def holds(self):
        me = threading.get_ident()
        return self._writer == me or me in self._shared


_rw = _RW()


class _WorldLock:
    """What db._world_lock is with entity locks on: the EXCLUSIVE side of the world lock, with Lock's interface."""

    def acquire(self, blocking=True, timeout=-1):
        _stats["exclusive"] += 1
        return _rw.acquire_exclusive(None if (blocking and timeout in (-1, None)) else (timeout if blocking else 0))

    def release(self):
        _rw.release_exclusive()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    def locked(self):
        return _rw._writer is not None


def lock():
    return _WorldLock() if ENABLED else threading.Lock()


# ── entity locks ──────────────────────────────────────────────────────────────────────────────────────────────────────

_meta = threading.Condition(threading.Lock())
_owner = {}              # (kind, id) -> thread id
_waiting_for = {}        # thread id -> (kind, id) it is waiting for
_units = {}              # thread id -> unit
_local = threading.local()


class _Unit:
    def __init__(self, kind, declared=None):
        self.kind = kind                         # "tick" | "command"
        self.declared = set(declared or ())
        self.held = set()
        self.abort = False


def _unit():
    return getattr(_local, "unit", None)


def _cycle(me, key):
    """Would `me` waiting for `key` close a cycle? Follows owner -> what that owner waits for -> its owner ..."""
    seen = set()
    k = key
    while k is not None:
        owner = _owner.get(k)
        if owner is None:
            return None
        if owner == me:
            return k
        if owner in seen:
            return None
        seen.add(owner)
        k = _waiting_for.get(owner)
    return None


def _acquire(unit, key):
    me = threading.get_ident()
    with _meta:
        while True:
            owner = _owner.get(key)
            if owner is None or owner == me:
                _owner[key] = me
                unit.held.add(key)
                _waiting_for.pop(me, None)
                return
            if unit.abort:
                _waiting_for.pop(me, None)
                raise LockConflict(f"aborted while waiting for {key}")
            if _cycle(me, key) is not None:
                _stats["conflicts"] += 1
                if unit.kind == "command":
                    _waiting_for.pop(me, None)
                    raise LockConflict(f"lock cycle on {key}")
                other = _units.get(owner)              # the tick never yields: the command in the cycle does
                if other is not None:
                    other.abort = True
                    _meta.notify_all()
            _waiting_for[me] = key
            _stats["entity_waits"] += 1
            _meta.wait(0.01)


def _release_all(unit):
    with _meta:
        for key in unit.held:
            if _owner.get(key) == threading.get_ident():
                del _owner[key]
        unit.held.clear()
        _waiting_for.pop(threading.get_ident(), None)
        _meta.notify_all()


# Top-level keys that are not locked: read-mostly clock/definition values, and the dirty-id sets every writer adds to
# (set.add is atomic under the GIL). Locking them would make every command wait on (and cycle with) every step.
LOCK_FREE_KEYS = {"tick", "sim_time", "calendar", "definitions", "_dirty", "simulation_id"}


def _on_access(kind, key):
    """WorldView hook: an entity is being reached. Inside a unit, it is locked (once) for the rest of the unit."""
    unit = _unit()
    if unit is None or (kind, key) in unit.held or (kind == "key" and key in LOCK_FREE_KEYS):
        return
    k = (kind, key)
    if unit.kind == "command" and k not in unit.declared:
        _stats["undeclared"] += 1
        _undeclared[k] = _undeclared.get(k, 0) + 1
    _acquire(unit, k)


def install():
    """Hook into the façade (core/world_view.py): with locks on, every access is seen (not only the first per flush)."""
    from core import world_view
    if _on_access not in world_view.access_hooks:
        world_view.access_hooks.append(_on_access)
    world_view._LOCKS = True


@contextmanager
def _enter(unit):
    from core import world_state
    me = threading.get_ident()
    _local.unit = unit
    _units[me] = unit
    try:
        with world_state.hold():
            yield unit
    finally:
        _release_all(unit)
        _units.pop(me, None)
        _local.unit = None


@contextmanager
def tick_unit():
    """One step of the tick: shared world lock, entity locks as they are reached."""
    if not ENABLED:
        raise RuntimeError("tick_unit() needs ENTITY_LOCKS=on")
    install()
    _rw.acquire_shared()
    _stats["tick_units"] += 1
    try:
        with _enter(_Unit("tick")) as u:
            yield u
    finally:
        _rw.release_shared()


@contextmanager
def command_unit(entities, timeout=30.0):
    """A declared command: shared world lock and its entities, all up front (all-or-nothing)."""
    install()
    declared = sorted({(k, str(i)) for k, i in entities})
    if not _rw.acquire_shared(timeout):
        raise LockConflict("the world is held exclusively")
    try:
        unit = _Unit("command", declared)
        me = threading.get_ident()
        deadline = time.monotonic() + timeout
        with _meta:
            while True:
                busy = [k for k in declared if _owner.get(k) not in (None, me)]
                if not busy:
                    for k in declared:
                        _owner[k] = me
                        unit.held.add(k)
                    break
                if time.monotonic() > deadline:
                    raise LockConflict(f"entities busy: {busy[:3]}")
                _meta.wait(0.01)
        _stats["command_units"] += 1
        if any(u.kind == "tick" for u in _units.values()):
            _stats["concurrent_with_tick"] += 1
        with _enter(unit) as u:
            yield u
    finally:
        _rw.release_shared()


def in_unit():
    return _unit() is not None


def stats():
    return dict(_stats, undeclared_top=sorted(_undeclared.items(), key=lambda kv: -kv[1])[:10])
