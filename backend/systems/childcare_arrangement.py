"""
systems/childcare_arrangement.py

Before a parent leaves -- systems/offgrid.py::send_offgrid is the single
funnel every departure (work, errand, leisure, everything) goes through --
a real check: would this leave a young dependent home alone, and if so,
does the parent try to arrange care first rather than just leaving them?
Runs for every departure reason, work included, per the user's explicit
ask -- a recurring work shift gets the same real check as a one-off
errand, not an exemption.

Two real outcomes if care is sought and a candidate actually answers:
  - accepted -> the child becomes a real, on-grid guest at the
    caretaker's building -- systems/temporary_separation.py's exact
    c["building_id"] = host's home_id pattern (visible, walkable there,
    not an abstracted off-grid trip), reverted the moment the PARENT's
    own trip resolves (systems/offgrid.py::process_return is that
    system's single return funnel, same idea).
  - declined, or nobody answered -> the parent leaves them home alone
    anyway. This is a real attempt, not a guaranteed fix -- exactly the
    "could possibly miss it" behavior requested for the doorbell itself.

Candidate selection: a peer -- another household's adult with their OWN
dependent close in age to this child (a household already juggling a
similarly-aged kid is a plausible, comfortable person to ask), ranked by
existing relationship trust. Reaching them uses systems/doorbell.py's real
ring_doorbell roll (so it can genuinely be missed) before the ask is even
made, and the ask itself is a real proposal (systems/proposals.py::
propose_social_ask, the same engine systems/caretaker_negotiation.py
already reuses for a related custody-change flow) -- accept/decline is
the recipient's own real decision, not a hidden dice roll.
"""

import random

BABYSIT_CHORE_ID = "temporary_babysitting_request"
CARE_AGE_THRESHOLD = 9  # a dependent this age or younger isn't left alone without a real decision
PEER_AGE_WINDOW = 4     # how close the candidate's own dependent's age must be to count as a "peer"


def _dependents_needing_arrangement(c, world):
    chars = world.get("characters", {})
    result = []
    for cid in c.get("dependents", []):
        child = chars.get(cid)
        if not child or child.get("alive") is False:
            continue
        if child.get("off_grid") or child.get("_temp_caretaker"):
            continue
        if (child.get("age") or 99) > CARE_AGE_THRESHOLD:
            continue
        result.append(child)
    return result


def _another_adult_home(c, child, world):
    """Is there already someone else responsible at home right now, so no
    arrangement is even needed? Checks the CHILD's own household (not the
    departing parent's, though normally the same) for a present adult who
    isn't the parent about to leave."""
    chars = world.get("characters", {})
    household = world.get("households", {}).get(child.get("household_id"))
    if not household:
        return False
    for mid in household.get("members", []):
        if mid == c["id"]:
            continue
        other = chars.get(mid)
        if not other or other.get("alive") is False:
            continue
        if other.get("age_group") not in ("adult", "elderly"):
            continue
        if other.get("off_grid") or other.get("building_id") != child.get("building_id"):
            continue
        return True
    return False


def _seek_care_chance(world, age):
    """Time-of-day-weighted -- much more likely to seek care overnight
    than for a quick daytime departure, scaled up further the younger the
    dependent (mirrors dependent_tracking.py's own age-scaling idea: the
    younger, the more caution)."""
    hour = world.get("calendar", {}).get("hour", 12)
    if hour >= 22 or hour < 6:
        time_factor = 0.85
    elif 18 <= hour < 22:
        time_factor = 0.5
    else:
        time_factor = 0.15
    age_factor = max(0.0, min(1.0, (CARE_AGE_THRESHOLD - (age or 0)) / CARE_AGE_THRESHOLD))
    return min(0.95, time_factor + (1 - time_factor) * age_factor * 0.5)


def _find_peer_caretaker(c, child, world):
    """Another household's adult who has their own dependent close in age
    to this child, ranked by existing relationship trust (0 if no
    relationship exists yet -- a real but untested neighbor still counts,
    just ranks below a trusted one)."""
    chars = world.get("characters", {})
    best, best_score = None, None
    for other in chars.values():
        if other["id"] == c["id"] or other.get("household_id") == c.get("household_id"):
            continue
        if other.get("age_group") not in ("adult", "elderly") or other.get("alive") is False:
            continue
        if other.get("off_grid"):
            continue
        deps = other.get("dependents", [])
        if not any(abs((chars.get(d) or {}).get("age", 999) - (child.get("age") or 0)) <= PEER_AGE_WINDOW
                   for d in deps):
            continue
        rel = c.get("relationships", {}).get(other["id"], {})
        score = rel.get("trust", 0)
        if best is None or score > best_score:
            best, best_score = other, score
    return best


def _request_babysitting(parent, candidate, child, world):
    household = world.get("households", {}).get(candidate.get("household_id"))
    if not household:
        return False

    from systems.doorbell import resolve_door_signal
    _heard_by, target_heard = resolve_door_signal(
        parent, world, household, target_id=candidate["id"], method="ring_doorbell",
    )
    if not target_heard:
        return False

    from systems.proposals import propose_social_ask
    description = f"watch {child.get('name', 'my child')} for a while"
    result = propose_social_ask(
        parent, candidate, world, BABYSIT_CHORE_ID,
        params={"text": description, "child_id": child["id"], "parent_id": parent["id"]},
    )
    return bool(result.get("proposal"))


def maybe_arrange_childcare_before_departure(c, world, reason):
    """Called from systems/offgrid.py::send_offgrid, before the departure
    itself is committed. Purely a side-effecting attempt -- never blocks
    or delays the actual trip; a pending/declined/no-answer request just
    means the child stays home alone, same as before this system existed."""
    for child in _dependents_needing_arrangement(c, world):
        if _another_adult_home(c, child, world):
            continue
        if random.random() >= _seek_care_chance(world, child.get("age")):
            continue
        candidate = _find_peer_caretaker(c, child, world)
        if not candidate:
            continue
        _request_babysitting(c, candidate, child, world)


def tick_babysitting_requests(world):
    """Moderate-cadence sweep (see sim_loop.py's wiring) -- once a
    temporary_babysitting_request proposal resolves, actually move the
    child (accept) or just drop it (decline) -- reuses systems/
    temporary_separation.py's exact on-grid relocation pattern."""
    chars = world.get("characters", {})
    for p in list(world.get("proposals", {}).values()):
        if p.get("chore_id") != BABYSIT_CHORE_ID or p.get("kind") != "social_ask":
            continue
        if p.get("status") != "resolved" or p.get("_babysit_handled"):
            continue
        p["_babysit_handled"] = True

        params = p.get("params") or {}
        child = chars.get(params.get("child_id"))
        candidate_id = p["recipients"][0]
        candidate = chars.get(candidate_id)
        parent = chars.get(params.get("parent_id"))
        if not child or not candidate or not parent:
            continue
        if p["responses"].get(candidate_id) != "accept":
            continue

        household = world.get("households", {}).get(candidate.get("household_id"))
        if not household or not household.get("home_id"):
            continue

        child["_temp_caretaker"] = {
            "host_id": candidate["id"],
            "origin_building_id": child.get("building_id"),
            "started_tick": world.get("tick", 0),
            "parent_id": parent["id"],
        }
        child["building_id"] = household["home_id"]

        from brain.memory import store_memory
        store_memory(
            child, f"{parent.get('name', 'Your parent')} dropped you off at {candidate.get('name', 'the neighbor')}'s place for a while.",
            importance=0.3, tags=["childcare_dropoff"], kind="childcare_dropoff", tick=world.get("tick", 0),
        )
        from sim_loop import _mark_dirty
        _mark_dirty(world, char_ids={child["id"]})


def maybe_return_dependents(parent, world):
    """Called from systems/offgrid.py::process_return once the PARENT's
    own trip resolves -- brings home any dependent currently placed with
    a temporary caretaker on THIS parent's behalf. Syncing the return to
    the parent's own arrival (rather than an independent timer) matches
    how the drop-off happened -- the parent's the one who arranged it, so
    the parent's the one who collects them."""
    chars = world.get("characters", {})
    for cid in parent.get("dependents", []):
        child = chars.get(cid)
        if not child:
            continue
        temp = child.get("_temp_caretaker")
        if not temp or temp.get("parent_id") != parent["id"]:
            continue

        host = chars.get(temp.get("host_id"))
        child["building_id"] = temp.get("origin_building_id")
        child["_temp_caretaker"] = None

        from brain.memory import store_memory
        host_name = host.get("name", "the neighbor") if host else "the neighbor"
        store_memory(
            child, f"{parent.get('name', 'Your parent')} picked you up from {host_name}'s place.",
            importance=0.2, tags=["childcare_return"], kind="childcare_return", tick=world.get("tick", 0),
        )
        from sim_loop import _mark_dirty
        _mark_dirty(world, char_ids={child["id"]})


# ── Narrative context (brain/context_builder.py) ───────────────────────────

def get_temp_caretaker_context(c, world):
    """Surfaces c["_temp_caretaker"] for the CHILD's own prompt -- you're
    currently staying at a neighbor's place while your parent is out."""
    temp = c.get("_temp_caretaker")
    if not temp:
        return []
    host = world.get("characters", {}).get(temp.get("host_id"))
    host_name = host.get("name", "a neighbor") if host else "a neighbor"
    return [f"You're staying at {host_name}'s place for a bit while your parent is out."]
