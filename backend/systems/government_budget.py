"""
systems/government_budget.py

Closes the loop government_debt.py's own docstring left open: income tax
was collected from characters but the money "vanished" -- never credited
anywhere. world["government"]["treasury"] is now a real balance, credited
by assess_monthly_tax() as it collects, and spent here on a fixed cadence
across a small set of categories -- each category's spend applies a real,
small, positive nudge to the matching world["environment"] community stat
(socioeconomics.py), so "the government putting money into healthcare"
is a literal, visible effect on health_system_capacity, not flavor text.

Treasury is spent, not hoarded -- it zeroes back to 0 each cycle after
allocating, mirroring how a government's monthly/annual budget is spent
down rather than accumulated indefinitely.
"""

BUDGET_CATEGORY_SHARES = {
    "healthcare":     0.25,
    "education":      0.20,
    "infrastructure": 0.20,
    "policing":       0.20,
    "welfare":        0.15,
}

# A "full effectiveness" month spends roughly this much treasury on a
# category with a 100% share -- tunable. Scales each category's stat nudge
# by how much was actually available to spend that cycle, rather than
# applying a flat nudge regardless of how much tax was actually collected.
FULL_EFFECT_TREASURY = 50_000.0

# Each category's spend nudges one or two real environment stats. The sign
# is baked in already (crime/poverty/congestion get pushed DOWN, capacity/
# graduation/attendance get pushed UP) -- not inferred at apply time.
CATEGORY_STAT_EFFECTS = {
    "healthcare":     [("health_system_capacity", 8.0)],
    "education":      [("high_school_graduation", 0.3), ("college_attendance", 0.2)],
    "infrastructure": [("traffic_congestion_pct", -0.3)],
    "policing":       [("violent_crime_rate", -0.02), ("nonviolent_crime_rate", -0.03)],
    "welfare":        [("poverty_rate", -0.15), ("homeless_pct", -0.05)],
}

# Stats that can legitimately go to 0 but never negative (rates/percentages).
# health_system_capacity is a raw capacity number, not a rate -- left
# unclamped on the floor side (still can't go negative in practice, since
# spend is never negative, but no artificial ceiling either).
_FLOOR_AT_ZERO = {
    "high_school_graduation", "college_attendance", "traffic_congestion_pct",
    "violent_crime_rate", "nonviolent_crime_rate", "poverty_rate", "homeless_pct",
}


def ensure_government(world):
    return world.setdefault("government", {
        "treasury": 0.0,
        "spending_categories": {
            cat: {"share": share, "total_spent": 0.0}
            for cat, share in BUDGET_CATEGORY_SHARES.items()
        },
    })


def tick_government_budget(world):
    """Monthly cadence (see sim_loop.py, alongside government_debt.py's
    tax assessment). Allocates the treasury across fixed-share categories,
    applies each category's real stat nudge scaled by how much was
    actually spent, then zeroes the treasury back down."""
    gov = ensure_government(world)
    treasury = gov.get("treasury", 0.0)
    if treasury <= 0:
        return

    env = world.setdefault("environment", {})
    categories = gov.setdefault("spending_categories", {})

    for cat, default_share in BUDGET_CATEGORY_SHARES.items():
        cat_data = categories.setdefault(cat, {"share": default_share, "total_spent": 0.0})
        share = cat_data.get("share", default_share)
        spend = treasury * share
        if spend <= 0:
            continue
        cat_data["total_spent"] = round(cat_data.get("total_spent", 0.0) + spend, 2)

        effectiveness = min(1.0, spend / (FULL_EFFECT_TREASURY * share)) if share > 0 else 0.0
        for stat_key, magnitude in CATEGORY_STAT_EFFECTS.get(cat, []):
            current = env.get(stat_key)
            if current is None:
                continue
            new_val = current + magnitude * effectiveness
            if stat_key in _FLOOR_AT_ZERO:
                new_val = max(0.0, new_val)
            env[stat_key] = round(new_val, 4)

    gov["treasury"] = 0.0  # spent, not hoarded
