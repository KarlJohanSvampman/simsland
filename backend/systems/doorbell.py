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
    return (occupant.get("activity") or {}).get("type") in ("sleep", "nap", "take_nap")


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


RELAY_STALE_TICKS = 30 * 60       # nobody waits at a door half an hour: after that the message is moot


def settle_relay_intentions(c, world):
    """A "tell X someone's at the door" intention is over once it can't matter any more: the visitor has come in or
    gone, the person asked for has seen them, or it's been RELAY_STALE_TICKS. Live (2026-11-23): these never ended --
    Rachel carried "Pamela Martinez is at the door asking for Daniel Martinez -- let them know" for 1,337 minutes, the
    prompt telling her "This cannot wait any longer", so she kept trying to wake her napping father to tell him."""
    intents = c.get("active_intentions") or []
    if not any(str(i.get("type", "")).startswith("relay_door_visitor_") for i in intents):
        return
    chars = world.get("characters") or {}
    t = world.get("tick", 0)
    keep = []
    for i in intents:
        if not str(i.get("type", "")).startswith("relay_door_visitor_"):
            keep.append(i)
            continue
        visitor, target = chars.get(i.get("visitor_id")), chars.get(i.get("target_id"))
        why = None
        if not visitor or not target or visitor.get("off_grid"):
            why = "the visitor isn't at the door any more"
        elif t - int(i.get("created_at") or t) > RELAY_STALE_TICKS:
            why = "too long ago -- whoever was at the door has gone"
        elif visitor.get("building_id") and visitor.get("building_id") == target.get("building_id"):
            why = "they've met"
        elif visitor.get("household_id") and visitor.get("household_id") == target.get("household_id"):
            why = "they live here"
        if why:
            from brain.intention_history import mark
            mark(c, world, i.get("type"), "dropped", why, target=i.get("target_id"))
        else:
            keep.append(i)
    c["active_intentions"] = keep


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
    from cpl.lifecycle import interrupt as _cpl_interrupt     # someone talking is interrupted (cpl/lifecycle.py)
    for occ in heard_by:
        _cpl_interrupt(world, occ["id"], by=visitor.get("id"), kind="doorbell")
        wake_character(occ, world, "door_signal", {
            "visitor_name": visitor.get("name", "someone"),
        })

    # someone who lives here doesn't need announcing -- they let themselves in (live: Rachel was told for 22 hours that
    # her own daughter Pamela was "at the door asking for Daniel")
    lives_here = visitor.get("household_id") and visitor.get("household_id") == (household or {}).get("id")
    if target_id and not target_heard and heard_by and not lives_here:
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
