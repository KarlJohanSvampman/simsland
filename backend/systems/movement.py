from systems.personal_items import lock_home
from systems.props import get_prop_by_id
from systems.templates import get_prop_template
from systems.prop_movement import get_move_capacity, get_drag_animation, get_push_animation
import math


# =========================================================
# UPDATE ROUTE MOVEMENT
# =========================================================

OFFSET_DRAG = 0.6   # matches the pre-existing baby-carriage "in front" offset
OFFSET_PUSH = 1.1   # pusher trails further back than the dragged prop itself

# Per-character locomotion speeds (see schema_defaults.py::
# ensure_character_defaults() and the character_templates[...].instance
# overrides in definitions.json). Stored in "base units"; SPEED_TO_TILES_PER_SECOND
# (below) turns them into real tiles per second. Ratios are real-world-plausible
# relative to walk (jog ~1.8x, sprint ~3.6x, crawl/sneak both well under half).
DEFAULT_WALK_SPEED   = 0.05
DEFAULT_JOG_SPEED    = 0.09
DEFAULT_SPRINT_SPEED = 0.18
DEFAULT_CRAWL_SPEED  = 0.02
DEFAULT_SNEAK_SPEED  = 0.025

# Fatigue speed penalty while dizzy (health.py::_apply_passive_traits,
# health_state.temporary_traits) -- a flat mid-strength slowdown for the
# duration of the effect.
_DIZZY_SPEED_MULTIPLIER = 0.8

# Intoxication speed penalty (systems/harassment.py's intoxication_state) --
# starts biting at the same 25% "intoxicated" posture threshold used
# elsewhere (systems/harassment.py::_apply_intoxication_posture).
_INTOX_SPEED_THRESHOLD  = 0.25
_INTOX_MIN_MULTIPLIER   = 0.5

# animation_state values that select the jog/sprint/sneak speeds. "run" is
# kept as an alias for sprint since action_router.py's turn_and_run (panic
# flight) already sets animation_state="run" -- sprint_speed applies there
# for free. Nothing today drives "jog"/"sneak" as a real route-walking
# animation_state (jog only exists as the stationary jog exercise
# activity) -- the fields/lookup are ready for whatever sets it next.
_JOG_STATES    = ("jog",)
_SPRINT_STATES = ("sprint", "run")
_SNEAK_STATES  = ("sneak",)


def _current_move_speed(c):
    """Picks the active per-tile speed for c: an explicit c["move_speed"]
    always wins (baby.py's age-stage locomotion and pregnancy.py's
    penalty multiplier both manage that field directly and must keep
    overriding everything else); otherwise crawling posture and the
    jog/sprint/sneak animation states each pick their own template-driven
    speed, defaulting to walk."""
    if c.get("move_speed") is not None:
        return c["move_speed"]

    if c.get("posture") == "crawling":
        return c.get("crawl_speed", DEFAULT_CRAWL_SPEED)

    anim = c.get("animation_state")
    if anim in _SPRINT_STATES:
        return c.get("sprint_speed", DEFAULT_SPRINT_SPEED)
    if anim in _JOG_STATES:
        return c.get("jog_speed", DEFAULT_JOG_SPEED)
    if anim in _SNEAK_STATES:
        return c.get("sneak_speed", DEFAULT_SNEAK_SPEED)

    walk = c.get("walk_speed", DEFAULT_WALK_SPEED)
    if c.get("posture") == "standing":
        is_dizzy = "dizzy" in c.get("health_state", {}).get("temporary_traits", {})
        if is_dizzy:
            walk *= _DIZZY_SPEED_MULTIPLIER

    # Intoxication (systems/harassment.py's alcohol_level/drug_level,
    # decision #12 of the nutrition/intoxication overhaul) -- an
    # independent multiplier, same shape as the dizzy curve above but
    # keyed to intoxication_pct. Checked for both
    # "standing" and "intoxicated" postures, since intoxication_pct >=
    # INTOX_POSTURE_THRESHOLD (harassment.py) is exactly what puts a
    # character into the "intoxicated" posture in the first place.
    if c.get("posture") in ("standing", "intoxicated"):
        state = c.get("intoxication_state")
        if state:
            intox = min(1.0, state.get("alcohol_level", 0.0) + state.get("drug_level", 0.0))
            if intox >= _INTOX_SPEED_THRESHOLD:
                frac = min(1.0, (intox - _INTOX_SPEED_THRESHOLD) / (1.0 - _INTOX_SPEED_THRESHOLD))
                walk *= 1.0 - (1.0 - _INTOX_MIN_MULTIPLIER) * frac
    return walk


def _auto_lock_on_exit(c, world):
    """Lock home when character transitions from their home building to outdoor."""
    current_building = c.get("building_id")
    if not current_building:
        return
    hid = c.get("household_id")
    if not hid:
        return
    h = world.get("households", {}).get(hid, {})
    if h.get("home_id") == current_building:
        lock_home(c, world)


# Locomotion speeds are stored per character in the old "tiles per tick at 1x"
# units (walk 0.05, jog 0.09, ...) -- those fields are persisted and written by
# baby.py / pregnancy.py, so they keep their numbers and this factor converts
# them to real tiles per second. 28 puts a walk at 1.4 tiles/s (~1.4 m/s at one
# metre a tile), jog 2.5, sprint 5.0, sneak 0.7, crawl 0.55; a toddler (0.02)
# 0.56, a 5-year-old (0.04) 1.1.
SPEED_TO_TILES_PER_SECOND = 28.0

# Hard cap on waypoints crossed in one tick: a route is a few dozen tiles at
# most, this only stops a malformed one (zero-length segments forever) spinning.
_MAX_STEPS_PER_TICK = 64


def update_character_movement(c, world):
    """Advance c along its route by one tick's worth of distance.

    The distance a character can cover this tick is a budget computed once from
    their speed; it is spent across as many waypoints and route segments as it
    reaches, so movement is a steady glide at the real speed instead of one
    waypoint per tick (which made the pace depend on how far apart the
    waypoints happened to be).
    """
    state = {"budget": None, "first": True}
    result = False
    for _ in range(_MAX_STEPS_PER_TICK):
        status = _advance(c, world, state)
        state["first"] = False
        if status == "again":
            continue
        result = status == "moved"
        break
    else:
        result = True
    return result


def _advance(c, world, state):
    """One step of update_character_movement. Returns "again" when a free
    transition (waypoint arrival, segment change) happened and the budget may
    still have something left, "moved" when the tick's budget is spent (or the
    walk continues next tick), "stop" when there is nothing more to do."""

    # Defense-in-depth: a route already in flight when a character dies or
    # collapses (see systems/health.py::apply_severity_consequences)
    # shouldn't keep interpolating just because it was queued before that
    # happened — action_router.py's _movement_blocked() already stops a
    # *new* move/turn_and_run from being issued, this covers one already
    # underway.
    if c.get("alive") is False or c.get("posture") == "incapacitated":
        c["route"] = []
        c["is_moving"] = False
        return "stop"

    # A pusher has no route/move_target of their own — they're attached to
    # the prop, not independently walking. Position is driven entirely by
    # the dragger's movement, so this short-circuits before the normal
    # route logic below (which a route-less pusher would otherwise just
    # bail out of via the `if not route` check with no effect at all).
    pushing_prop_id = c.get("pushing_prop_id")
    if pushing_prop_id:
        prop = get_prop_by_id(world, pushing_prop_id)
        if prop and prop.get("being_dragged_by"):
            dragger = world.get("characters", {}).get(prop["being_dragged_by"])
            if dragger:
                ddx = dragger["x"] - prop["x"]
                ddy = dragger["y"] - prop["y"]
                ddist = math.hypot(ddx, ddy) or 1
                c["x"] = prop["x"] - (ddx / ddist) * OFFSET_PUSH
                c["y"] = prop["y"] - (ddy / ddist) * OFFSET_PUSH
            push_anim = get_push_animation(world, prop)
            if push_anim:
                c["animation_state"] = push_anim
        else:
            # Dragger let go or prop gone — detach.
            c["pushing_prop_id"] = None
        return "moved"

    route = c.get(
        "route",
        []
    )

    if not route:
        return "stop"

    segment_index = c.get(
        "route_segment_index",
        0
    )

    if segment_index >= len(route):

        c["route"] = []

        # NOT c["activity"] = None here -- activities.py::execute_activity()
        # runs BEFORE this function each tick (see agent_loop.py) and is the
        # sole authority over the activity lifecycle: its "walking" phase
        # handler waits for is_moving to clear, then transitions to "using"
        # itself. Clearing activity here raced it -- since this function
        # sets is_moving False in this exact same tick, execute_activity()
        # would only ever see is_moving turn False on the tick immediately
        # after activity was already wiped, so no walk-to-anchor activity
        # (i.e. nearly all of them, via begin_interaction/
        # request_route_to_anchor) could ever reach its "using" phase. A
        # standalone move with no activity attached (c["activity"] already
        # None) is unaffected either way.

        c["is_moving"] = False

        c["animation_state"] = "idle"

        return "stop"

    segment = route[
        segment_index
    ]

    path = segment.get(
        "tiles",
        []
    )

    path_index = c.get(
        "path_index",
        0
    )

    # =====================================
    # SEGMENT COMPLETE
    # =====================================

    if path_index >= len(path):

        c["route_segment_index"] += 1

        c["path_index"] = 0

        next_index = c[
            "route_segment_index"
        ]

        if next_index < len(route):

            next_segment = route[
                next_index
            ]

            if next_segment["type"] == "outdoor":

                # Lock home doors when character steps outside
                _auto_lock_on_exit(c, world)
                prev_building = c.get("building_id")
                c["building_id"] = None
                # Fire departure observation (incidental speech system)
                if prev_building:
                    try:
                        from systems.incidental_speech import mark_departure
                        mark_departure(c, prev_building)
                    except Exception:
                        pass

            elif next_segment["type"] == "indoor":

                new_building = next_segment.get("building_id")
                c["building_id"] = new_building

        return "again"

    # =====================================
    # NEXT TILE
    # =====================================

    tx, ty = path[path_index]

    dx = tx - c["x"]
    dy = ty - c["y"]

    dist = math.sqrt(
        dx * dx
        + dy * dy
    )

    # Counter-scale against server-side time-scale control (see
    # api/admin.py): ticks fire more often in real time as time_scale
    # increases, so dividing the per-tick step keeps *real-time* walking
    # speed constant even though more ticks are being processed per second
    # -- the one place this file needs to know about time_scale at all.
    time_scale = max(1, min(50, world.get("time_scale", 1)))
    # movement_speed_multiplier (api/admin.py's /admin/movement_speed) is the
    # independent "make everyone faster on screen" knob; 1 is real speed.
    speed_multiplier = max(1, min(200, world.get("movement_speed_multiplier", 1)))
    speed = _current_move_speed(c) * SPEED_TO_TILES_PER_SECOND / time_scale * speed_multiplier

    # =====================================
    # STUCK DETECTION (once per tick, by actual displacement)
    # =====================================
    # Nothing upstream guarantees `path`/`route` stay valid (a stale route
    # computed against a since-changed building, c["x"]/c["y"] perturbed by
    # another system). A character that stops making progress abandons the
    # route so a fresh decision happens promptly instead of leaving them
    # frozen until the next LLM cycle.
    if state["first"]:
        last_pos = c.get("_stuck_last_pos")
        if last_pos and math.hypot(c["x"] - last_pos[0], c["y"] - last_pos[1]) < max(speed * 0.25, 0.01):
            c["_stuck_ticks"] = c.get("_stuck_ticks", 0) + 1
        else:
            c["_stuck_ticks"] = 0
        c["_stuck_last_pos"] = [c["x"], c["y"]]

        if c["_stuck_ticks"] > 60:
            c["route"] = []
            c["route_segment_index"] = 0
            c["path_index"] = 0
            c["is_moving"] = False
            c["animation_state"] = "idle"
            c["_stuck_ticks"] = 0
            c["_stuck_last_pos"] = None
            return "stop"

    # Pushable prop (baby carriage / lawnmower) — apply walk_speed_modifier
    # and set the push animation directly. Previously looked up a
    # "placed_props" world key nothing ever wrote to, and a "template_id"
    # instance field that's actually called "template" — both always
    # resolved to nothing, so this silently no-op'd every tick. The
    # animation override also used to be written to
    # c["_active_locomotion_override"], which nothing anywhere ever read
    # back — fixed to set c["animation_state"] directly instead, matching
    # the already-working pattern activities.py uses for carry_walk.
    pushed_prop_id = c.get("pushed_prop_id")
    if pushed_prop_id:
        pushed_prop = get_prop_by_id(world, pushed_prop_id)
        if pushed_prop:
            prop_tpl = get_prop_template(world, pushed_prop) or {}
            speed_mod = prop_tpl.get("walk_speed_modifier", 1.0)
            speed = speed * speed_mod
            push_anim = prop_tpl.get("push_animation")
            if push_anim:
                c["animation_state"] = push_anim
        else:
            # Prop gone — detach
            c.pop("pushed_prop_id", None)

    if state["budget"] is None:
        state["budget"] = speed

    # Dragged prop (chairs/sofas/etc. — see systems/prop_movement.py)
    dragged_prop = None
    dragged_prop_id = c.get("dragged_prop_id")
    if dragged_prop_id:
        dragged_prop = get_prop_by_id(world, dragged_prop_id)
        if dragged_prop:
            drag_anim = get_drag_animation(world, dragged_prop)
            if drag_anim:
                c["animation_state"] = drag_anim
        else:
            c["dragged_prop_id"] = None

    # =====================================
    # ARRIVED TILE
    # =====================================

    if dist < 0.05:

        c["x"] = tx
        c["y"] = ty

        c["path_index"] += 1

        return "again"

    # =====================================
    # MOVE
    # =====================================

    if dist > 0:

        # Never step past the tile (a flat step overshoots and oscillates around
        # it forever -- seen live as a child jogging back and forth in a
        # bathroom), and never past what is left of this tick's budget.
        step = min(state["budget"], dist)
        state["budget"] -= step

        c["x"] += (
            dx / dist
        ) * step

        c["y"] += (
            dy / dist
        ) * step

        # Keep pushed prop in front of character
        pushed_prop_id = c.get("pushed_prop_id")
        if pushed_prop_id:
            pushed_prop = get_prop_by_id(world, pushed_prop_id)
            if pushed_prop:
                pushed_prop["x"] = c["x"] + (dx / dist) * OFFSET_DRAG
                pushed_prop["y"] = c["y"] + (dy / dist) * OFFSET_DRAG

        # Dragged prop trails BEHIND the character (negated offset, vs.
        # the pushed-prop "in front" case above). A move_capacity=2 prop
        # only actually follows once a second character has joined as
        # pusher — otherwise it deliberately stays put; the dragger can
        # still walk off without it.
        if dragged_prop_id and dragged_prop:
            capacity = get_move_capacity(dragged_prop)
            crewed = capacity == 1 or (capacity == 2 and dragged_prop.get("being_pushed_by"))
            if crewed:
                dragged_prop["x"] = c["x"] - (dx / dist) * OFFSET_DRAG
                dragged_prop["y"] = c["y"] - (dy / dist) * OFFSET_DRAG

    # budget left over means the waypoint was reached with distance to spare:
    # carry on to the next one this same tick
    return "again" if state["budget"] > 1e-9 and dist - step < 1e-9 else "moved"
