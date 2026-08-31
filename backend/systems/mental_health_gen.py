"""
systems/mental_health_gen.py

Weighted-by-prevalence assignment of mental_health/physical_health
conditions at character generation -- both registries already had real,
richly-authored content (common_sex/common_age_range/severity/
need_penalties/medicine) that nothing ever assigned (confirmed via grep
-- the only way a character acquired one before this was a handful of
runtime triggers deep in health.py, e.g. stroke/head-trauma). One
shared engine, called twice from character_gen.py, rather than two
separate assignment systems.

Each eligible template carries base_rate (approximate real-world
current-prevalence, 0-1) and age_progressive (bool). Conditions roll
independently, not mutually exclusive -- real comorbidity is realistic
and simpler than a single-pick model.
"""

import random

_AGE_BUCKET_MULTIPLIERS = [
    (30, 0.3),
    (50, 1.0),
    (65, 1.8),
    (80, 3.0),
    (999, 4.5),
]


def _age_progressive_multiplier(age):
    for cap, mult in _AGE_BUCKET_MULTIPLIERS:
        if age < cap:
            return mult
    return _AGE_BUCKET_MULTIPLIERS[-1][1]


def _sex_multiplier(common_sex, sex):
    # Pre-existing content inconsistently uses "any" and "all" as the
    # no-preference sentinel (confirmed via grep across both
    # registries) -- both mean the same thing here.
    if not common_sex or common_sex in ("any", "all"):
        return 1.0
    return 1.6 if sex == common_sex else 0.5


def assign_conditions(c, defs, registry_key, target_list_key):
    """Rolls every template in defs[registry_key] with a nonzero
    base_rate against c's age/sex, appending hits to c[target_list_key]
    (mental_health / physical_health -- whichever list already exists
    on the character). age eligibility: age >= common_age_range[0]
    (the lower bound only -- an existing diagnosis persists past a
    template's typical-onset upper bound, it doesn't just vanish)."""
    registry = defs.get(registry_key, {})
    if not registry:
        return []

    age = c.get("age", 0)
    sex = c.get("sex")
    existing = c.setdefault(target_list_key, [])
    newly_added = []

    for tid, tmpl in registry.items():
        base_rate = tmpl.get("base_rate", 0.0)
        if base_rate <= 0 or tid in existing:
            continue

        age_range = tmpl.get("common_age_range")
        if age_range and age < age_range[0]:
            continue

        rate = base_rate
        if tmpl.get("age_progressive"):
            rate *= _age_progressive_multiplier(age)
        rate *= _sex_multiplier(tmpl.get("common_sex"), sex)
        rate = max(0.0, min(0.95, rate))

        if random.random() < rate:
            existing.append(tid)
            newly_added.append(tid)

    return newly_added


def assign_all_conditions(c, defs):
    """Called once at generation (see character_gen.py's post-build hook
    block) -- rolls both registries against the same character."""
    assign_conditions(c, defs, "mental_health_templates", "mental_health")
    assign_conditions(c, defs, "physical_health_templates", "physical_health")
