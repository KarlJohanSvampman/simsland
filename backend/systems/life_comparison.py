"""
systems/life_comparison.py

Characters compare themselves (and, via belongings/household net worth,
their household) against real contacts across several dimensions --
belongings, spouse-vs-my-ideal, children-vs-my-ideal, appearance, work,
intelligence, social life, expectations-fulfillment, and personality-
vs-admired-traits. Jealousy (rel["jealousy"]) only ever accumulates on
dimensions where the OTHER scores better -- never the observer's own
wins -- and decays otherwise, same shape as every other relationship-
stat tracker built this session (grievances, favor_frustration,
creeped_out).

Deliberately NOT a rewrite of attraction.py::check_envy_events() --
that stays scoped to romantic/status envy exactly as it already is;
this is a separate, broader "how does their life stack up" comparison.
"""

import random

from systems.attraction import compute_ideal_match

_EDU_RANK = {
    "none": 0, "none_completed": 0, "preschool": 0, "primary": 0,
    "middle_school": 0, "high_school": 1, "trade_school": 2, "certificate": 2,
    "associate": 3, "bachelor": 4, "master": 5, "doctorate": 6, "professional": 6,
}

JEALOUSY_GAIN_PER_DIMENSION = 3.0
JEALOUSY_DECAY_RATE         = 0.97   # per day, mirrors grievances.py's DECAY_RATE shape
JEALOUSY_GRIEVANCE_THRESHOLD = 60.0
COMPARISON_SAMPLE_SIZE      = 4      # bounded scan, mirrors check_envy_events' contact scope


def _kin_ids(c, kinship):
    return [oid for oid, rel in c.get("relationships", {}).items() if rel.get("kinship") == kinship]


def _spouse_of(c, world):
    chars = world.get("characters", {})
    for oid in _kin_ids(c, "spouse"):
        if oid in chars:
            return chars[oid]
    return None


def _children_of(c, world):
    chars = world.get("characters", {})
    return [chars[oid] for oid in _kin_ids(c, "child") if oid in chars]


def _avg_ideal_match(c, people, ideal_key):
    if not people:
        return None
    scores = [compute_ideal_match(c, p, ideal_key=ideal_key) for p in people]
    return sum((s["trait"] + s["physical"]) / 2.0 for s in scores) / len(scores)


def _expectations_ratio(c):
    exps = c.get("expectations", {})
    if not exps:
        return None
    streak = sum(e.get("streak", 0) for e in exps.values())
    missed = sum(e.get("missed_count", 0) for e in exps.values())
    return streak / (streak + missed + 1)


def _admired_traits_score(c, other):
    ideal = c.get("ideal_partner")
    if not ideal:
        return None
    desired = set(ideal.get("desired_traits", []))
    undesired = set(ideal.get("undesired_traits", []))
    total = len(desired) + len(undesired)
    if not total:
        return None
    other_traits = set(other.get("traits", []) + other.get("personality_traits", []))
    hits = len(other_traits & desired) - len(other_traits & undesired)
    return 0.5 + 0.5 * (hits / total)


def compare_lives(c, other, world):
    """Returns {dimension: {"self": x, "other": x, "favors_other": bool}}
    -- only dimensions where BOTH sides have real, comparable data are
    included (a dimension neither side can observe/measure isn't
    silently defaulted into a comparison)."""
    dims = {}

    c_wealth = c.get("wealth", 0) or 0
    o_wealth = other.get("wealth", 0) or 0
    dims["belongings"] = {"self": c_wealth, "other": o_wealth, "favors_other": o_wealth > c_wealth}

    c_spouse_match = _avg_ideal_match(c, [_spouse_of(c, world)] if _spouse_of(c, world) else [], "ideal_partner")
    o_spouse_match = _avg_ideal_match(c, [_spouse_of(other, world)] if _spouse_of(other, world) else [], "ideal_partner")
    if c_spouse_match is not None and o_spouse_match is not None:
        dims["spouse"] = {"self": c_spouse_match, "other": o_spouse_match, "favors_other": o_spouse_match > c_spouse_match}

    c_kids, o_kids = _children_of(c, world), _children_of(other, world)
    if c_kids and o_kids:
        c_child_match = _avg_ideal_match(c, c_kids, "ideal_child")
        o_child_match = _avg_ideal_match(c, o_kids, "ideal_child")
        dims["children"] = {"self": c_child_match, "other": o_child_match, "favors_other": o_child_match > c_child_match}

    c_attr, o_attr = c.get("attractiveness", 0.5), other.get("attractiveness", 0.5)
    dims["appearance"] = {"self": c_attr, "other": o_attr, "favors_other": o_attr > c_attr}

    if c.get("employed") and other.get("employed"):
        c_wage, o_wage = c.get("hourly_wage", 0) or 0, other.get("hourly_wage", 0) or 0
        dims["work"] = {"self": c_wage, "other": o_wage, "favors_other": o_wage > c_wage}

    c_edu = _EDU_RANK.get(c.get("education", "none"), 0)
    o_edu = _EDU_RANK.get(other.get("education", "none"), 0)
    dims["intelligence"] = {"self": c_edu, "other": o_edu, "favors_other": o_edu > c_edu}

    c_social, o_social = len(c.get("relationships", {})), len(other.get("relationships", {}))
    dims["social_life"] = {"self": c_social, "other": o_social, "favors_other": o_social > c_social}

    c_exp, o_exp = _expectations_ratio(c), _expectations_ratio(other)
    if c_exp is not None and o_exp is not None:
        dims["expectations_fulfillment"] = {"self": c_exp, "other": o_exp, "favors_other": o_exp > c_exp}

    o_admired = _admired_traits_score(c, other)
    if o_admired is not None:
        # No symmetric "self" score here -- this is c's own admired-
        # traits yardstick applied to `other`, not a two-sided measure.
        dims["personality_vs_admired"] = {"self": 0.5, "other": o_admired, "favors_other": o_admired > 0.5}

    return dims


def _apply_comparison(c, other, world):
    rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
    dims = compare_lives(c, other, world)
    favorable_hits = sum(1 for d in dims.values() if d["favors_other"])

    if favorable_hits:
        rel["jealousy"] = min(100.0, rel.get("jealousy", 0.0) + JEALOUSY_GAIN_PER_DIMENSION * favorable_hits)
    else:
        rel["jealousy"] = max(0.0, rel.get("jealousy", 0.0) * JEALOUSY_DECAY_RATE)

    if rel["jealousy"] >= JEALOUSY_GRIEVANCE_THRESHOLD:
        from systems.grievances import add_grievance
        add_grievance(c, other["id"], "life_envy", world,
                      details={"favorable_dimensions": [k for k, d in dims.items() if d["favors_other"]]})
        rel["jealousy"] = 0.0  # vented via the grievance/confrontation pipeline

    return dims


def tick_life_comparison(world):
    """Daily cadence (see sim_loop.py). Bounded per-character contact
    sample, same spirit as attraction.py::check_envy_events()'s own
    contact-scoped scan -- not a full world-wide comparison every day."""
    characters = world.get("characters", {})
    for c in characters.values():
        if c.get("is_offscreen") or c.get("age_group") in ("child", "teen"):
            continue
        contact_ids = list(c.get("relationships", {}).keys())
        if not contact_ids:
            continue
        sample = random.sample(contact_ids, min(COMPARISON_SAMPLE_SIZE, len(contact_ids)))
        for oid in sample:
            other = characters.get(oid)
            if not other or other.get("id") == c.get("id"):
                continue
            _apply_comparison(c, other, world)
