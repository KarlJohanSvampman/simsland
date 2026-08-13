"""
systems/contact_designation.py — hours-based contact designation tiers.

Tracks how many hours per week a character spends physically co-present
with each relationship (accumulated in sim_loop.py's existing
_update_nearby_relationships proximity sweep via accumulate_hours()), and
promotes/demotes each relationship's designation tier accordingly once a
week (Monday midnight, alongside every other weekly system in
sim_loop.py::tick()).

Deliberately separate from brain/relationships.py's rel["state"] (that's a
live stat-threshold computation feeding 10+ unrelated behavior systems) --
"designation" here is purely a function of logged hours, tier-tunable via
definitions.json's contact_designations without any code change.
"""


def accumulate_hours(rel, hours):
    rel["hours_this_week"] = rel.get("hours_this_week", 0.0) + hours
    # Separate running total, consumed (and reset) by
    # systems/peer_influence.py::resolve_cognitive_adoption() at whatever
    # cadence applies to the character being evaluated (monthly for
    # adults, weekly for children/teens) -- kept apart from
    # hours_this_week above since that one resets every week regardless,
    # for the designation ladder specifically.
    rel["hours_since_adoption_eval"] = rel.get("hours_since_adoption_eval", 0.0) + hours


def evaluate_weekly_designations(world, defs):
    """Promote/demote every relationship's designation tier based on
    hours_this_week, then reset the weekly counter. Called once, from the
    existing Monday-midnight weekly block in sim_loop.py::tick()."""
    tiers = defs.get("contact_designations", {})
    order = tiers.get("order", [])
    if not order:
        return

    for c in world.get("characters", {}).values():
        for rel in c.get("relationships", {}).values():
            _evaluate_one(rel, order, tiers)


def _evaluate_one(rel, order, tiers):
    current = rel.get("designation", "stranger")
    if current not in order:
        current = order[0]
    idx = order.index(current)
    hours = rel.get("hours_this_week", 0.0)

    tier_cfg = tiers.get(current, {})
    upgrade_needed = tier_cfg.get("upgrade_hours_week")
    if upgrade_needed is not None and hours >= upgrade_needed and idx < len(order) - 1:
        idx += 1
    else:
        upkeep_needed = tier_cfg.get("weekly_upkeep_hours", 0)
        if hours < upkeep_needed and idx > 0:
            idx -= 1

    rel["designation"] = order[idx]
    rel["hours_this_week"] = 0.0
