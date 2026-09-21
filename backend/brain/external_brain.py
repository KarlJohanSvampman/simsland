"""
brain/external_brain.py

Tiny shared state for the standalone AI middleware (../middleware).

A character flagged c["external_brain"] = True is decided for by the
middleware instead of by brain/llm_brain.py::think(). To make sure a dead
middleware can never freeze those characters, the flag is only honored
while the middleware has recently talked to api/middleware_bridge.py
(heartbeat). If the heartbeat goes stale, update_agent() falls straight
back to the built-in think() path.

The heartbeat is process-local on purpose: the tick loop and the /mw routes
run in the same uvicorn process, and nothing here needs to survive a restart.
"""

import os
import time

ALIVE_SECONDS = float(os.getenv("MIDDLEWARE_ALIVE_SECONDS", "30"))

# Phase 1 middleware only makes needs/solo/one-line social choices. Anything that
# needs real dialogue is handed straight back to the built-in brain until the
# cognition-aware contract (spec Phase 2) lets the middleware speak.
LEGACY_WAKES = {"heard_speech", "provoked"}

_last_seen = 0.0


def touch():
    global _last_seen
    _last_seen = time.monotonic()


def middleware_alive():
    return _last_seen > 0 and (time.monotonic() - _last_seen) < ALIVE_SECONDS


def wants_middleware(c):
    """Flagged for the middleware, and not currently in a moment it can't handle yet."""
    if not c.get("external_brain"):
        return False
    if c.get("conversation"):
        return False
    return (c.get("cognition") or {}).get("wake_reason") not in LEGACY_WAKES


def is_external(c):
    """True when this character's decisions are currently owned by the middleware."""
    return wants_middleware(c) and middleware_alive()
