"""
idle_quirks.py

Small, involuntary things a character does with a genuinely idle moment --
wandering the house, second-guessing whether the door's locked, pausing at a
window over an imagined sound, patting themselves down for a phone that
isn't there. None of these are decisions a character reasons about (no LLM/
middleware call): they're spontaneous, the same way curiosity.py's noticing
something or psychosis.py's erratic wander are. Rolled once per idle wake,
after a short random pause -- a person doesn't act on an idle moment the
instant it starts.

Two entry points, both called from brain/agent_loop.py::update_agent():

  maybe_delay_or_quirk(c, world)  -- called once should_think() has already
      returned "idle" and the character has nothing else going on. Returns
      True if this wake was consumed here (still pausing, or a quirk just
      started) -- the caller skips think()/the middleware entirely for it.

  advance_idle_quirk(c, world)    -- called every tick regardless of wake
      state, alongside the activity watchdog: progresses whichever quirk
      activity (if any) is currently running -- arrival, lingering,
      completion -- independent of the cognition cycle.
"""

from __future__ import annotations

import random
from typing import Optional

from brain.cognition_scheduler import wake_character
from systems.navigation import plan_character_route
from systems.props import find_nearest_prop, prop_distance

IDLE_PAUSE_TICKS = (5, 30)            # a beat before acting on idleness at all

ROAM_CHANCE = 0.10
ROAM_LINGER_TICKS = (120, 360)        # 2-6 minutes, once arrived
FORGOT_WHY_CHANCE = 0.20              # ... and can't quite remember why they came in here

CHECK_DOOR_CHANCE = 0.02
CHECK_DOOR_LINGER_TICKS = (10, 30)

LOOK_OUT_WINDOW_CHANCE = 0.05
LOOK_OUT_WINDOW_LINGER_TICKS = (30, 60)

PHONE_CHANCE = 0.30

QUIRK_TYPES = ("roam", "check_door_lock", "look_out_window")
WALK_BUDGET_TICKS = 600   # matches activity_watchdog.WALK_LIMIT_TICKS


def _lingering(c) -> bool:
    return (c.get("activity") or {}).get("type") in QUIRK_TYPES


def maybe_delay_or_quirk(c, world) -> bool:
    if c.get("activity"):
        return False   # already doing something real; not ours to touch

    tick = world.get("tick", 0)
    cog = c.setdefault("cognition", {})

    pause_until = c.get("_idle_pause_until")
    if pause_until is None:
        lo, hi = IDLE_PAUSE_TICKS
        pause_until = tick + random.randint(lo, hi)
        c["_idle_pause_until"] = pause_until
        cog["next_think_tick"] = max(cog.get("next_think_tick", tick), pause_until)
        return True
    if tick < pause_until:
        return True
    c.pop("_idle_pause_until", None)

    started = (
        _maybe_go_looking_for_phone(c, world)
        or (random.random() < ROAM_CHANCE and _start_roam(c, world))
        or (random.random() < CHECK_DOOR_CHANCE and _start_check_door(c, world))
        or (random.random() < LOOK_OUT_WINDOW_CHANCE and _start_look_out_window(c, world))
    )
    if started:
        # Nothing else re-checks should_think() while one of these runs (they
        # bypass the normal decide/note_think path entirely) -- push the next
        # cognition check out past a generous estimate of how long this one
        # could take (its own linger duration, plus real walking time), same
        # as a real decision's note_think() would. advance_idle_quirk()
        # re-arms this properly, for real, once the quirk actually finishes.
        act = c.get("activity") or {}
        cog["next_think_tick"] = tick + (act.get("duration") or 0) + WALK_BUDGET_TICKS
        return True
    return False


def advance_idle_quirk(c, world) -> None:
    act = c.get("activity")
    if not act or act.get("type") not in QUIRK_TYPES:
        return

    tick = world.get("tick", 0)
    if act.get("phase") == "walking":
        if c.get("is_moving"):
            return   # activity_watchdog already bounds an unreachable target
        act["phase"] = "using"
        act["phase_started_tick"] = tick
        return

    if tick - act.get("phase_started_tick", tick) < act.get("duration", 0):
        return

    kind = act["type"]
    if kind == "roam":
        _finish_roam(c, world)
    elif kind == "check_door_lock":
        _finish_check_door(c, world, act)
    elif kind == "look_out_window":
        _finish_look_out_window(c, world)

    c["activity"] = None
    wake_character(c, world, "activity_finished")


# ---- phone ------------------------------------------------------------------

def _maybe_go_looking_for_phone(c, world) -> bool:
    from systems.phone import ensure_phone_state
    state = ensure_phone_state(c)
    if not state.get("last_known_location") or random.random() >= PHONE_CHANCE:
        return False
    from systems.action_router import _route_retrieve_phone
    _route_retrieve_phone(c, world, {"type": "retrieve_phone"})
    return bool(c.get("activity"))


# ---- roam ---------------------------------------------------------------------

def _random_point_in_room(world, building, room) -> Optional[tuple]:
    """A real floorplan room is an irregular set of tiles (see
    resolve_floorplan()'s "tiles": [{"x","y"}, ...]), not a rectangle --
    picking uniformly from its own tiles (rather than a bounding box, which
    can cover walls or a neighbouring room for an L-shaped one) always lands
    somewhere actually inside it."""
    from systems.transforms import local_to_world
    tiles = room.get("tiles") or []
    if not tiles:
        return None
    tile = random.choice(tiles)
    return local_to_world(building, tile["x"] + 0.5, tile["y"] + 0.5)


def _start_roam(c, world) -> bool:
    from systems.navigation import find_building_at
    from systems.templates import resolve_floorplan
    building_id = c.get("building_id")
    building = next((b for b in world.get("buildings", []) if b["id"] == building_id), None)         if building_id else None
    if not building:
        # Confirmed pattern (systems/navigation.py::plan_character_route's own
        # fallback): building_id is only ever set once an indoor ROUTE
        # completes -- a character who spawned, or was placed, straight into a
        # room never has it, even while genuinely indoors and mid-activity.
        building, _ = find_building_at(world, c.get("x", 0), c.get("y", 0))
    if not building:
        return False
    floorplan = resolve_floorplan(world, building) or {}
    rooms = [r for r in floorplan.get("rooms", []) if r.get("id") != c.get("room_id")]
    random.shuffle(rooms)
    for room in rooms:
        point = _random_point_in_room(world, building, room)
        if not point:
            continue
        if not plan_character_route(world, c, point[0], point[1]):
            continue
        c["animation_state"] = "walk"
        c["is_moving"] = True
        lo, hi = ROAM_LINGER_TICKS
        c["activity"] = {"type": "roam", "phase": "walking",
                         "phase_started_tick": world.get("tick", 0),
                         "duration": random.randint(lo, hi), "target_room": room.get("id"),
                         "state": {}}
        return True
    return False


def _finish_roam(c, world) -> None:
    if random.random() < FORGOT_WHY_CHANCE:
        from brain.memory import store_memory
        store_memory(c, "You wandered in here and, for a second, couldn't remember why.",
                    importance=0.1, tags=["flavor"], tick=world.get("tick", 0), source="internal")


# ---- check the door -----------------------------------------------------------

def _nearest_home_door(c, world):
    home_id = c.get("household_id")
    household = world.get("households", {}).get(home_id) if home_id else None
    home_building_id = household.get("home_id") if household else None
    if not home_building_id:
        return None
    for building in world.get("buildings", []):
        if building["id"] != home_building_id:
            continue
        doors = [d for d in building.get("doors", []) if d.get("home_id") == home_building_id]
        if not doors:
            return None
        doors.sort(key=lambda d: (d.get("x", 0) - c.get("x", 0)) ** 2 + (d.get("y", 0) - c.get("y", 0)) ** 2)
        return home_building_id, doors[0]
    return None


def _start_check_door(c, world) -> bool:
    found = _nearest_home_door(c, world)
    if not found:
        return False
    _, door = found
    if not plan_character_route(world, c, door["x"], door["y"]):
        return False
    c["animation_state"] = "walk"
    c["is_moving"] = True
    lo, hi = CHECK_DOOR_LINGER_TICKS
    c["activity"] = {"type": "check_door_lock", "phase": "walking",
                     "phase_started_tick": world.get("tick", 0),
                     "duration": random.randint(lo, hi),
                     "state": {"door_id": door["id"]}}
    return True


def _finish_check_door(c, world, act) -> None:
    from brain.memory import store_memory
    found = _nearest_home_door(c, world)
    if not found:
        return
    _, door = found
    if door["id"] != act.get("state", {}).get("door_id"):
        return
    tick = world.get("tick", 0)
    if door.get("locked"):
        store_memory(c, "You checked -- the door was already locked.",
                    importance=0.1, tags=["flavor"], tick=tick, source="internal")
    else:
        door["locked"] = True
        store_memory(c, "It wasn't locked. You locked it.",
                    importance=0.2, tags=["flavor"], tick=tick, source="internal")


# ---- look out the window -------------------------------------------------------

def _start_look_out_window(c, world) -> bool:
    window = find_nearest_prop(c, world, tag="window")
    if not window:
        return False
    if prop_distance(c, window) > 1 and not plan_character_route(world, c, window["x"], window["y"]):
        return False
    c["animation_state"] = "walk"
    c["is_moving"] = True
    lo, hi = LOOK_OUT_WINDOW_LINGER_TICKS
    c["activity"] = {"type": "look_out_window", "phase": "walking",
                     "phase_started_tick": world.get("tick", 0),
                     "duration": random.randint(lo, hi), "target_id": window["id"], "state": {}}
    return True


def _finish_look_out_window(c, world) -> None:
    from brain.memory import store_memory
    store_memory(c, "You thought you heard something outside. Just the wind, it seems.",
                importance=0.1, tags=["flavor"], tick=world.get("tick", 0), source="internal")
