"""
systems/household_bonds.py -- people who live together already know each other.

A family set up in the editor (or generated) gets its kinship labels stamped on the relationship entries
(systems/family.py::sync_kinship_to_relationships) but the numbers stay at zero: a mother and her child would start out as
strangers who happen to share a surname. This gives household members who are related the closeness the label implies, once,
the first time their pair is stamped:

  spouse            familiarity 90  trust 70  friendship 65  comfort 60
  parent -> child   familiarity 90  trust 60  friendship 60  comfort 60   (the parent's view of the child)
  child -> parent   familiarity 90  trust 65  friendship 60  comfort 65
  sibling           familiarity 90  trust 45  friendship 45  comfort 50
  any other kin     familiarity 60  trust 30  friendship 30  comfort 25    (grandparent, aunt, cousin, ...)

Only for pairs in the SAME household, only raised (never lowered), and marked `bonded` on the entry so a later re-stamp
doesn't restore what a fight has since worn down.
"""

from brain.relationships import ensure_relationship, update_relationship_state, _default_relationship

FLOORS = {
    "spouse":  {"familiarity": 90, "trust": 70, "friendship": 65, "comfort": 60},
    "parent":  {"familiarity": 90, "trust": 60, "friendship": 60, "comfort": 60},
    "child":   {"familiarity": 90, "trust": 65, "friendship": 60, "comfort": 65},
    "sibling": {"familiarity": 90, "trust": 45, "friendship": 45, "comfort": 50},
}
OTHER_KIN = {"familiarity": 60, "trust": 30, "friendship": 30, "comfort": 25}
INTERACTIONS = 50


def bond(world, a, b_id, kinship):
    """Raise a's feelings about b to what living together as `kinship` implies. True if anything was done."""
    if kinship == "ex_spouse":
        return False
    b = (world.get("characters") or {}).get(b_id)
    if not b or not a.get("household_id") or a.get("household_id") != b.get("household_id"):
        return False
    rel = ensure_relationship(a, b_id)
    for key, value in _default_relationship().items():       # an entry from an older save may be partly filled
        rel.setdefault(key, value)
    if rel.get("bonded"):
        return False
    for field, floor in FLOORS.get(kinship, OTHER_KIN).items():
        if (rel.get(field, 0) or 0) < floor:
            rel[field] = floor
    rel["interaction_count"] = max(rel.get("interaction_count", 0) or 0, INTERACTIONS)
    rel["bonded"] = True
    update_relationship_state(a, b_id)
    return True
