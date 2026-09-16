"""
systems/workplace_reputation.py

Two small, bounded, decaying adjusters over brain/relationships.py's
new rel["workplace_reputation"]/rel["workplace_dependency"] fields --
the only writers those two fields should ever have. Mirrors systems/
grievances.py::decay_grievances()'s slow multiplicative decay shape,
applied only to a character's real workplace_contact_ids (systems/
workplace_npc.py), not their whole relationships dict.
"""

REPUTATION_BOUND  = 100.0
DEPENDENCY_BOUND  = 100.0
DAILY_DECAY_RATE  = 0.98   # per real day, pulls both fields toward 0


def adjust_reputation(c, other_id, delta):
    from brain.relationships import ensure_relationship
    rel = ensure_relationship(c, other_id)
    rel["workplace_reputation"] = max(
        -REPUTATION_BOUND, min(REPUTATION_BOUND, rel.get("workplace_reputation", 0.0) + delta)
    )
    return rel["workplace_reputation"]


def adjust_dependency(c, other_id, delta):
    from brain.relationships import ensure_relationship
    rel = ensure_relationship(c, other_id)
    rel["workplace_dependency"] = max(
        0.0, min(DEPENDENCY_BOUND, rel.get("workplace_dependency", 0.0) + delta)
    )
    return rel["workplace_dependency"]


def decay_workplace_views(c):
    """Daily cadence -- call alongside decay_stories()/similar in
    sim_loop.py. Only decays real workplace-contact relationships, not
    the whole c["relationships"] dict."""
    rels = c.get("relationships", {})
    for other_id in c.get("workplace_contact_ids", []):
        rel = rels.get(other_id)
        if not rel:
            continue
        rel["workplace_reputation"] = round(rel.get("workplace_reputation", 0.0) * DAILY_DECAY_RATE, 2)
        rel["workplace_dependency"] = round(rel.get("workplace_dependency", 0.0) * DAILY_DECAY_RATE, 2)
