"""
systems/persona_expectations.py

General "who do you expect this specific person to be" mechanic --
distinct from systems/religious_repression.py (a bespoke, pre-existing
system specifically for the religious-strictness/sexual-identity axis,
now wired into grievances too -- see its _trigger_family_conflict) and
from systems/expectations.py's role-based recurring checkboxes (which
aren't about a specific other person at all).

Rather than hardcoding a checklist of "acceptable" life choices (which
would mean encoding one side of real social questions as "correct" game
logic), this reuses brain/opinions.py's already-built machinery: when two
closely related characters (parent/child/spouse, via kinship) have both
formed an opinion on the SAME topic and it diverges sharply, while one of
them holds it in a value category they personally care strongly about,
that's a real "you're not who I expected you to be" clash. It's
symmetric in either direction -- a strict parent clashing with a
rebellious kid works exactly the same way as a very permissive parent
clashing with a kid who turns devout -- rather than one side being
modeled as inherently right.

rel["personal_expectations"][topic] = {
    "category", "importance", "first_detected_tick",
    "clash_count", "frustration",
}
"""

CLASH_ALIGNMENT_THRESHOLD  = 0.35   # opinion_alignment() below this counts as a real clash
CLASH_IMPORTANCE_THRESHOLD = 0.6    # holder must care enough about the category for it to matter
CLASH_FRUSTRATION_DELTA    = 0.25
CLASH_GRIEVANCE_THRESHOLD  = 0.7

RELEVANT_KINSHIP = {"parent", "child", "spouse"}


def evaluate_persona_clashes(c, other, world):
    """Check c's opinions against other's for value-alignment clashes,
    weighted by c's own values[category] importance. Returns the list of
    topics newly flagged this call (mainly for tests/observability)."""
    from brain.opinions import get_current_opinion, opinion_alignment

    shared_topics = set(c.get("opinions", {})) & set(other.get("opinions", {}))
    if not shared_topics:
        return []

    values = c.get("values", {})
    rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
    tracked = rel.setdefault("personal_expectations", {})

    flagged = []
    for topic in shared_topics:
        c_op = get_current_opinion(c, topic)
        categories = c_op.get("relevant_values") or []
        importance = max(
            (values.get(cat, {}).get("importance", 0.0) for cat in categories),
            default=0.0,
        )
        if importance < CLASH_IMPORTANCE_THRESHOLD:
            continue

        if opinion_alignment(c, other, topic) >= CLASH_ALIGNMENT_THRESHOLD:
            continue  # aligned enough, not a clash

        entry = tracked.setdefault(topic, {
            "category":            categories[0] if categories else None,
            "importance":          importance,
            "first_detected_tick": world.get("tick", 0),
            "clash_count":         0,
            "frustration":         0.0,
        })
        entry["clash_count"] += 1
        entry["frustration"] = min(1.0, entry["frustration"] + CLASH_FRUSTRATION_DELTA * importance)
        flagged.append(topic)

        if entry["frustration"] >= CLASH_GRIEVANCE_THRESHOLD:
            from systems.grievances import add_grievance
            add_grievance(c, other["id"], "value_clash", world,
                          severity=7.0 * importance,
                          details={"topic": topic, "category": entry["category"]})
            entry["frustration"] = 0.0  # vented via the grievance/confrontation pipeline

    return flagged


def evaluate_parenting_guideline_clash(parent, child, world):
    """Real child's traits vs the household's derived parenting
    guidelines (systems/parenting.py -- the intersection of both
    spouses' ideal_child personas). A second, more concrete clash
    source alongside evaluate_persona_clashes()'s opinion-based one,
    same tracked/frustration/grievance shape."""
    household = world.get("households", {}).get(parent.get("household_id"))
    if not household:
        return False

    guidelines = household.get("parenting_guidelines")
    if guidelines is None:
        from systems.parenting import derive_household_parenting_guidelines
        guidelines = derive_household_parenting_guidelines(household, world)
    if not guidelines:
        return False

    desired = set(guidelines.get("desired_traits", []))
    undesired = set(guidelines.get("undesired_traits", []))
    total = len(desired) + len(undesired)
    if not total:
        return False

    child_traits = set(child.get("traits", []) + child.get("personality_traits", []))
    hits = len(child_traits & desired) - len(child_traits & undesired)
    match = 0.5 + 0.5 * (hits / total)
    if match >= CLASH_ALIGNMENT_THRESHOLD + 0.15:
        return False  # decent-enough match, not a clash

    rel = parent.setdefault("relationships", {}).setdefault(child["id"], {})
    tracked = rel.setdefault("personal_expectations", {})
    entry = tracked.setdefault("parenting_guidelines", {
        "category":            "family",
        "importance":          0.8,
        "first_detected_tick": world.get("tick", 0),
        "clash_count":         0,
        "frustration":         0.0,
    })
    entry["clash_count"] += 1
    entry["frustration"] = min(1.0, entry["frustration"] + CLASH_FRUSTRATION_DELTA)

    if entry["frustration"] >= CLASH_GRIEVANCE_THRESHOLD:
        from systems.grievances import add_grievance
        add_grievance(parent, child["id"], "value_clash", world,
                      severity=7.0, details={"topic": "parenting_guidelines"})
        entry["frustration"] = 0.0

    return True


def tick_persona_expectations(world):
    """Slow-cadence sweep (see core/tick_schedule.py's
    CADENCE["persona_expectations"], sim_loop.py). Only checks close-kin
    pairs (parent/child/spouse) -- this isn't meant to fire for every
    acquaintance who disagrees about politics, just the relationships
    where "who you turned out to be" carries real stakes."""
    characters = world.get("characters", {})
    for c in characters.values():
        if c.get("is_offscreen"):
            continue
        for other_id, rel in list(c.get("relationships", {}).items()):
            if rel.get("kinship") not in RELEVANT_KINSHIP:
                continue
            other = characters.get(other_id)
            if not other:
                continue
            evaluate_persona_clashes(c, other, world)
            if rel.get("kinship") == "parent":
                evaluate_parenting_guideline_clash(c, other, world)
