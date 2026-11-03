"""
systems/roam.py

When a step times out (systems/step_timeouts.py): step back, wander a little, then try again.

Being stuck -- walking somewhere and never getting there, an activity that never progresses -- used to end in the
character standing where they were and the same choice coming up again (live, 2026-11-03/04: three tries at the kitchen
sink on the way out of the bathroom, a counter "examined" and "moved to" over and over). Now a timeout:

  1. if what was being done came from an intention (c["current_intention"]), that intention is set back for a while
     (SETBACK_TICKS) and the next most urgent one is given a lift for the same time -- so the next choice is a
     different one (brain/intentions.py::final_priority reads c["_setbacks"] / c["_lifts"]);
  2. in any case, the character roams: a random other room of the building they're in, or, outdoors, a random walkable
     spot ROAM_MIN..ROAM_MAX tiles away -- the existing "roam" activity (systems/idle_quirks.py) with a short linger;
  3. once there, what they were doing is tried again (once -- MAX_RETRIES), from somewhere else: the walk is planned
     afresh. A second time out of the same thing in a row is given up on.
"""

import random

SETBACK_TICKS = 1800            # 30 sim-minutes
SETBACK_PENALTY = 1500          # final_priority points: below the next category for that long
LIFT_POINTS = 20                # the next most urgent: this much more pressing, within its own category
ROAM_LINGER_TICKS = (20, 60)
ROAM_MIN, ROAM_MAX = 5, 12      # tiles, outdoors
MAX_RETRIES = 1


def _target_label(world, retry):
    tid = retry.get("target_id")
    if not tid:
        return None
    if str(tid).startswith("room:"):
        return "the " + str(tid).split(":")[-1].rsplit("_", 1)[0].replace("_", " ")
    if str(tid).startswith("building:"):
        return "someone's house"
    other = (world.get("characters") or {}).get(tid)
    if other:
        return other.get("name")
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, tid)
    if prop:
        import re
        return "the " + re.sub(r"_[a-z]$", "", str(prop.get("template") or "thing")).replace("_", " ")
    return None


def wonder_aloud(c, world, retry, intention):
    """Stuck -- not getting anywhere: they lose the thread, say so out loud, and piece it back together -- what they
    were doing, why, and how long ago it started -- before wandering off to try again."""
    from systems.incidental_speech import fire_incidental
    from brain.memory import store_memory
    tick = world.get("tick", 0)
    walking = retry.get("phase") == "walking" or retry.get("type") == "move"
    fire_incidental(c, "announce", "Wait... where was I going?" if walking else "Hm... what was I doing?", world)
    what = str(retry.get("interaction") or retry.get("type") or "something").replace("_", " ")
    where = _target_label(world, retry)
    started = retry.get("started")
    minutes = max(0, (tick - started) // 60) if isinstance(started, (int, float)) else None
    ago = ("just now" if minutes == 0 else f"{minutes} minute{'s' if minutes != 1 else ''} ago") if minutes is not None \
        else "a little while ago"
    why = intention.get("reason") or str(intention.get("type") or "").replace("_", " ")
    if walking and retry.get("type") == "move":
        text = f"Right -- I was on my way to {where or 'somewhere'}"
    elif walking:
        text = f"Right -- I was on my way to {what}" + (f" at {where}" if where else "")
    else:
        text = f"Right -- I was trying to {what}" + (f" at {where}" if where else "")
    text += (f" (why: {why.replace('_', ' ')})" if why else "") + f". I started {ago} and didn't get anywhere. I'll take a quick " \
            f"walk and then try again."
    store_memory(c, text, importance=0.35, tags=["stuck", "recalled"], tick=tick, source="internal")
    c.setdefault("cognition", {}).setdefault("staged_knowledge", []).append(text)
    return text


def setback_active(c, intention_type, tick):
    until = (c.get("_setbacks") or {}).get(intention_type)
    return until is not None and tick < until


def lift_active(c, intention_type, tick):
    until = (c.get("_lifts") or {}).get(intention_type)
    return until is not None and tick < until


def set_back(c, world, intention_type):
    """The intention that led to the stuck activity goes down for a while; the next most urgent goes up."""
    from brain.intentions import final_priority
    if not intention_type:
        return None
    tick = world.get("tick", 0)
    c.setdefault("_setbacks", {})[intention_type] = tick + SETBACK_TICKS
    others = [i for i in c.get("active_intentions") or [] if i.get("type") != intention_type
              and (i.get("strength", 1) or 0) > 0]
    if not others:
        return None
    nxt = max(others, key=lambda i: final_priority(i, c))
    c.setdefault("_lifts", {})[nxt["type"]] = tick + SETBACK_TICKS
    for book in ("_setbacks", "_lifts"):                 # keep these small
        c[book] = {k: v for k, v in c[book].items() if v > tick}
    return nxt["type"]


def _random_room_point(c, world):
    from systems.navigation import find_building_at, plan_character_route
    from systems.templates import resolve_floorplan
    from systems.idle_quirks import _random_point_in_room
    building, _ = find_building_at(world, int(round(c.get("x", 0))), int(round(c.get("y", 0))))
    if not building:
        return None
    floorplan = resolve_floorplan(world, building) or {}
    here = str(c.get("room_id") or "").split(":", 1)[-1]
    rooms = [r for r in floorplan.get("rooms", []) if r.get("id") != here]
    random.shuffle(rooms)
    for room in rooms:
        point = _random_point_in_room(world, building, room)
        if point and plan_character_route(world, c, point[0], point[1]):
            return room.get("id")
    return None


def _random_outdoor_point(c, world):
    from systems.navigation import plan_character_route
    nav = world.get("outdoor_navigation") or {}
    cx, cy = int(round(c.get("x", 0))), int(round(c.get("y", 0)))
    spots = []
    for key in nav:
        try:
            x, y = (int(float(v)) for v in str(key).split(","))
        except ValueError:
            continue
        if ROAM_MIN <= abs(x - cx) + abs(y - cy) <= ROAM_MAX:
            spots.append((x, y))
    random.shuffle(spots)
    for x, y in spots[:12]:
        if plan_character_route(world, c, x, y):
            return f"{x},{y}"
    return None


def start_roam(c, world, retry=None):
    """Walk somewhere else nearby (another room here, or a few tiles off outdoors), then retry `retry` there.
    Returns True if they set off."""
    where = _random_room_point(c, world) or _random_outdoor_point(c, world)
    if not where:
        return False
    c["animation_state"] = "walk"
    c["is_moving"] = True
    lo, hi = ROAM_LINGER_TICKS
    c["activity"] = {"type": "roam", "phase": "walking", "phase_started_tick": world.get("tick", 0),
                     "duration": random.randint(lo, hi), "target_room": where, "state": {}}
    if retry:
        c["activity"]["retry"] = retry
    return True


def retry_key(retry):
    return f"{retry.get('type')}|{retry.get('target_id')}|{retry.get('interaction')}"


def after_roam(c, world, act):
    """The roam is over: try what they were doing before, once, from here."""
    retry = act.get("retry")
    if not retry:
        return False
    key = retry_key(retry)
    counts = c.setdefault("_retry_counts", {})
    if counts.get(key, 0) >= MAX_RETRIES:
        counts.pop(key, None)
        from brain.memory import store_memory
        store_memory(c, f"I couldn't manage to {str(retry.get('type')).replace('_', ' ')} even after trying again, "
                        f"so I let it go for now.", importance=0.3, tags=["stuck", "gave_up"],
                     tick=world.get("tick", 0), source="internal")
        return False
    counts[key] = counts.get(key, 0) + 1
    c["activity"] = None
    if retry.get("target_id") and retry.get("interaction"):
        from systems.action_router import _route_interact
        _route_interact(c, world, {"type": "interact", "target": retry["target_id"],
                                   "interaction": retry["interaction"]}, world.get("definitions", {}))
    elif retry.get("type") == "move" and retry.get("target_id"):
        from systems.action_router import _route_move
        _route_move(c, world, {"type": "move", "target": retry["target_id"]})
    else:
        from systems.activities import start_activity
        try:
            start_activity(c, world, retry.get("type"))
        except Exception:                            # noqa: BLE001 -- a retry must never break the tick
            return False
    if c.get("activity") or c.get("is_moving"):
        if retry.get("intention"):
            c["current_intention"] = {"type": retry["intention"]}
        return True
    return False


def note_success(c, retry_type):
    """Something got done: forget earlier retries of it."""
    counts = c.get("_retry_counts") or {}
    for key in [k for k in counts if k.startswith(f"{retry_type}|")]:
        counts.pop(key, None)
