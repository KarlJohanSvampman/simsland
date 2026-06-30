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
import traceback

_subscribers: dict[str, list] = defaultdict(list)
_queue: list[tuple[str, dict]] = []
_lock = threading.Lock()


def subscribe(event_type: str, handler):
    """Register a handler for an event type. Called at import time."""
    _subscribers[event_type].append(handler)


def emit(event_type: str, data: dict | None = None):
    """Queue an event. Thread-safe — may be called from worker threads."""
    with _lock:
        _queue.append((event_type, data or {}))


def flush(world):
    """
    Process all queued events. Call once per tick (main thread only)
    after all agent workers have finished.
    """
    with _lock:
        if not _queue:
            return
        pending = list(_queue)
        _queue.clear()

    for event_type, data in pending:
        for handler in _subscribers.get(event_type, []):
            try:
                handler(data, world)
            except Exception:
                print(f"[event_bus] Error in handler for '{event_type}':")
                traceback.print_exc()

    # If handlers emitted new events, process those too (one level deep)
    with _lock:
        has_more = bool(_queue)
    if has_more:
        flush(world)


def clear():
    """Reset bus state (useful in tests)."""
    with _lock:
        _queue.clear()
        _subscribers.clear()
