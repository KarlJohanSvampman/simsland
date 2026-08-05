"""
systems/pain_fatigue.py

Background rest-seeking behavior for moderate pain (health_state["pain"],
20 up to systems/health.py's PAIN_CRAWL_THRESHOLD=60 -- at/above that,
apply_severity_consequences() force-sets posture="crawling" and this no
longer applies). "Moves reluctantly" as an actual behavior, not just a
speed penalty (see movement.py's fatigue speed band for that half):
whenever standing and fatigued, try to sit down; lean against a wall if
one's in reach and sitting isn't possible; sit on the floor as a last
resort, especially while c["activity"] is set (waiting for something/
someone) -- _movement_blocked() (action_router.py) already forbids new
movement in that case, so the in-place branches never touch c["activity"],
mirroring action_router.py::_route_lean_against_wall's own precedent.

Self-gated to run only every _CHECK_INTERVAL ticks per character (may do
pathfinding work -- no need for per-tick precision), except while a
seat-seeking walk is already in flight, which is checked every call so
arrival is noticed promptly.
"""

from systems.posture import set_posture

PAIN_FATIGUE_MIN     = 20
PAIN_FATIGUE_CEILING = 60  # matches health.py's PAIN_CRAWL_THRESHOLD
_CHECK_INTERVAL       = 15
_SEEK_SEAT_RADIUS      = 6

_RESTING_POSTURES = {"sitting_seat", "sitting_floor", "lying", "leaning_wall"}


def tick_pain_fatigue(c, world):
    """Call once per character per tick from agent_loop.py, right after
    process_health() so it sees the tick's final pain/posture."""
    pending = c.get("_fatigue_seek_seat")
    if pending:
        _resolve_pending_seat(c, world, pending)
        return

    tick = world.get("tick", 0)
    last_check = c.get("_fatigue_last_check", -999999)
    if tick - last_check < _CHECK_INTERVAL:
        return
    c["_fatigue_last_check"] = tick

    if not c.get("alive", True):
        return
    pain = c.get("health_state", {}).get("pain", 0.0)
    if pain < PAIN_FATIGUE_MIN or pain >= PAIN_FATIGUE_CEILING:
        return
    if c.get("posture") in _RESTING_POSTURES or c.get("posture") != "standing":
        return

    if c.get("activity"):
        # Can't move (see _movement_blocked) -- lean or sit in place,
        # without touching activity.
        _seek_rest_in_place(c, world)
    else:
        _seek_rest_with_movement(c, world)


def _seek_rest_in_place(c, world):
    from systems.walls import find_leanable_wall
    wall = find_leanable_wall(c, world)
    if wall:
        set_posture(c, world, "leaning_wall")
        c["leaning_wall_id"] = wall["wall_id"]
    else:
        set_posture(c, world, "sitting_floor")


def _seek_rest_with_movement(c, world):
    from systems.props import find_nearest_prop, prop_distance

    seat = find_nearest_prop(c, world, tag="seatable")
    if seat and prop_distance(c, seat) <= _SEEK_SEAT_RADIUS:
        if prop_distance(c, seat) <= 1:
            _sit_in_seat(c, world, seat)
            return
        from systems.navigation import plan_character_route
        if plan_character_route(world, c, seat.get("x", 0), seat.get("y", 0)):
            c["_fatigue_seek_seat"] = seat["id"]
            return

    _seek_rest_in_place(c, world)


def _resolve_pending_seat(c, world, prop_id):
    if c.get("is_moving"):
        return  # still en route

    c["_fatigue_seek_seat"] = None

    if not c.get("alive", True):
        return
    pain = c.get("health_state", {}).get("pain", 0.0)
    if pain < PAIN_FATIGUE_MIN or pain >= PAIN_FATIGUE_CEILING:
        return  # pain changed en route -- no longer relevant
    if c.get("activity") or c.get("posture") in _RESTING_POSTURES:
        return  # something else claimed this character in the meantime

    from systems.props import get_prop_by_id, prop_distance
    prop = get_prop_by_id(world, prop_id)
    if not prop or prop_distance(c, prop) > 1:
        _seek_rest_in_place(c, world)  # route failed / prop gone -- fall back
        return
    _sit_in_seat(c, world, prop)


def _sit_in_seat(c, world, prop):
    from systems.occupancy import find_free_anchor, reserve_anchor
    set_posture(c, world, "sitting_seat")
    anchor = find_free_anchor(prop, "sit")
    if anchor:
        reserve_anchor(c, prop, anchor)
    c["seat_prop_id"] = prop["id"]
