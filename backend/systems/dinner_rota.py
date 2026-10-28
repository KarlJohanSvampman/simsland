"""
systems/dinner_rota.py -- who cooks which evening, and who does the dishes (docs/food_system.md, section 8).

A household that is lopsided about dinner -- one adult cooking nearly every night -- ends up with that adult proposing a rota
("you cook Tuesday and Thursday, I'll take Monday, Wednesday and Friday"). It is an ordinary systems/proposals.py proposal of kind
"dinner_rota"; the others accept or decline in their own turn. If it is accepted it becomes `household["dinner_rota"]`:

    {"cooks": {"monday": member_id, ...}, "dishes": "cook" | "other", "since_tick": n}

The planner (systems/dinner.py) sends the person whose evening it is to the stove, and the end of dinner (cookware.end_of_dinner) sends
the dish washer to the sink: the cook, or -- when the household agreed that one cooks and the other washes up -- the other adult.
"""

import random

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")
MIN_DINNERS_LOGGED = 4          # no one proposes a rota before the household has had a few dinners
LOPSIDED = 3                    # ...of the last four made by the same person
LOG_KEEP = 14


def _adults(world, household):
    chars = world.get("characters", {})
    from systems.food_habits import can_cook
    return [chars[m] for m in household.get("members", []) if m in chars and can_cook(chars[m])]


def rota(household):
    return household.get("dinner_rota")


def cook_for(household, weekday):
    r = rota(household)
    return (r or {}).get("cooks", {}).get((weekday or "").lower())


def washer_for(world, household, maker_id):
    """Who deals with the dishes after dinner: the cook, unless the household agreed the other adult washes up."""
    r = rota(household)
    if r and r.get("dishes") == "other":
        others = [a["id"] for a in _adults(world, household) if a["id"] != maker_id]
        if others:
            return others[0]
    return household.get("dish_duty") or maker_id


def note_cook(household, maker_id):
    log = household.setdefault("cook_log", [])
    log.append(maker_id)
    del log[:-LOG_KEEP]


def lopsided_cook(household):
    """The member who made at least three of the last four dinners, or None."""
    log = household.get("cook_log", [])
    if len(log) < MIN_DINNERS_LOGGED:
        return None
    recent = log[-4:]
    for who in set(recent):
        if recent.count(who) >= LOPSIDED:
            return who
    return None


def assignments(adult_ids, rng=random):
    """Weekdays shared out round-robin, so each adult cooks their own days and nobody cooks every night; weekends stay open."""
    ids = list(adult_ids)
    rng.shuffle(ids)
    return {day: ids[i % len(ids)] for i, day in enumerate(WEEKDAYS)}


def describe(world, cooks, dishes):
    chars = world.get("characters", {})
    by = {}
    for day, who in cooks.items():
        by.setdefault(who, []).append(day.capitalize())
    parts = [f"{chars.get(w, {}).get('name', 'someone').split()[0]} cooks {', '.join(days)}" for w, days in by.items()]
    tail = "; whoever cooked does not wash up" if dishes == "other" else "; the cook washes up"
    return "A dinner rota: " + "; ".join(parts) + tail + "."


def propose(world, household, proposer, rng=random):
    """The proposer asks the other adults in the household to share dinner out. Returns the proposal, or None."""
    from systems.proposals import propose as open_proposal
    adults = _adults(world, household)
    recipients = [a for a in adults if a["id"] != proposer["id"]]
    if len(adults) < 2 or not recipients:
        return None
    cooks = assignments([a["id"] for a in adults], rng)
    dishes = rng.choice(["cook", "other"])
    params = {"cooks": cooks, "dishes": dishes, "text": describe(world, cooks, dishes)}
    return open_proposal(proposer, recipients, "dinner_rota", "dinner_rota", params, world)


def finalize(proposal, world):
    """An accepted rota. Only the people who accepted (and the proposer) are in it; if no one accepted there is no rota."""
    household = world.get("households", {}).get(proposal.get("household_id"))
    accepted = proposal.get("participants") or []
    if not household or len(accepted) < 2:
        return None
    cooks = assignments(accepted) if set(proposal["params"]["cooks"].values()) - set(accepted) else dict(proposal["params"]["cooks"])
    household["dinner_rota"] = {"cooks": cooks, "dishes": proposal["params"].get("dishes", "cook"), "since_tick": world.get("tick", 0)}
    return household["dinner_rota"]


def maybe_propose(world, household, rng=random):
    """Once a day or less: if one adult keeps making dinner and there is no rota, they raise it."""
    if rota(household) or household.get("_rota_asked_tick") and world.get("tick", 0) - household["_rota_asked_tick"] < 7 * 86400:
        return None
    who = lopsided_cook(household)
    proposer = world.get("characters", {}).get(who) if who else None
    if not proposer or len(_adults(world, household)) < 2:
        return None
    for p in world.get("proposals", {}).values():
        if p.get("kind") == "dinner_rota" and p.get("status") == "open" and p.get("household_id") == household.get("id"):
            return None
    household["_rota_asked_tick"] = world.get("tick", 0)
    return propose(world, household, proposer, rng)
