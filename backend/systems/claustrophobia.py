"""
systems/claustrophobia.py

If a character is trying to get somewhere (is_moving, or mid-"walking"
phase of an activity) and their actual position hasn't meaningfully
changed over a real stretch of time, they're stuck -- deliberately
detected this way (raw position-vs-time, not a specific "can't leave a
room" flag) so it catches ANY real movement failure, not just the one
found live this session (a mechanical intention-loop trap that froze a
character outside a house for hours). Builds real, escalating panic the
longer they stay stuck; past a threshold, actively looks for a real
window prop in their current building and climbs out through it if one
exists. If none does, panic caps out and the character just gets a real,
one-time stress/memory hit -- no invented "trapped forever" spiral.

c["claustrophobia"] = {
    "stuck_ticks": int,       # accumulated time with no real progress
    "last_x", "last_y": float | None,   # position snapshot for comparison
    "last_check_tick": int,
    "panic": float,           # 0-100, decays once no longer stuck
    "escaped_via_window": bool,   # this stuck episode already tried/used one
}
"""

import random

STUCK_CHECK_INTERVAL   = 30     # ticks between position snapshots
POSITION_EPSILON       = 0.5    # smaller real movement than this counts as "stuck"
STUCK_THRESHOLD_TICKS  = 300    # 5 minutes stuck before panic starts building
PANIC_PER_CHECK        = 8.0
PANIC_DECAY_PER_CHECK  = 15.0   # once moving again, panic drains fast -- relief is immediate
STRESS_PER_CHECK       = 4.0
WINDOW_ESCAPE_PANIC_THRESHOLD = 40.0
MAX_PANIC              = 100.0

_PANIC_LINES = [
    (20,  "I need to get out of here."),
    (45,  "I really need to get out of here -- this is starting to freak me out."),
    (70,  "I can't stay in here, I need out, NOW."),
    (100, "I CAN'T BREATHE, I NEED TO GET OUT OF HERE!"),
]


def _panic_line(panic):
    for threshold, line in _PANIC_LINES:
        if panic <= threshold:
            return line
    return _PANIC_LINES[-1][1]


def _ensure_state(c):
    return c.setdefault("claustrophobia", {
        "stuck_ticks": 0,
        "last_x": None,
        "last_y": None,
        "last_check_tick": 0,
        "panic": 0.0,
        "escaped_via_window": False,
    })


def _is_trying_to_move(c):
    # Live bug report: a character waiting at a bus stop (travel_state
    # "waiting_for_bus"/"awaiting_bus_arrival", or riding in/waiting on a
    # car via "driving_out"/"driving_back") has is_moving stuck True the
    # whole time they're paused there -- a deliberate, expected hold, not
    # a failed movement attempt -- so this module read it as "trying to
    # move but making no progress" and built full panic/stress on a
    # perfectly calm character standing at a bus stop. None of
    # TRAVEL_FROZEN_STATES represent someone actually trying and failing
    # to move.
    from systems.travel import TRAVEL_FROZEN_STATES
    if c.get("travel_state") in TRAVEL_FROZEN_STATES:
        return False
    if c.get("is_moving"):
        return True
    act = c.get("activity") or {}
    return act.get("phase") == "walking"


def _find_window_in_building(world, building_id):
    """A real window prop in the character's current building, or None."""
    if not building_id:
        return None
    defs = world.get("definitions", {})
    prop_templates = defs.get("prop_templates", {})
    for prop in world.get("props", []):
        if prop.get("building_id") != building_id:
            continue
        tmpl = prop_templates.get(prop.get("template"), {})
        if "window" in tmpl.get("tags", []):
            return prop
    return None


def _climb_out_window(c, world, window_prop):
    """Places the character just outside the building at the window's own
    tile -- an escape, not a normal walk-there-and-use activity, since the
    whole point is bypassing whatever's blocking normal movement."""
    from systems.props import get_anchor
    anchor = get_anchor(window_prop, "anchor_look_out") or window_prop
    c["x"] = anchor.get("x", window_prop.get("x", c.get("x", 0)))
    c["y"] = anchor.get("y", window_prop.get("y", c.get("y", 0)))
    c["building_id"] = None
    from systems.occupancy import interrupt_activity
    interrupt_activity(c, world)
    c["is_moving"] = False
    c["animation_state"] = "idle"

    from brain.memory import store_memory
    store_memory(
        c, "Panicked, climbed out a window just to get outside.", 0.7,
        ["panic", "claustrophobia"], "claustrophobia", world.get("tick", 0),
    )

    from core.event_bus import emit
    from brain.cognition_scheduler import wake_character
    emit("claustrophobia_escaped", {"character_id": c["id"]})
    wake_character(c, world, "activity_aborted")


def tick_claustrophobia(world):
    """Periodic sweep (see sim_loop.py's cadence wiring) -- cheap position
    comparison for every character, real escalation only for the rare
    stuck ones."""
    tick = world.get("tick", 0)
    chars = world.get("characters", {})

    for c in chars.values():
        if not c.get("alive", True) or c.get("off_grid"):
            continue

        state = _ensure_state(c)
        if tick - state["last_check_tick"] < STUCK_CHECK_INTERVAL:
            continue

        x, y = c.get("x", 0), c.get("y", 0)
        moved = (
            state["last_x"] is None
            or abs(x - state["last_x"]) > POSITION_EPSILON
            or abs(y - state["last_y"]) > POSITION_EPSILON
        )
        state["last_x"], state["last_y"], state["last_check_tick"] = x, y, tick

        if moved or not _is_trying_to_move(c):
            state["stuck_ticks"] = 0
            state["escaped_via_window"] = False
            if state["panic"] > 0:
                state["panic"] = max(0.0, state["panic"] - PANIC_DECAY_PER_CHECK)
            continue

        state["stuck_ticks"] += STUCK_CHECK_INTERVAL
        if state["stuck_ticks"] < STUCK_THRESHOLD_TICKS:
            continue

        state["panic"] = min(MAX_PANIC, state["panic"] + PANIC_PER_CHECK)
        c["stress"] = min(100.0, c.get("stress", 0.0) + STRESS_PER_CHECK)

        try:
            from systems.incidental_speech import fire_incidental
            fire_incidental(c, "distressed", _panic_line(state["panic"]), world)
        except Exception:
            pass

        if state["panic"] >= WINDOW_ESCAPE_PANIC_THRESHOLD and not state["escaped_via_window"]:
            window = _find_window_in_building(world, c.get("building_id"))
            if window:
                state["escaped_via_window"] = True
                _climb_out_window(c, world, window)
                state["stuck_ticks"] = 0
                state["panic"] = max(0.0, state["panic"] - 30.0)
                continue

        if state["panic"] >= MAX_PANIC and random.random() < 0.05:
            from brain.memory import store_memory
            store_memory(
                c, "Had a full-blown panic attack, trapped with no way out.", 0.85,
                ["panic", "claustrophobia", "trauma"], "claustrophobia", tick,
            )
            c["stress"] = 100.0
