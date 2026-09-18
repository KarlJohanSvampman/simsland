"""
systems/caretaker_negotiation.py

Real caretaker-to-caretaker negotiation for a shared-custody/temporary-
caretaker schedule or responsibility change -- e.g. a child wants to
stay the night at a friend's house. Reuses systems/proposals.py's
existing propose/respond/counter engine verbatim (propose_social_ask())
rather than building a second negotiation system: a custody change is
just a "social_ask" proposal whose chore_id is tagged
CUSTODY_CHORE_ID, so it rides the SAME accept/decline/counter UX and
the SAME brain/context_builder.py::_build_proposal_context() narration
every other social_ask already gets ("<name> is asking you: <params.
text> -- you can accept, decline, or counter"), with ZERO changes
needed to either proposals.py or context_builder.py.

Two real hops, both real proposals -- not a single auto-resolved roll:

  1. child_requests_schedule_change() -- the child proposes the change
     directly to whichever caretaker they're currently with/asking.
     `description` should already read in the child's own voice (e.g.
     "stay the night at Mia's house") -- their wish is baked straight
     into the proposal's own text (the thing the recipient's LLM
     actually reads), not a separate hidden number nudging the outcome
     behind the scenes. Gated by MIN_WISH_AGE -- a child too young to
     meaningfully express or negotiate a wish doesn't get to initiate
     one (mirrors dependent_tracking.py's own age-gated agency logic,
     e.g. its _DIRECT_CALL_AGE threshold for calling a caretaker
     directly).

  2. tick_caretaker_negotiation() -- once that first proposal resolves,
     if it was accepted AND a second, real co-parent exists (a second
     real "parent"/"step_parent"/"adoptive_parent"/"guardian" in
     family.py's own kinship graph, distinct from dependent_tracking.
     py's current_caretaker, which just answers "who physically has
     them right now" -- this is the real "other custodial party" a
     shared-custody arrangement implies), the accepting caretaker
     automatically forwards a SECOND real proposal to them. Both real
     people have to actually agree for the change to stick; if there's
     no second co-parent, the first acceptance is final immediately.
"""

CUSTODY_CHORE_ID = "custody_schedule_change"
MIN_WISH_AGE = 6


def _find_co_parent(caretaker, child, world):
    """A second real parent/guardian (family.py kinship) who isn't the
    caretaker who just accepted -- the real "other custodial party" in
    a shared-custody scenario. Distinct from dependent_tracking.py's
    current_caretaker, which only answers "who physically has them
    right now," not "who else has a real say.\""""
    fam_id = child.get("family_id")
    family = world.get("families", {}).get(fam_id) if fam_id else None
    if not family:
        return None
    chars = world.get("characters", {})
    for other_id in family.get("members", []):
        if other_id in (child["id"], caretaker["id"]):
            continue
        other = chars.get(other_id)
        if not other or other.get("alive") is False:
            continue
        relation = family.get("relations", {}).get(f"{other_id}:{child['id']}")
        if relation in ("parent", "step_parent", "adoptive_parent", "guardian"):
            return other
    return None


def child_requests_schedule_change(child, caretaker, world, description):
    """The child proposes a schedule/responsibility change directly to
    whichever caretaker they're currently with. Returns the real
    proposal dict, or None if the child isn't old enough to meaningfully
    initiate one (MIN_WISH_AGE)."""
    if (child.get("age") or 0) < MIN_WISH_AGE:
        return None

    from systems.proposals import propose_social_ask
    result = propose_social_ask(
        child, caretaker, world, CUSTODY_CHORE_ID,
        params={"text": description, "child_id": child["id"], "hop": 1},
    )
    return result.get("proposal")


def _forward_to_co_caretaker(accepting_caretaker, child, world, description):
    co_parent = _find_co_parent(accepting_caretaker, child, world)
    if not co_parent:
        return None

    from systems.proposals import propose_social_ask
    forward_text = (
        f"{child.get('name', 'the child')} asked to {description}, and I'm fine with "
        f"it as long as you are too."
    )
    result = propose_social_ask(
        accepting_caretaker, co_parent, world, CUSTODY_CHORE_ID,
        params={"text": forward_text, "child_id": child["id"], "hop": 2},
    )
    return result.get("proposal")


def tick_caretaker_negotiation(world):
    """Moderate-cadence sweep (see sim_loop.py's wiring) -- detects a
    hop-1 custody proposal that just resolved to "accept" and forwards
    a real hop-2 proposal to a genuine co-parent, if one exists.
    Idempotent via a "forwarded" flag so a proposal is only ever acted
    on once."""
    chars = world.get("characters", {})
    for p in list(world.get("proposals", {}).values()):
        if p.get("chore_id") != CUSTODY_CHORE_ID or p.get("kind") != "social_ask":
            continue
        if p.get("status") != "resolved" or p.get("forwarded"):
            continue

        p["forwarded"] = True
        if (p.get("params") or {}).get("hop") != 1:
            continue  # hop-2 proposals never forward again

        recipient_id = p["recipients"][0]
        accepted = p["responses"].get(recipient_id) == "accept"
        if not accepted:
            continue

        caretaker = chars.get(recipient_id)
        child = chars.get((p.get("params") or {}).get("child_id"))
        if not caretaker or not child:
            continue

        description = (p.get("params") or {}).get("text", "make a schedule change")
        _forward_to_co_caretaker(caretaker, child, world, description)
