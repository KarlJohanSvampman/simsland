# =========================================================
# IN-PROCESS EVENT BUS
#
# Replaces the "run every tick just in case" pattern for
# systems that only need to act when something actually
# happened.
#
# Usage:
#   emit("character_arrested", {"character_id": cid})
#   subscribe("character_arrested", my_handler)  # called at flush()
#   flush(world)   # called once per tick after all emits
#
# Handlers signature: handler(event_data, world)
# =========================================================

from collections import defaultdict
import traceback

_subscribers: dict[str, list] = defaultdict(list)
_queue: list[tuple[str, dict]] = []


def subscribe(event_type: str, handler):
    """Register a handler for an event type. Called at import time."""
    _subscribers[event_type].append(handler)


def emit(event_type: str, data: dict | None = None):
    """Queue an event to be processed at the next flush()."""
    _queue.append((event_type, data or {}))


def flush(world):
    """
    Process all queued events. Call once per tick after sim systems
    have emitted their events.
    """
    if not _queue:
        return

    # Snapshot and clear before processing so handlers can emit new events
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
    if _queue:
        flush(world)


def clear():
    """Reset bus state (useful in tests)."""
    _queue.clear()
    _subscribers.clear()
