"""
core/sensory_event_dispatcher.py

Scaffold for the move from "poll everyone every N ticks" to "emit a change,
notify only the characters who can actually perceive it."

Design (see docs/event_driven_sensory_plan.md):
  * An entity mutation calls `emit_change(world, entity_id, change, payload)`.
  * Listeners are registered per event/change type via `register(...)`.
  * `flush(world)` runs at the end of the tick (or on demand) and dispatches
    each queued change only to characters who pass the sensory gate:
    vision (line of sight + visibility), hearing range, or direct affect.
  * One-shot follow-ups use core.scheduler.schedule_in/at via `schedule(...)`.

This module is intentionally a SCAFFOLD: it queues and filters, and calls
listeners, but it does not yet replace any existing poll job. Migration
happens job-by-job (see the plan doc) so behaviour stays identical until a
job is converted and verified with tests/determinism.py.

Sensory gate reuses brain.perception so headless simulation still honours
line-of-sight, hearing range and visibility exactly as a rendered client
would.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

_lock = threading.Lock()
_listeners: Dict[str, List[Callable]] = {}
_queue: List[Dict[str, Any]] = []


def register(change_type: str, handler: Callable) -> None:
    """Register a listener for a change type. handler(world, observer_id, event)."""
    _listeners.setdefault(change_type, []).append(handler)


def unregister(change_type: str, handler: Callable) -> None:
    if change_type in _listeners:
        try:
            _listeners[change_type].remove(handler)
        except ValueError:
            pass


def emit_change(world: Any, entity_id: str, change_type: str,
                payload: Optional[Dict[str, Any]] = None,
                direct: Optional[List[str]] = None) -> None:
    """Queue a change to an entity. `direct` lists character ids that are
    affected regardless of perception (e.g. the owner of the entity)."""
    with _lock:
        _queue.append({
            "entity_id": entity_id,
            "change_type": change_type,
            "payload": payload or {},
            "direct": list(direct or []),
        })


def can_perceive(observer_id: str, source_id: str, world: Any) -> bool:
    """Sensory gate: vision (visible_people / line of sight) or hearing range."""
    chars = (world or {}).get("characters", {}) if isinstance(world, dict) else {}
    obs = chars.get(observer_id)
    src = chars.get(source_id)
    if not obs or not src:
        return False
    # Vision: already-computed visible_people (covers LOS + visibility).
    visible = {p.get("id") for p in (obs.get("perception") or {}).get("visible_people", [])}
    if source_id in visible:
        return True
    # Hearing range.
    try:
        from brain.perception import hearing_range
        hr = hearing_range(obs)
    except Exception:
        hr = None
    if isinstance(hr, (int, float)):
        try:
            dx = (obs.get("x", 0) or 0) - (src.get("x", 0) or 0)
            dy = (obs.get("y", 0) or 0) - (src.get("y", 0) or 0)
            if (dx * dx + dy * dy) ** 0.5 <= float(hr):
                return True
        except Exception:
            pass
    # Line of sight fallback.
    try:
        from brain.perception import line_of_sight
        if line_of_sight(obs, src, world):
            return True
    except Exception:
        pass
    return False


def observers_of(world: Any, source_id: str) -> List[str]:
    """Characters who can perceive `source_id` (or are directly affected)."""
    chars = (world or {}).get("characters", {}) if isinstance(world, dict) else {}
    out = []
    for cid in chars:
        if cid == source_id:
            continue
        if can_perceive(cid, source_id, world):
            out.append(cid)
    return out


def flush(world: Any) -> int:
    """Dispatch queued changes to perceiving listeners. Returns count dispatched."""
    with _lock:
        pending = list(_queue)
        _queue.clear()
    dispatched = 0
    for ev in pending:
        ctype = ev["change_type"]
        handlers = _listeners.get(ctype, [])
        if not handlers:
            continue
        source_id = ev["entity_id"]
        targets = set(ev.get("direct", [])) | set(observers_of(world, source_id))
        for obs in targets:
            for h in handlers:
                try:
                    h(world, obs, ev)
                    dispatched += 1
                except Exception:
                    pass
    return dispatched


def schedule(world: Any, at_tick: int, change_type: str, entity_id: str,
            payload: Optional[Dict[str, Any]] = None) -> None:
    """One-shot timer that emits a change when due. Uses core.scheduler if available."""
    try:
        from core import scheduler
        def _cb(w, entry):
            emit_change(w, entity_id, change_type, payload)
        owner = f"sensory_dispatcher:{change_type}"
        scheduler.register(owner, _cb)
        scheduler.schedule(world, owner, f"{entity_id}:{change_type}", at_tick, payload or {})
    except Exception:
        # Fall back to a world-local timer list.
        world.setdefault("_sensory_timers", []).append(
            {"due": at_tick, "change_type": change_type, "entity_id": entity_id, "payload": payload or {}})


def fire_due_timers(world: Any) -> int:
    """Fire world-local fallback timers (if scheduler unavailable)."""
    timers = world.get("_sensory_timers", []) if isinstance(world, dict) else []
    due = [t for t in timers if t.get("due", 10**9) <= world.get("tick", 0)]
    for t in due:
        emit_change(world, t["entity_id"], t["change_type"], t.get("payload"))
        try:
            timers.remove(t)
        except ValueError:
            pass
    return len(due)


def stats() -> Dict[str, Any]:
    with _lock:
        return {"queued": len(_queue), "listeners": {k: len(v) for k, v in _listeners.items()}}
PY