"""
core/tick_profile.py

Where the tick spends its time, section by section -- step 0 of the move away from a
single main tick (docs/distributed_architecture_plan.md).

`tick()` is one long function with no section boundaries, so it is instrumented with
`mark("label")` calls: the time between one mark and the next is attributed to the
label of the earlier one. A mark is ~1 microsecond, so there is one before every
cadence-gated block and every section header.

For each label we keep: how many ticks reached it, total/max/last seconds, and how often it
did real work (took longer than ACTIVE_THRESHOLD) -- the "polling that nearly always does
nothing" signal the migration is built on. Read it from /admin/tick_profile.
"""

import threading
import time

ACTIVE_THRESHOLD = 0.0005     # a section that took longer than this did something
_lock = threading.Lock()
_stats = {}                    # label -> {"calls", "active", "total", "max", "last"}
_ticks = {"count": 0, "total": 0.0, "max": 0.0, "last": 0.0, "slow": 0}
_state = threading.local()


def begin_tick():
    _state.prev = None
    _state.prev_t = 0.0
    _state.tick_start = time.perf_counter()
    _state.local = {}


def mark(label):
    """Close the previous section (attributing the elapsed time to it) and open `label`."""
    now = time.perf_counter()
    prev = getattr(_state, "prev", None)
    if prev is not None:
        local = _state.local
        local[prev] = local.get(prev, 0.0) + (now - _state.prev_t)
    _state.prev = label
    _state.prev_t = now


def end_tick():
    now = time.perf_counter()
    prev = getattr(_state, "prev", None)
    if prev is None:
        return
    local = _state.local
    local[prev] = local.get(prev, 0.0) + (now - _state.prev_t)
    total = now - _state.tick_start
    with _lock:
        for label, secs in local.items():
            s = _stats.setdefault(label, {"calls": 0, "active": 0, "total": 0.0, "max": 0.0, "last": 0.0})
            s["calls"] += 1
            s["total"] += secs
            s["last"] = secs
            if secs > s["max"]:
                s["max"] = secs
            if secs > ACTIVE_THRESHOLD:
                s["active"] += 1
        _ticks["count"] += 1
        _ticks["total"] += total
        _ticks["last"] = total
        _ticks["max"] = max(_ticks["max"], total)
        if total > 1.0:
            _ticks["slow"] += 1
    _state.prev = None


def report(top=None):
    with _lock:
        rows = []
        for label, s in _stats.items():
            rows.append({
                "section": label,
                "ticks_reached": s["calls"],
                "ticks_active": s["active"],
                "active_pct": round(100.0 * s["active"] / s["calls"], 1) if s["calls"] else 0.0,
                "total_s": round(s["total"], 3),
                "avg_ms": round(1000.0 * s["total"] / s["calls"], 3) if s["calls"] else 0.0,
                "avg_active_ms": round(1000.0 * s["total"] / s["active"], 2) if s["active"] else 0.0,
                "max_ms": round(1000.0 * s["max"], 2),
            })
        from core.section_registry import classify
        for r in rows:
            info = classify(r["section"])
            r["kind"], r["owner"], r["becomes"] = info if info else ("UNCLASSIFIED", None, None)
        rows.sort(key=lambda r: -r["total_s"])
        by_kind = {}
        for r in rows:
            k = by_kind.setdefault(r["kind"], {"sections": 0, "total_s": 0.0, "active_ticks": 0, "reached_ticks": 0})
            k["sections"] += 1
            k["total_s"] = round(k["total_s"] + r["total_s"], 3)
            k["active_ticks"] += r["ticks_active"]
            k["reached_ticks"] += r["ticks_reached"]
        ticks = dict(_ticks)
    ticks["avg_ms"] = round(1000.0 * ticks["total"] / ticks["count"], 2) if ticks["count"] else 0.0
    ticks["max_ms"] = round(1000.0 * ticks.pop("max"), 1)
    ticks["last_ms"] = round(1000.0 * ticks.pop("last"), 1)
    ticks["total_s"] = round(ticks.pop("total"), 2)
    for k in by_kind.values():
        k["active_pct"] = round(100.0 * k["active_ticks"] / k["reached_ticks"], 1) if k["reached_ticks"] else 0.0
    return {"ticks": ticks, "by_kind": by_kind, "sections": rows[:top] if top else rows}


def reset():
    with _lock:
        _stats.clear()
        _ticks.update({"count": 0, "total": 0.0, "max": 0.0, "last": 0.0, "slow": 0})
