"""
conversation_seating.py

Per the user's explicit ask: a conversation that runs past its own planned
length (see systems/conversation_interest.py::planned_length_ticks, rolled
when the conversation started) has a randomized chance of prompting someone
to actually sit down -- or, if nothing's free to sit on, lean against a
wall -- rather than the two of them standing in place indefinitely for
however long the conversation goes on.

Called on a cadence from sim_loop.py (world-level: sweeps every active
conversation, not one character at a time).
"""

import random

from core.event_bus import emit


def _already_settled(chars):
    """True if anyone in the conversation is already sitting or leaning --
    nothing to suggest, they're already comfortable."""
    return any(c.get("posture") in ("sitting_seat", "leaning_wall") for c in chars)


def _try_seat_or_lean(c, world):
    """Sit `c` in a nearby free seat if one exists, else have them lean
    against a nearby wall. Returns True if either worked."""
    from systems.action_router import _seat_near_point, _sit_in
    from systems.props import prop_distance

    seat = _seat_near_point(world, c.get("x", 0), c.get("y", 0))
    if seat and prop_distance(c, seat) <= 3:
        _sit_in(c, world, seat)
        return True

    from systems.walls import find_leanable_wall
    from systems.posture import set_posture
    wall = find_leanable_wall(c, world)
    if wall:
        set_posture(c, world, "leaning_wall")
        c["leaning_wall_id"] = wall["wall_id"]
        return True
    return False


def tick_conversation_seating(world):
    tick = world.get("tick", 0)
    chars = world.get("characters", {})

    for conv in world.get("conversations", {}).values():
        if not conv.get("active") or conv.get("seating_suggested"):
            continue
        if not conv.get("will_suggest_seating"):
            continue
        planned = conv.get("planned_length_ticks")
        if planned is None or tick - conv.get("started_at", tick) < planned:
            continue

        conv["seating_suggested"] = True  # only ever offered once per conversation

        participants = [chars[pid] for pid in conv.get("participants", []) if pid in chars]
        if len(participants) < 1 or _already_settled(participants):
            continue

        suggester = participants[0]
        if not _try_seat_or_lean(suggester, world):
            continue   # nowhere to sit or lean nearby -- stay standing

        # A second participant who's ALSO now free to sit (not off doing
        # something else entirely) gets the same offer, so the conversation
        # doesn't leave one of them standing over the other.
        for other in participants[1:]:
            if not (other.get("activity") or {}).get("type"):
                _try_seat_or_lean(other, world)

        from systems.incidental_speech import fire_incidental
        line = ("Want to sit down for a bit?" if suggester.get("posture") == "sitting_seat"
               else "Let's lean somewhere a second.")
        fire_incidental(suggester, "suggest", line, world)
        emit("conversation_seating_suggested", {
            "conversation_id": conv.get("id"),
            "character_id": suggester.get("id"),
        })
