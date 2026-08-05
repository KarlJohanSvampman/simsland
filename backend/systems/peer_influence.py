"""
systems/peer_influence.py — trait absorption from prolonged positive exposure

Deliberately separate from conditioning.py rather than merged into it —
"authority conditions you via discipline events" and "peers/trusted people
influence you via prolonged exposure" are distinct trigger mechanisms even
though they share a threshold-promotion shape. Reuses conditioning.py's
threshold constants for consistency, keyed by (source_person_id, trait)
instead of (stimulus, response_type).
"""

TRAIT_CONVERSION_THRESHOLD = 0.70
MIN_REINFORCEMENTS         = 15
STRENGTH_GAIN_POSITIVE     = 0.06


def record_positive_exposure(observer, source, trait, world, strength_gain=STRENGTH_GAIN_POSITIVE):
    """Grow (or create) an influence_profile entry for observer absorbing
    `trait` from `source`. Past threshold, promotes it to a permanent
    personality trait -- see _promote_absorbed_trait()."""
    profile = observer.setdefault("influence_profile", [])
    entry = next(
        (e for e in profile if e["source_person_id"] == source["id"] and e["trait"] == trait),
        None,
    )
    if entry is None:
        entry = {
            "source_person_id": source["id"],
            "trait":            trait,
            "strength":         0.0,
            "exposure_count":   0,
            "last_tick":        world.get("tick", 0),
        }
        profile.append(entry)

    entry["strength"]       = min(1.0, entry["strength"] + strength_gain)
    entry["exposure_count"] += 1
    entry["last_tick"]      = world.get("tick", 0)

    if (not entry.get("trait_converted")
            and entry["strength"] >= TRAIT_CONVERSION_THRESHOLD
            and entry["exposure_count"] >= MIN_REINFORCEMENTS):
        _promote_absorbed_trait(observer, entry, world)

    return entry


def _promote_absorbed_trait(observer, entry, world):
    """Promote an accumulated influence_profile entry to a permanent trait --
    mirrors conditioning.py::_convert_to_trait()'s shape."""
    trait = entry["trait"]
    traits = observer.setdefault("personality_traits", [])
    if trait not in traits:
        traits.append(trait)
        observer.setdefault("absorbed_traits", []).append({
            "trait":             trait,
            "source":            "peer_influence",
            "source_person_id":  entry["source_person_id"],
            "acquired_tick":     world.get("tick", 0),
            "exposure_count":    entry["exposure_count"],
        })
    entry["trait_converted"] = True


# =========================================================
# VALUE-DRIVEN TRAIT ACQUISITION (children/teens only)
# =========================================================
# Distinct from record_positive_exposure() above, which imitates a
# specific trusted PERSON's traits -- this is "children partly become
# what they're around" via the daily value-influence pressure itself
# (systems/influence.py::resolve_value_influence's per-category
# reinforce/oppose signal), not any one source person. Reuses this
# module's exact threshold-promotion shape/constants, keyed by trait
# instead of (source_person_id, trait).

VALUE_CATEGORY_TRAIT_HINTS = {
    ("family",     True):  "family_oriented",
    ("family",     False): "independent",
    ("friends",    True):  "loyal",
    ("friends",    False): "self_reliant",
    ("work",       True):  "conscientious",
    ("work",       False): "free_spirited",
    ("leisure",    True):  "disciplined",
    ("leisure",    False): "carefree",
    ("education",  True):  "studious",
    ("education",  False): "unconventional",
    ("romance",    True):  "traditional_romantic",
    ("romance",    False): "free_spirited",
    ("children",   True):  "nurturing",
    ("children",   False): "independent",
    ("religion",   True):  "devout",
    ("religion",   False): "skeptical",
    ("politics",   True):  "civic_minded",
    ("politics",   False): "independent_minded",
    ("community",  True):  "community_minded",
    ("community",  False): "self_reliant",
    ("solidarity", True):  "generous",
    ("solidarity", False): "individualistic",
    ("traditions", True):  "traditional",
    ("traditions", False): "unconventional",
}

CHILD_TRAIT_ACQUISITION_AGE_GROUPS = ("child", "teen")


def record_value_trait_exposure(observer, category, conform, world, strength_gain=STRENGTH_GAIN_POSITIVE):
    """Grow (or create) a value_trait_profile entry for `observer` being
    shaped toward the trait mapped from (category, conform) by
    VALUE_CATEGORY_TRAIT_HINTS. Callers should only invoke this for
    child/teen characters -- see systems/influence.py's
    resolve_value_influence, which only calls this branch for
    age_group in CHILD_TRAIT_ACQUISITION_AGE_GROUPS. No-ops if the
    (category, conform) pair has no mapped trait."""
    trait = VALUE_CATEGORY_TRAIT_HINTS.get((category, conform))
    if not trait:
        return None

    profile = observer.setdefault("value_trait_profile", [])
    entry = next((e for e in profile if e["trait"] == trait), None)
    if entry is None:
        entry = {
            "trait":           trait,
            "strength":        0.0,
            "exposure_count":  0,
            "last_tick":       world.get("tick", 0),
        }
        profile.append(entry)

    entry["strength"]       = min(1.0, entry["strength"] + strength_gain)
    entry["exposure_count"] += 1
    entry["last_tick"]      = world.get("tick", 0)

    if (not entry.get("trait_converted")
            and entry["strength"] >= TRAIT_CONVERSION_THRESHOLD
            and entry["exposure_count"] >= MIN_REINFORCEMENTS):
        _promote_value_trait(observer, entry, world)

    return entry


def _promote_value_trait(observer, entry, world):
    """Promote an accumulated value_trait_profile entry to a permanent
    trait -- mirrors _promote_absorbed_trait()'s shape, logged with
    source "value_influence" instead of a single source_person_id since
    this is driven by aggregate daily exposure, not one person."""
    trait = entry["trait"]
    traits = observer.setdefault("personality_traits", [])
    if trait not in traits:
        traits.append(trait)
        observer.setdefault("absorbed_traits", []).append({
            "trait":            trait,
            "source":           "value_influence",
            "acquired_tick":    world.get("tick", 0),
            "exposure_count":   entry["exposure_count"],
        })
    entry["trait_converted"] = True
