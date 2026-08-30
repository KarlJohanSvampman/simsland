"""
systems/intimate_item_discovery.py

Two ways a household member can stumble onto evidence of another's
private sex life, both landing on the same effect (apply_creeped_out):
  1. Physical items -- a stored (not currently held) fleshlight/
     vibrator/dildo/strapon found while someone has a plausible reason
     to be near the owner's things (tidying, looking for their own
     stuff). Periodic low-probability roll, tick_discovery_checks(world).
  2. Computer history -- action_router.py::_route_check_computer_history,
     calls apply_creeped_out() directly when a logged watch_porn entry
     is discovered.

Deliberately NOT built on retrieve_item/return_item/search_room --
those are confirmed broken (referenced but never defined) and
explicitly out of scope from earlier this session.
"""

import random

DISCOVERY_CHANCE_PER_CHECK = 0.02
CREEPED_OUT_DELTA = 8.0
_INTIMATE_TEMPLATES = {"fleshlight", "vibrator", "dildo_small", "dildo_medium", "dildo_large", "strapon"}


def apply_creeped_out(discoverer, owner_id, world):
    """discoverer's subjective view of owner takes a real hit -- mirrors
    systems/persona_expectations.py's per-relationship-dict placement.
    Not a grievance (nobody did anything WRONG to the discoverer), just
    a standing dent to how they see this person."""
    from brain.relationships import ensure_relationship
    rel = ensure_relationship(discoverer, owner_id)
    rel["creeped_out"] = min(100.0, rel.get("creeped_out", 0.0) + CREEPED_OUT_DELTA)
    rel["respect"] = max(-100, rel.get("respect", 0) - 3)
    rel["comfort"] = max(-100, rel.get("comfort", 0) - 3)


def _stored_intimate_items(c):
    """Items of interest NOT currently in use (location != "held")."""
    from systems.personal_items import get_inventory
    return [
        i for i in get_inventory(c)
        if i.get("template_id") in _INTIMATE_TEMPLATES and i.get("location") != "held"
    ]


def tick_discovery_checks(world):
    """Slow cadence (see sim_loop.py). For each household with 2+
    members, a small per-non-owner roll for "plausible reason to be
    near" the owner's stored things."""
    households = world.get("households", {})
    characters = world.get("characters", {})

    for household in households.values():
        members = [characters.get(mid) for mid in household.get("members", [])]
        members = [m for m in members if m]
        if len(members) < 2:
            continue

        for owner in members:
            items = _stored_intimate_items(owner)
            if not items:
                continue
            for other in members:
                if other["id"] == owner["id"]:
                    continue
                if random.random() < DISCOVERY_CHANCE_PER_CHECK:
                    apply_creeped_out(other, owner["id"], world)
