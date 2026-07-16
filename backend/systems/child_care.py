"""
systems/child_care.py

Ongoing needs oversight + accountability for age_group=="child" characters
(age < 13) -- distinct from systems/baby.py's infant pipeline, which only
tracks characters with a development_stage set (i.e. born in-sim via
pregnancy.py) and stops around age 3-6. Most children in this game never go
through that pipeline at all (family.py generates them directly), so this
module targets age_group=="child" directly regardless of origin.

Two need modes, per the parent's actual involvement:
  parent_serves      -- child can't do this themselves (cooking); a parent
                         must notice and act (see feed_child action).
  self_with_reminder -- child CAN do this themselves (toilet/sleep are
                         already generically available interact/sleep
                         actions) but doesn't proactively initiate; a
                         parent must remind them first (see remind_child
                         action), after which the child's own already-
                         autonomous decision loop takes it from there.

Also seeds a baseline "announce_departure" authority contract between each
child and their resolved parent(s), reusing systems/social_contracts.py's
already-complete authority-contract engine (previously only created
reactively as a discipline consequence -- see conditioning.py) -- this is
the "tell your parent what you're up to" mechanic.
"""

CHILD_NEED_CONFIG = {
    "hunger":  {"mode": "parent_serves",      "threshold": 70},
    "bladder": {"mode": "self_with_reminder", "threshold": 70},
    "bowels":  {"mode": "self_with_reminder", "threshold": 70},
    "fatigue": {"mode": "self_with_reminder", "threshold": 75},
}


def _find_parents_for_child(c, world):
    """Resolve caregiver(s) for a child -- household authority (same
    pattern as offgrid.py::_get_household_authorities) with a family.py
    kinship fallback for family-tree-linked characters."""
    chars = world.get("characters", {})
    result = []

    hid = c.get("household_id")
    if hid:
        for oc in chars.values():
            if oc["id"] == c["id"] or oc.get("household_id") != hid:
                continue
            rel = oc.get("relationships", {}).get(c["id"], {})
            if rel.get("authority_over") or "parent" in rel.get("labels", []) \
                    or "guardian" in rel.get("labels", []):
                result.append(oc)

    if not result:
        fam_id = c.get("family_id")
        family = world.get("families", {}).get(fam_id) if fam_id else None
        if family:
            for other_id in family.get("members", []):
                if other_id == c["id"]:
                    continue
                if family.get("relations", {}).get(f"{other_id}:{c['id']}") == "parent":
                    other = chars.get(other_id)
                    if other:
                        result.append(other)

    return result


def _ensure_departure_contract(child, parents, world):
    from systems.social_contracts import get_contracts_for_character, create_authority_contract

    existing = get_contracts_for_character(child["id"], world)
    for contract in existing:
        if contract.get("contract_type") == "announce_departure":
            return

    parent = parents[0]
    create_authority_contract(
        parent["id"], child["id"], "announce_departure",
        {"authorized_recipients": [p["id"] for p in parents]},
        world,
    )


def tick_child_needs(world):
    """Called on a moderate cadence (see CADENCE["child_care"]). For every
    age_group=="child" character, checks body needs against
    CHILD_NEED_CONFIG and notifies a resolved parent when one is crossed,
    and lazily seeds the baseline accountability contract."""
    from brain.intentions import add_intention

    for c in world.get("characters", {}).values():
        if c.get("age_group") != "child" or not c.get("alive", True):
            continue

        parents = _find_parents_for_child(c, world)
        if not parents:
            continue

        _ensure_departure_contract(c, parents, world)

        body = c.get("body", {})
        for need, cfg in CHILD_NEED_CONFIG.items():
            value = body.get(need, 0)
            if value < cfg["threshold"]:
                continue

            if cfg["mode"] == "parent_serves":
                if c.get("_awaiting_caregiver", {}).get("need") == need:
                    continue
                c["_awaiting_caregiver"] = {"need": need, "tick": world.get("tick", 0)}
                for parent in parents:
                    add_intention(parent, {
                        "type":     f"feed_child_{c['id']}",
                        "category": "health",
                        "priority": 85,
                        "reason":   f"{c.get('name', 'your child')} is hungry and can't cook for themselves",
                        "child_id": c["id"],
                    })
            else:
                if c.get("_awaiting_reminder", {}).get("need") == need:
                    continue
                c["_awaiting_reminder"] = {"need": need, "tick": world.get("tick", 0)}
                for parent in parents:
                    add_intention(parent, {
                        "type":     f"remind_child_{c['id']}",
                        "category": "health",
                        "priority": 60,
                        "reason":   f"{c.get('name', 'your child')} needs a reminder about {need}",
                        "child_id": c["id"],
                        "need":     need,
                    })
