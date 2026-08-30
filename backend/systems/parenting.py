"""
systems/parenting.py

A household's real parenting guidelines are the INTERSECTION of both
spouses' individual ideal_child personas (systems/attraction.py::
generate_ideal_child) -- traits both parents actually share, not
either parent's individual wishlist, and life_goals taken at whichever
parent holds it LESS strongly (the genuine shared floor, not an
average that could overstate agreement).

household["parenting_guidelines"] = {
    "desired_traits", "undesired_traits", "life_goals", "derived_from",
}

systems/persona_expectations.py reads this as an additional clash
source for real children in the household, alongside its existing
opinion-alignment clash detection.
"""

from systems.attraction import LIFE_GOAL_CATEGORIES


def _find_spouses(household, world):
    chars = world.get("characters", {})
    member_ids = set(household.get("members", []))
    members = [chars.get(mid) for mid in member_ids if chars.get(mid)]

    spouses = []
    for m in members:
        for oid, rel in m.get("relationships", {}).items():
            if rel.get("kinship") == "spouse" and oid in member_ids and m not in spouses:
                spouses.append(m)
    return spouses


def derive_household_parenting_guidelines(household, world):
    """Computes (and caches on household["parenting_guidelines"]) the
    shared-ground parenting profile. Returns None if the household
    doesn't have two identifiable spouses (a single parent has no
    "shared ground" to derive -- their own ideal_child stands alone and
    is read directly wherever needed instead)."""
    spouses = _find_spouses(household, world)
    if len(spouses) < 2:
        return household.get("parenting_guidelines")

    defs = world.get("definitions", {})
    for sp in spouses[:2]:
        if not sp.get("ideal_child"):
            from systems.attraction import generate_ideal_child
            generate_ideal_child(sp, defs)

    ideal_a, ideal_b = spouses[0]["ideal_child"], spouses[1]["ideal_child"]

    common_desired = set(ideal_a.get("desired_traits", [])) & set(ideal_b.get("desired_traits", []))
    common_undesired = set(ideal_a.get("undesired_traits", [])) & set(ideal_b.get("undesired_traits", []))

    life_goals = {}
    for cat in LIFE_GOAL_CATEGORIES:
        a = ideal_a.get("life_goals", {}).get(cat, 0.5)
        b = ideal_b.get("life_goals", {}).get(cat, 0.5)
        life_goals[cat] = min(a, b)  # genuine shared ground, not either parent's ceiling

    guidelines = {
        "desired_traits":   sorted(common_desired),
        "undesired_traits": sorted(common_undesired),
        "life_goals":       life_goals,
        "derived_from":     [spouses[0]["id"], spouses[1]["id"]],
    }
    household["parenting_guidelines"] = guidelines
    return guidelines
