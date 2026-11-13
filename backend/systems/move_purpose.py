"""
systems/move_purpose.py

Walking to a thing is for doing something with it.

Live (2026-11-03): Steven Moreau, hungry, chose "move | To the kitchen counter to grab something to eat" again and
again, standing right by the counter, and nothing ever happened: a move to a prop routed onto the prop's own tile
(its solid footprint -- no route, so no walk and no word about it), and even a walk that got there ended there --
arriving did nothing, and he was never told he'd arrived, so the next turn chose the same move.

Now a move to a prop:
  - walks to where the thing is used from (its anchor), not into it;
  - if they are already there, or once they arrive, does what they came for, when that's clear: the purpose they
    gave names one of the thing's uses ("to wash my hands" at a sink -> wash_hands), or one of its uses satisfies
    what they most have to see to (hungry at the kitchen counter -> prepare_food; brain/intention_needs.py);
  - otherwise tells them they're there and what it's for, so the next choice can be to use it;
  - if they can't get there, tells them that.
"""

import re

from systems.props import get_prop_by_id

ARRIVED_TILES = 1.5            # this close to the walk target (or the thing) counts as being there
PURPOSE_TTL_TICKS = 900        # a walk that has gone on longer than this is no longer "on the way"

_GENERIC_WORDS = {"use", "do", "get", "the", "a", "with", "to", "on", "up", "down", "open", "toggle", "check"}


def _offered(world, prop):
    from systems.templates import resolve_prop
    full = resolve_prop(world, prop)
    out = []
    for anchor in full.get("anchors") or []:
        i = anchor.get("interaction")
        if i and i not in out:
            out.append(i)
    return out, full


def _walk_point(world, prop, interaction=None):
    from systems.action_router import _walk_target_for
    _, full = _offered(world, prop)
    if interaction:
        return _walk_target_for(full, interaction)
    return _walk_target_for(full, None)


def _near(c, point, prop):
    d_point = abs(c.get("x", 0) - point[0]) + abs(c.get("y", 0) - point[1])
    d_prop = abs(c.get("x", 0) - prop.get("x", 0)) + abs(c.get("y", 0) - prop.get("y", 0))
    return min(d_point, d_prop) <= ARRIVED_TILES


def _words(text):
    return re.findall(r"[a-z]+", str(text or "").lower())


def _named_use(offered, purpose):
    """An interaction the stated purpose names: every meaningful word of it appears ("wash my hands" -> wash_hands)."""
    said = _words(purpose)
    best = None
    for i in offered:
        need = [w for w in i.split("_") if w not in _GENERIC_WORDS]
        if need and all(any(s.startswith(w[:5]) for s in said) for w in need):
            if best is None or len(need) > len([w for w in best.split("_") if w not in _GENERIC_WORDS]):
                best = i
    return best


def _needed_use(c, offered):
    """An interaction that satisfies what they most have to see to (brain/intention_needs.py), best first."""
    from systems.todo import todo_list
    from brain.intention_needs import satisfied_by
    for intention in todo_list(c)["pressing"][:3]:
        for i in satisfied_by(intention.get("type")):
            if i in offered:
                return i
    return None


def choose_use(c, world, prop, purpose):
    offered, _ = _offered(world, prop)
    if not offered:
        return None
    return _named_use(offered, purpose) or _needed_use(c, offered)


def _label(prop):
    return re.sub(r"_[a-z]$", "", str(prop.get("template") or "thing")).replace("_", " ")


def _tell(c, world, text):
    from brain.cognition_scheduler import wake_character
    c.setdefault("cognition", {}).setdefault("staged_knowledge", []).append(text)
    wake_character(c, world, "activity_finished")


def _use(c, world, prop, interaction):
    from systems.action_router import _route_interact
    _route_interact(c, world, {"type": "interact", "target": prop["id"], "interaction": interaction},
                    world.get("definitions", {}))
    return bool(c.get("activity"))


def _there(c, world, prop, purpose):
    """They're at the thing: do what they came for, or say what it's for."""
    interaction = choose_use(c, world, prop, purpose)
    if interaction and _use(c, world, prop, interaction):
        return
    offered, _ = _offered(world, prop)
    uses = ", ".join(i.replace("_", " ") for i in offered) or "nothing in particular"
    _tell(c, world, f"You're at the {_label(prop)}. It's for: {uses}. If that's what you came for, use it "
                    f"(ACTION: interact | the {_label(prop)} | which one).")


def move_to_prop(c, world, prop, action, mode="walk"):
    """_route_move for a prop target."""
    from systems.navigation import plan_character_route
    purpose = " ".join(str(action.get(k) or "") for k in ("target_description", "detail", "reason"))
    interaction = choose_use(c, world, prop, purpose)
    point = _walk_point(world, prop, interaction)
    c.pop("_move_purpose", None)
    if _near(c, point, prop):
        c["move_target"] = None
        c["is_moving"] = False
        _there(c, world, prop, purpose)
        return
    c["move_target"] = {"x": point[0], "y": point[1], "target_id": prop["id"], "target_type": "prop"}
    if plan_character_route(world, c, point[0], point[1]):
        c["animation_state"] = mode
        from systems.movement import start_moving
        start_moving(c, world)
        c["_move_purpose"] = {"prop_id": prop["id"], "purpose": purpose, "point": list(point),
                              "tick": world.get("tick", 0)}
        return
    c["move_target"] = None
    _tell(c, world, f"You can't find a way to the {_label(prop)} from here.")


def check_arrival(c, world):
    """Each tick (brain/agent_loop.py): a walk to a thing that has ended -- arrived, or not."""
    mp = c.get("_move_purpose")
    if not mp or c.get("is_moving") or c.get("route"):
        if mp and world.get("tick", 0) - mp.get("tick", 0) > PURPOSE_TTL_TICKS:
            c.pop("_move_purpose", None)
        return
    c.pop("_move_purpose", None)
    if c.get("activity"):
        return                                       # they've already started something else
    prop = get_prop_by_id(world, mp.get("prop_id"))
    if not prop:
        return
    if _near(c, mp.get("point") or (prop.get("x", 0), prop.get("y", 0)), prop):
        c["move_target"] = None
        _there(c, world, prop, mp.get("purpose"))
    else:
        _tell(c, world, f"You didn't make it to the {_label(prop)} -- something was in the way.")
