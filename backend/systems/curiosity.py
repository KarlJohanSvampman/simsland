"""
systems/curiosity.py

Curiosity-driven novelty reaction and investigation -- see
schema_defaults.py's 0-100 "curiosity" field. When a curious character
notices something out of the ordinary (a nearby incident, or a loud/
high/intense audible event -- see brain/perception.py's VOLUME_TIERS),
they may abort what they're doing, react physically, and go take a
closer look. Reuses systems/activity_queue.py's existing suspend/resume
interrupt mechanism and brain/cognition_scheduler.py's wake system
rather than building parallel plumbing for either.
"""

import random

CURIOSITY_CHECK_INTERVAL = 10   # ticks between checks per character
CURIOSITY_MIN_TO_REACT   = 15   # below this, basically never reacts
CURIOSITY_MAX_ROLL_CHANCE = 0.5  # even at curiosity=100, caps per-check odds
CURIOSITY_APPROACH_MAX_DISTANCE = 3  # "close enough to see," not officially participating
_SEEN_INCIDENTS_CAP = 20

_NOTABLE_VOLUMES = ("high", "loud", "intense")


def tick_curiosity(c, world):
    """Call once per character per tick from agent_loop.py, same hook
    point as tick_pain_fatigue/tick_pain_complaints."""
    if not c.get("alive", True):
        return

    if c.get("_investigating"):
        _resolve_investigation(c, world)
        return

    tick = world.get("tick", 0)
    last_check = c.get("_curiosity_last_check", -999999)
    if tick - last_check < CURIOSITY_CHECK_INTERVAL:
        return
    c["_curiosity_last_check"] = tick

    curiosity = c.get("curiosity", 50)
    if curiosity < CURIOSITY_MIN_TO_REACT:
        return

    target = _find_notable_target(c, world)
    if not target:
        return

    if random.random() > (curiosity / 100.0) * CURIOSITY_MAX_ROLL_CHANCE:
        return

    _start_investigation(c, world, target)


def _find_notable_target(c, world):
    """Nearby incidents first (systems/emergency.py, same Manhattan-4
    proximity emergency.py/_build_incident_context already use), then
    notable audible events (ambient sounds, then loud/yelling speech)."""
    cx, cy = c.get("x", 0), c.get("y", 0)
    seen = c.get("_curiosity_seen_incidents", [])

    for inc in world.get("incidents", []):
        if inc.get("extinguished"):
            continue
        if inc.get("id") in seen:
            continue
        if c["id"] in inc.get("participants", []):
            continue  # already directly involved, not "investigating" as a bystander
        loc = inc.get("location", {})
        if "x" not in loc or "y" not in loc:
            continue
        if abs(cx - loc["x"]) + abs(cy - loc["y"]) < 4:
            return {"kind": "incident", "x": loc["x"], "y": loc["y"],
                    "id": inc["id"], "label": inc.get("type", "commotion")}

    audible = c.get("perception", {}).get("audible_events", [])
    for event in audible:
        if event.get("type") == "ambient" and event.get("volume") in _NOTABLE_VOLUMES \
                and "x" in event and "y" in event:
            return {"kind": "ambient", "x": event["x"], "y": event["y"],
                    "label": event.get("sound", "noise")}

    for event in audible:
        if event.get("type") == "speech" and event.get("volume") in _NOTABLE_VOLUMES \
                and event.get("source_id"):
            return {"kind": "speech", "source_id": event["source_id"], "label": "yelling"}

    return None


def _approach_point(c, tx, ty, max_distance):
    """A point `max_distance` tiles short of (tx,ty) along the straight
    line from the character -- "close enough to see, not officially
    participating." Returns the character's own position (no movement
    needed) if already within range."""
    cx, cy = c.get("x", 0), c.get("y", 0)
    dist = abs(tx - cx) + abs(ty - cy)
    if dist <= max_distance:
        return cx, cy
    frac = max(0.0, (dist - max_distance) / dist)
    return int(round(cx + (tx - cx) * frac)), int(round(cy + (ty - cy) * frac))


def _start_investigation(c, world, target):
    from systems.reactions import push_reaction
    from systems.excuses import generate_approach_pretext
    from brain.cognition_scheduler import wake_character
    from systems.navigation import plan_character_route

    tick = world.get("tick", 0)
    push_reaction(c, "look_around" if target["kind"] == "speech" else "surprise", tick)

    if c.get("activity_queue"):
        from systems.activity_queue import suspend_activity_queue
        suspend_activity_queue(c, world, reason="curiosity")
    # suspend_activity_queue only clears c["activity"] as a side effect of
    # draining a non-empty activity_queue -- a single-slot activity (e.g.
    # "wait", with no queue behind it) needs clearing directly, or
    # _movement_blocked() (action_router.py) would still refuse the walk
    # below.
    c["activity"] = None

    if target["kind"] == "speech":
        other = world.get("characters", {}).get(target["source_id"])
        if not other:
            return
        tx, ty = other["x"], other["y"]
    else:
        tx, ty = target["x"], target["y"]

    pretext_kind = "incident" if target["kind"] == "incident" else "ambient"
    pretext = generate_approach_pretext(c, world, pretext_kind, target.get("label"))

    # An indoor character investigating a pure ambient sound (no incident
    # record, nobody to walk up to) "looks out the window" rather than
    # literally walking outside toward the raw sound coordinates -- see
    # simulations/default/definitions.json's new window_a prop_template
    # (tag "window"). Falls back to approaching the raw source directly
    # if no window prop exists nearby (this content is sparse today).
    if target["kind"] == "ambient" and c.get("building_id"):
        from systems.props import find_nearest_prop, prop_distance
        window = find_nearest_prop(c, world, tag="window")
        if window and prop_distance(c, window) <= CURIOSITY_APPROACH_MAX_DISTANCE * 3:
            ax, ay = window["x"], window["y"]
        else:
            ax, ay = _approach_point(c, tx, ty, CURIOSITY_APPROACH_MAX_DISTANCE)
    else:
        ax, ay = _approach_point(c, tx, ty, CURIOSITY_APPROACH_MAX_DISTANCE)

    if (ax, ay) != (c.get("x", 0), c.get("y", 0)) and plan_character_route(world, c, ax, ay):
        c["animation_state"] = "walk"
        c["is_moving"] = True

    c["_investigating"] = {
        "kind": target["kind"], "target_x": tx, "target_y": ty,
        "started_tick": tick,
    }

    if target.get("id"):
        seen = c.setdefault("_curiosity_seen_incidents", [])
        seen.append(target["id"])
        c["_curiosity_seen_incidents"] = seen[-_SEEN_INCIDENTS_CAP:]

    wake_character(c, world, "noticed_commotion", {"summary": pretext})


def _resolve_investigation(c, world):
    """Once the walk-over finishes (or there was nothing to walk to),
    clear the marker -- the character's own next LLM turn (already
    primed by the noticed_commotion wake) takes it from there."""
    if not c.get("is_moving") and not c.get("route"):
        c["_investigating"] = None
