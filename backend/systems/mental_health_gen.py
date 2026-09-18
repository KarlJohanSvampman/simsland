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


# Confirmed live bug, round 2 (player report: even after the first
# "two population-level gates" fix below, ~46% of generated characters
# still ended up with SOME diagnosed condition, empirically measured
# over N=3000 -- nowhere near the intended ~1-in-10). The four gates
# (mental-serious, mental-mild, physical-serious, physical-mild) were
# each independently rolled per REGISTRY, so "at least one of four"
# still compounds: 1-(0.9*0.8)^2 ≈ 48%, matching what was observed.
# Replaced with a SINGLE population-level "has any condition at all"
# gate (OVERALL_CONDITION_CHANCE) shared across both registries --
# only characters who pass it proceed to pick exactly one condition
# (mental or physical, serious or mild, weighted by the templates' own
# base_rate/age/sex logic among ALL eligible candidates combined), with
# a separate, small COMORBIDITY_CHANCE for a rare second condition.
# This one constant now directly controls the real "at least one
# diagnosed condition" population rate -- calibrated and verified via a
# live N=3000 sample to land within a percentage point or two of target.
OVERALL_CONDITION_CHANCE  = 0.10   # ~1-in-10 characters get ANY diagnosed condition
COMORBIDITY_CHANCE        = 0.12   # of those, a further chance of a second, independent condition
SERIOUS_SEVERITY_THRESHOLD = 6   # severity (1-10ish scale) >= this = "serious"


def _weighted_pick(pool):
    total_w = sum(entry[-1] for entry in pool)
    if total_w <= 0:
        return None
    r = random.uniform(0, total_w)
    upto = 0.0
    for entry in pool:
        upto += entry[-1]
        if upto >= r:
            return entry
    return pool[-1]


_REGISTRIES = (
    ("mental_health_templates", "mental_health"),
    ("physical_health_templates", "physical_health"),
)


def _build_condition_pools(c, defs):
    """Combined serious/mild pools across BOTH registries -- each entry
    (registry_key, target_list_key, tid, weight). Weight is the
    template's base_rate + age_progressive + common_sex logic, exactly
    as before; only used to pick WHICH condition among eligible
    candidates, never whether one is assigned at all (see
    OVERALL_CONDITION_CHANCE)."""
    age = c.get("age", 0)
    sex = c.get("sex")
    serious_pool = []
    mild_pool = []

    for registry_key, target_list_key in _REGISTRIES:
        registry = defs.get(registry_key, {})
        existing = c.get(target_list_key, [])
        for tid, tmpl in registry.items():
            base_rate = tmpl.get("base_rate", 0.0)
            if base_rate <= 0 or tid in existing:
                continue
            age_range = tmpl.get("common_age_range")
            if age_range and age < age_range[0]:
                continue

            weight = base_rate
            if tmpl.get("age_progressive"):
                weight *= _age_progressive_multiplier(age)
            weight *= _sex_multiplier(tmpl.get("common_sex"), sex)
            if weight <= 0:
                continue

            entry = (registry_key, target_list_key, tid, weight)
            if (tmpl.get("severity") or 0) >= SERIOUS_SEVERITY_THRESHOLD:
                serious_pool.append(entry)
            else:
                mild_pool.append(entry)

    return serious_pool, mild_pool


def _assign_one_condition(c, defs):
    """Picks exactly one condition (tier chosen proportional to each
    tier's combined weight, then a weighted pick within that tier) and
    applies it. Returns the assigned template id, or None if there was
    nothing eligible left to assign (e.g. every real candidate already
    diagnosed, or a very young character with no eligible templates)."""
    serious_pool, mild_pool = _build_condition_pools(c, defs)
    serious_w = sum(entry[-1] for entry in serious_pool)
    mild_w = sum(entry[-1] for entry in mild_pool)
    total_w = serious_w + mild_w
    if total_w <= 0:
        return None

    pool = serious_pool if random.uniform(0, total_w) < serious_w else mild_pool
    picked = _weighted_pick(pool)
    if not picked:
        return None

    registry_key, target_list_key, tid, _ = picked
    c.setdefault(target_list_key, []).append(tid)

    # Per the user's explicit ask: physical vs mental conditions
    # contribute to two SEPARATE handicap stats -- inferred from which
    # registry the winning pick came from.
    handicap_stat = "physical_handicap" if registry_key == "physical_health_templates" else "mental_handicap"
    from systems.handicap import apply_condition_handicap
    apply_condition_handicap(c, defs[registry_key][tid], handicap_stat)

    return tid


def assign_all_conditions(c, defs):
    """Called once at generation (see character_gen.py's post-build hook
    block). A single population-level gate (OVERALL_CONDITION_CHANCE)
    decides whether this character gets any diagnosed condition at all;
    only then does a further, separate roll (COMORBIDITY_CHANCE) decide
    whether a rare second, independent condition also gets assigned."""
    if random.random() > OVERALL_CONDITION_CHANCE:
        return []

    newly_added = []
    first = _assign_one_condition(c, defs)
    if first:
        newly_added.append(first)
        if random.random() < COMORBIDITY_CHANCE:
            second = _assign_one_condition(c, defs)
            if second:
                newly_added.append(second)

    return newly_added
