"""
systems/memory_trace.py -- every time a character's memory is touched, for VR "Memory debug" (a timeline:
frontend/src/vrMemory.js, /admin/memtrace/{id}). Kept on the character, newest last, c["memory_trace"] (the latest
KEPT):

    stm_write     a memory stored in short-term memory (brain/memory.py::store_memory)
    stm_read      short-term memories recalled (recall / recall_relevant / recall_with_filters / biased_recall),
                  with which ones and who asked (the calling module.function)
    ltm_read      long-term memories recalled (the same calls, when what came back is from long-term memory)
    ltm_commit    a memory moved into long-term memory (systems/memory_consolidation.py): kept as it was, or the
                  hour's summary
    aggregation   an hourly consolidation: how many memories were folded into a summary, how many kept as they
                  were; also when the AI couldn't summarise and it will try again
    forget        short-term memories dropped: random forgetting every few hours, or the hard cap (prune)

Only the outermost call is recorded (recall_relevant calling recall is one read).
"""

import sys
import threading

KEPT = 300
TEXT_CHARS = 140
_local = threading.local()


def _tick(world=None, tick=None):
    if tick:
        return tick
    if world:
        return world.get("tick", 0)
    try:
        from brain import intentions
        return intentions._CURRENT_TICK
    except Exception:
        return 0


def _caller(depth=3):
    f = sys._getframe(depth)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if mod not in (__name__, "brain.memory"):
            return f"{mod.split('.')[-1]}.{f.f_code.co_name}"
        f = f.f_back
    return "?"


def note(c, kind, items=(), world=None, tick=None, detail=None, caller=None, **extra):
    if not isinstance(c, dict):
        return
    items = list(items or [])
    e = {"tick": _tick(world, tick), "kind": kind, "n": len(items),
         "ids": [m.get("id") for m in items if isinstance(m, dict)][:12],
         "texts": [str(m.get("text") or "")[:TEXT_CHARS] for m in items if isinstance(m, dict)][:6],
         "by": caller or _caller()}
    if detail:
        e["detail"] = str(detail)[:300]
    e.update(extra)
    log = c.setdefault("memory_trace", [])
    log.append(e)
    del log[:-KEPT]


def traced_store(fn):
    import functools

    @functools.wraps(fn)
    def wrapped(c, text, *a, **kw):
        mem = fn(c, text, *a, **kw)
        if mem and not getattr(_local, "depth", 0):
            note(c, "stm_write", [mem], tick=mem.get("tick") or kw.get("tick"), caller=_caller(2),
                 importance=mem.get("importance"))
        return mem
    return wrapped


def traced_recall(fn):
    import functools

    @functools.wraps(fn)
    def wrapped(c, *a, **kw):
        depth = getattr(_local, "depth", 0)
        _local.depth = depth + 1
        try:
            out = fn(c, *a, **kw)
        finally:
            _local.depth = depth
        if depth == 0 and isinstance(c, dict):
            try:
                ltm_ids = {m.get("id") for m in c.get("long_term_memory") or [] if isinstance(m, dict)}
                got = [m for m in (out or []) if isinstance(m, dict)]
                lt = [m for m in got if m.get("id") in ltm_ids]
                st = [m for m in got if m.get("id") not in ltm_ids]
                world = kw.get("world") or next((x for x in a if isinstance(x, dict) and "characters" in x), None)
                who = _caller(2)
                q = a[0] if a and isinstance(a[0], (str, list, tuple)) else kw.get("query") or kw.get("query_or_tags")
                q = " ".join(q) if isinstance(q, (list, tuple)) else q
                if st or not lt:
                    note(c, "stm_read", st, world=world, caller=who, how=fn.__name__, query=(str(q)[:80] if q else None))
                if lt:
                    note(c, "ltm_read", lt, world=world, caller=who, how=fn.__name__, query=(str(q)[:80] if q else None))
            except Exception:
                pass
        return out
    return wrapped


def traced_prune(fn):
    import functools

    @functools.wraps(fn)
    def wrapped(c, *a, **kw):
        before = list(c.get("memories") or []) if isinstance(c, dict) else []
        out = fn(c, *a, **kw)
        try:
            kept = {id(m) for m in c.get("memories") or []}
            gone = [m for m in before if id(m) not in kept]
            if gone:
                note(c, "forget", gone, caller=_caller(2), why="over the cap (pruned)")
        except Exception:
            pass
        return out
    return wrapped
