"""
core/tick_state.py

Marks the thread currently running a simulation tick (main._run_tick_and_persist),
so code that must never block the world lock -- an LLM round-trip, a network fetch
-- can tell when it is being called from it. The tick holds the world lock for its
whole run, so anything slow on that thread turns every API route into "simulation
busy" and freezes the clock.
"""

import os
import threading

_local = threading.local()

# Total seconds one tick may spend blocked on model calls made from the tick
# thread itself. Past it, further calls fail immediately (callers already fall
# back to deterministic text on a failed call) instead of stalling the world.
TICK_LLM_BUDGET_SECONDS = float(os.getenv("TICK_LLM_BUDGET_SECONDS", "4"))
TICK_LLM_CALL_MAX_SECONDS = float(os.getenv("TICK_LLM_CALL_MAX_SECONDS", "3"))


def enter():
    _local.active = True
    _local.spent = 0.0


def leave():
    _local.active = False


def remaining_budget():
    return max(0.0, TICK_LLM_BUDGET_SECONDS - getattr(_local, "spent", 0.0))


def spend(seconds):
    _local.spent = getattr(_local, "spent", 0.0) + seconds


def in_tick_thread():
    return bool(getattr(_local, "active", False))
