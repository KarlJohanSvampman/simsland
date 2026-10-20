# =========================================================
# IN-PROCESS EVENT BUS
#
# Thread-safe: emit() may be called from worker threads
# (e.g. parallel agent loops). flush() is always called
# from the main sim tick thread.
#
# Usage:
#   emit("character_arrested", {"character_id": cid})
#   subscribe("character_arrested", my_handler)  # called at flush()
#   flush(world)   # called once per tick after all emits
#
# Handlers signature: handler(event_data, world)
# =========================================================

from collections import defaultdict
import threading
import time
import traceback

_subscribers: dict[str, list] = defaultdict(list)
_queue: list[tuple[str, dict]] = []
_lock = threading.Lock()

# Recursive flush depth cap — a handler that emits another event (e.g. the
# incident_created -> ... -> responder_dispatched chain) must not be able to
# recurse forever if a cycle ever forms.
_MAX_FLUSH_DEPTH = 4
_MAX_QUEUE = 5000

_emit_counts: dict[str, int] = defaultdict(int)
_handled_counts: dict[str, int] = defaultdict(int)
_dropped_count = 0
_queue_overflow_warned = False
_depth_exceeded_count = 0


def subscribe(event_type: str, handler):
    """Register a handler for an event type. Called at import time."""
    _subscribers[event_type].append(handler)


def emit(event_type: str, data: dict | None = None):
    """Queue an event. Thread-safe — may be called from worker threads."""
    global _dropped_count, _queue_overflow_warned
    with _lock:
        if len(_queue) >= _MAX_QUEUE:
            _dropped_count += 1
            if not _queue_overflow_warned:
                _queue_overflow_warned = True
                print(
                    f"[event_bus] Queue exceeded {_MAX_QUEUE} — dropping events. "
                    "flush() may not be running."
                )
            return
        _queue.append((event_type, data or {}))
        _emit_counts[event_type] += 1
    # Durable log of everything that happens (core/event_log.py); no serialisation here.
    try:
        from core import event_log
        event_log.record(event_type, data or {})
    except Exception:
        pass


def dispatch(event_type, data, world):
    """Run every handler subscribed to event_type for one event, timing each one.
    Returns [(handler name, ok, error text or None)] -- used by flush() and by
    event_log.replay()."""
    from core import event_log
    results = []
    for handler in _subscribers.get(event_type, []):
        t0 = time.perf_counter()
        ok, err = True, None
        try:
            handler(data, world)
            _handled_counts[event_type] += 1
        except Exception as exc:
            ok, err = False, repr(exc)[:300]
            print(f"[event_bus] Error in handler for '{event_type}':")
            traceback.print_exc()
        event_log.note_handled(event_type, handler, time.perf_counter() - t0, ok)
        results.append((getattr(handler, "__qualname__", repr(handler)), ok, err))
    return results


def flush(world, _depth=0):
    """
    Process all queued events. Call once per tick (main thread only)
    after all agent workers have finished.
    """
    global _depth_exceeded_count
    if _depth >= _MAX_FLUSH_DEPTH:
        with _lock:
            has_more = bool(_queue)
        if has_more:
            _depth_exceeded_count += 1
            print(
                f"[event_bus] flush() hit max depth ({_MAX_FLUSH_DEPTH}) with "
                "events still queued — bailing this tick to avoid unbounded recursion."
            )
        return

    with _lock:
        if not _queue:
            return
        pending = list(_queue)
        _queue.clear()

    for event_type, data in pending:
        dispatch(event_type, data, world)

    # If handlers emitted new events, process those too, up to the depth cap.
    with _lock:
        has_more = bool(_queue)
    if has_more:
        flush(world, _depth=_depth + 1)


def stats() -> dict:
    """Snapshot of bus activity — emitted/handled counts, queue depth, drops."""
    with _lock:
        queue_depth = len(_queue)
    return {
        "emitted": dict(_emit_counts),
        "handled": dict(_handled_counts),
        "total_emitted": sum(_emit_counts.values()),
        "total_handled": sum(_handled_counts.values()),
        "queue_depth": queue_depth,
        "dropped": _dropped_count,
        "depth_exceeded_count": _depth_exceeded_count,
        "subscriber_counts": {k: len(v) for k, v in _subscribers.items()},
    }


def clear():
    """Reset bus state (useful in tests)."""
    global _dropped_count, _queue_overflow_warned, _depth_exceeded_count
    with _lock:
        _queue.clear()
        _subscribers.clear()
        _emit_counts.clear()
        _handled_counts.clear()
        _dropped_count = 0
        _queue_overflow_warned = False
        _depth_exceeded_count = 0
