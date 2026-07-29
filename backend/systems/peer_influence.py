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
