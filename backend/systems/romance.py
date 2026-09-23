"""
systems/romance.py

Real state transitions for becoming/ceasing to be "partner" in
rel["labels"] -- confirmed (Romance/Dating & Intimate Relationship spec
pass) to be the single most load-bearing and, before this file, single
most completely unpopulated field in the whole relationship system:
~15 existing modules (absence_suspicion.py, detective_work.py,
secret_keeping.py, bedroom_assignment.py, domestic_control.py,
excuses.py, incidental_speech.py, nudity_perception.py,
sexual_release.py, crushes.py, attraction.py, temporary_separation.py,
action_router.py, offgrid.py, events.py, plus context_builder.py's own
LLM narration) all gate real, already-built behavior on "partner" or
"spouse" being present there, but the only place in all of backend/
that ever wrote to it was api/social_sandbox.py, a test/debug
scenario-staging endpoint -- never reachable through live gameplay.
Generation-time married NPCs didn't even get it (family.py wrote a
separate rel["kinship"] field instead -- fixed alongside this file, see
family.py::sync_kinship_to_relationships's diff).

become_partners()/break_up() are the two transitions a LIVE (not
generation-time) relationship can go through. Deliberately NOT built
this pass: any live propose-marriage/engagement/divorce mechanic (the
spec's "long-term partnership" section) -- break_up() below only ever
touches the "partner" label, never "spouse"; there is no divorce here,
same "confirmed gap, honestly left for later" treatment as every other
spec this session. Polyamory isn't modelled either -- becoming partners
with someone requires neither party already carries "partner" with
anyone else.
"""

_LABEL = "partner"


def _already_has_other_partner(person, exclude_id):
    for other_id, rel in person.get("relationships", {}).items():
        if other_id != exclude_id and _LABEL in rel.get("labels", []):
            return True
    return False


def become_partners(a, b, world):
    """Both sides' real consent is already established by the caller --
    systems/proposals.py's kind="romantic" only reaches this once the
    recipient has actually accept()-ed. Idempotent (a repeat call between
    the same two people is a no-op success), and clears a prior "ex" tag
    between exactly this pair if they're reconciling."""
    from brain.relationships import ensure_relationship

    if a.get("age", 0) < 18 or b.get("age", 0) < 18:
        return {"ok": False, "reason": "underage"}

    rel_a = ensure_relationship(a, b["id"])
    rel_b = ensure_relationship(b, a["id"])

    if _LABEL in rel_a.get("labels", []):
        return {"ok": True, "already": True}

    if _already_has_other_partner(a, b["id"]) or _already_has_other_partner(b, a["id"]):
        return {"ok": False, "reason": "already_partnered_elsewhere"}

    for rel in (rel_a, rel_b):
        labels = rel.setdefault("labels", [])
        if _LABEL not in labels:
            labels.append(_LABEL)
        if "ex" in labels:
            labels.remove("ex")
        rel["romantic_interest"] = max(rel.get("romantic_interest", 0), 40)
        rel["trust"] = rel.get("trust", 0) + 5
        rel["comfort"] = rel.get("comfort", 0) + 5

    return {"ok": True, "already": False}


def break_up(initiator, ex, world, reason="grew_apart"):
    """Unilateral -- ending a relationship, unlike starting one, needs no
    consent from the other side. Refuses when the pair isn't currently
    "partner" (covers both "never were" and "spouse"-only, since divorce
    isn't modelled -- see module docstring). Wakes the other party for
    real; the initiator already knows via their own action's outcome."""
    from brain.relationships import ensure_relationship
    from brain.cognition_scheduler import wake_character

    rel_init = ensure_relationship(initiator, ex["id"])
    rel_ex = ensure_relationship(ex, initiator["id"])

    if _LABEL not in rel_init.get("labels", []):
        return {"ok": False, "reason": "not_partners"}

    hostility_bump = 15 if reason == "cheating" else 6
    resentment_bump = 20 if reason == "cheating" else 8

    for rel in (rel_init, rel_ex):
        labels = rel.setdefault("labels", [])
        if _LABEL in labels:
            labels.remove(_LABEL)
        if "ex" not in labels:
            labels.append("ex")

    rel_ex["resentment"] = rel_ex.get("resentment", 0) + resentment_bump
    rel_ex["hostility"] = rel_ex.get("hostility", 0) + hostility_bump
    rel_ex["comfort"] = max(0, rel_ex.get("comfort", 0) - 15)

    wake_character(ex, world, "partner_broke_up_with_me", {
        "initiator_id": initiator["id"],
        "initiator_name": initiator.get("name", "your partner"),
        "reason": reason,
    })

    return {"ok": True}
