"""
systems/socioeconomics.py

Daily drift of community statistics.

Each stat in definitions["community_stats_config"] has:
  value        – starting value (written to world["environment"] on first init)
  min / max    – clamping bounds
  daily_drift  – fixed directional drift per tick (+/-), usually 0
  drift_range  – maximum random ±walk per tick
  unit         – display string (UI only)

The live values live in world["environment"] under the same keys.
"""

import random


# ---------------------------------------------------------------------------
# Keys that map 1-to-1 from community_stats_config into world["environment"]
# ---------------------------------------------------------------------------
_STAT_KEYS = [
    "population",
    "birth_rate",
    "death_rate",
    "unemployment_rate",
    "violent_crime_rate",
    "nonviolent_crime_rate",
    "incarceration_per_100k",
    "republican_pct",
    "democrat_pct",
    "independent_pct",
    "income_tax_rate",
    "food_stamp_pct",
    "homeless_pct",
    "health_system_capacity",
    "health_system_load",
    "traffic_congestion_pct",
    "traffic_accident_rate",
    "addiction_help_pct",
    "alcoholism_pct",
    "inflation_rate",
    "cost_of_living_index",
    "housing_vacancy_rate",
    "median_household_income",
    "poverty_rate",
    "high_school_graduation",
    "college_attendance",
    # Legacy keys also in environment (kept in sync)
    "crime_rate",
    "inflation",
    "tax_rate",
    "housing_pressure",
]


def init_community_stats(world: dict, defs: dict) -> None:
    """
    Called once at world creation / schema_defaults.
    Writes baseline values from community_stats_config into world["environment"].
    Does NOT overwrite if a value already exists.
    """
    cfg = defs.get("community_stats_config", {})
    env = world.setdefault("environment", {})

    for key, stat in cfg.items():
        env.setdefault(key, stat.get("value", 0))

    # Keep legacy keys in sync with their mapped new keys
    env.setdefault("crime_rate",        env.get("violent_crime_rate", 0.008) / 100)
    env.setdefault("inflation",         env.get("inflation_rate", 3.1) / 100)
    env.setdefault("tax_rate",          env.get("income_tax_rate", 8.5) / 100)
    env.setdefault("housing_pressure",  env.get("housing_vacancy_rate", 4.2) / 100)


def tick_socioeconomics(world: dict, defs: dict) -> None:
    """
    Called once per simulation day (every TICKS_PER_DAY ticks).
    Applies random drift within each stat's configured range.
    """
    cfg = defs.get("community_stats_config", {})
    env = world.setdefault("environment", {})

    for key, stat in cfg.items():
        current = env.get(key, stat.get("value", 0))
        drift_range = stat.get("drift_range", 0)
        daily_drift = stat.get("daily_drift", 0)
        lo = stat.get("min", 0)
        hi = stat.get("max", 1e9)

        if drift_range == 0 and daily_drift == 0:
            continue  # static stat

        delta = daily_drift + random.uniform(-drift_range, drift_range)
        new_val = max(lo, min(hi, current + delta))
        env[key] = round(new_val, 4)

    # ── Derived stats ────────────────────────────────────────────────────────
    # Health system stress (used by crisis.py)
    capacity = env.get("health_system_capacity", 320)
    load = env.get("health_system_load", 240)
    if capacity > 0:
        env["health_quality"] = round(max(0.1, min(2.0, capacity / max(load, 1))), 3)

    # Legacy sync — keep old keys consistent with new granular ones
    env["crime_rate"]       = round(env.get("violent_crime_rate", 0.8) / 100, 5)
    env["inflation"]        = round(env.get("inflation_rate", 3.1) / 100, 5)
    env["tax_rate"]         = round(env.get("income_tax_rate", 8.5) / 100, 5)
    env["housing_pressure"] = round(1.0 - env.get("housing_vacancy_rate", 4.2) / 20, 3)
    env["social_tension"]   = round(
        min(1.0,
            env.get("unemployment_rate", 5.5) / 30
            + env.get("poverty_rate", 13.5) / 80
            + env.get("violent_crime_rate", 0.8) / 10
        ), 3
    )

    # Drug economy value (see systems/crime.py) -- a real number, not
    # cosmetic: live drug_producer/drug_dealer_*/smuggler headcount times
    # each job's own CRIME_PROFILES cash-range midpoint. Production's
    # deliberately higher margins (Confirmed Decision #2) show up here
    # directly, not just per-character.
    try:
        from systems.crime import CRIME_PROFILES
        drug_jobs = ("drug_producer", "drug_dealer_low", "drug_dealer_mid", "smuggler")
        total = 0.0
        for c in world.get("characters", {}).values():
            job_tid = c.get("job_template_id") or (c.get("job") or {}).get("id")
            profile = CRIME_PROFILES.get(job_tid) if job_tid in drug_jobs else None
            if not profile:
                continue
            lo, hi = profile.get("cash_range", (0, 0))
            total += (lo + hi) / 2.0
        env["drug_economy_value"] = round(total, 2)
    except Exception:
        pass

    # Population natural change (very slow)
    pop = env.get("population", 52000)
    births = (env.get("birth_rate", 1.2) / 100 / 365) * pop
    deaths = (env.get("death_rate", 0.9) / 100 / 365) * pop
    env["population"] = max(0, round(pop + births - deaths))
