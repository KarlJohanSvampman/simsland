"""
systems/doorbell.py

Ringing a doorbell or knocking on someone's door to get their household's
attention -- distinct from action_registry.py's combat "knock" (a
blunt-weapon strike). Buildings have no access-control/locked-door concept
today (systems/movement.py lets anyone walk into any building), so this
isn't a gate on entry -- its whole job is deciding who inside actually
notices, and whether the specific person the visitor came for is one of
them or someone else has to pass the word along.

A doorbell rides brain/perception.py's own SLEEP_HEARING_MIN_VOLUME idea:
loud enough that a sleeper has a real (if reduced) chance of it reaching
them at all, same as that module's "high"-tier sounds. A bare knock sits
below that -- normally would never wake a sleeper via the generic ambient-
sound gate, so instead of a hard impossibility it gets its own small
chance (a light sleeper can still stir). Both are further muffled -- a
reduced chance, not a cutoff, since being in the shower or with music on
is a distraction, not deafness -- when the specific occupant who might
otherwise answer is in the middle of one of those.
"""

import random

_HEAR_CHANCE = {
    "ring_doorbell": 0.9,
    "knock_on_door": 0.6,
}

# A sleeper's real chance of the signal reaching them at all.
_ASLEEP_MULTIPLIER = {
    "ring_doorbell": 0.55,
    "knock_on_door": 0.1,
}

_DISTRACTED_MULTIPLIER = 0.3  # shower running / music on
_DISTRACTING_ACTIVITIES = {"take_shower", "listen_to_music"}


def _is_asleep(occupant):
    return (occupant.get("activity") or {}).get("type") == "sleep"


def _is_distracted(occupant):
    return (occupant.get("activity") or {}).get("type") in _DISTRACTING_ACTIVITIES


def _home_occupants(world, household):
    """Household members actually present in the household's own building
    right now -- ignores anyone off-grid or elsewhere. Guests aren't a
    real concept yet (nothing to check), so this is just the residents."""
    if not household:
        return []
    chars = world.get("characters", {})
    building_id = household.get("home_id")
    result = []
    for cid in household.get("members", []):
        occ = chars.get(cid)
        if not occ or occ.get("alive") is False or occ.get("off_grid"):
            continue
        if building_id and occ.get("building_id") != building_id:
            continue
        result.append(occ)
    return result


def ring_at_door(world, household, target_id=None, method="ring_doorbell"):
    """Rolls, per occupant actually home, whether they notice. Returns
    (heard_by, target_heard) -- heard_by is every occupant who noticed,
    target_heard is whether the specific person being asked for was one
    of them (any answer counts if no target_id was given)."""
    base = _HEAR_CHANCE.get(method, 0.7)
    asleep_mult = _ASLEEP_MULTIPLIER.get(method, 0.3)

    heard_by = []
    for occ in _home_occupants(world, household):
        chance = base
        if _is_asleep(occ):
            chance *= asleep_mult
        if _is_distracted(occ):
            chance *= _DISTRACTED_MULTIPLIER
        if random.random() < chance:
            heard_by.append(occ)

    target_heard = any(o["id"] == target_id for o in heard_by) if target_id else bool(heard_by)
    return heard_by, target_heard


def resolve_door_signal(visitor, world, household, target_id=None, method="ring_doorbell"):
    """Full effect of ringing/knocking: wakes/notifies whoever noticed
    (brain/cognition_scheduler.py::wake_character), and if the specific
    person being asked for wasn't among them but someone else in the
    house was, that someone gets a real intention to go pass the word
    along -- otherwise the visitor's whole reason for coming by silently
    stalls forever on a household member who never even finds out."""
    from brain.cognition_scheduler import wake_character
    from brain.intentions import add_intention

    heard_by, target_heard = ring_at_door(world, household, target_id, method)
    for occ in heard_by:
        wake_character(occ, world, "door_signal", {
            "visitor_name": visitor.get("name", "someone"),
        })

    if target_id and not target_heard and heard_by:
        target = world.get("characters", {}).get(target_id)
        target_name = target.get("name", "them") if target else "them"
        for occ in heard_by:
            if occ["id"] == target_id:
                continue
            add_intention(occ, {
                "type":       f"relay_door_visitor_{visitor['id']}",
                "category":   "social",
                "priority":   55,
                "reason":     f"{visitor.get('name', 'Someone')} is at the door asking for {target_name} -- let them know.",
                "target_id":  target_id,
                "visitor_id": visitor["id"],
            })

    return heard_by, target_heard
