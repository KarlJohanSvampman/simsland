"""
relative_gen.py — procedural derivation of a relative's traits/hobbies/
physical_traits from a source character, plus a small templated bio
fallback used when no LLM narration is available (or desired, as in the
live-sim family generator, which never calls the LLM).

Entry point: derive_relative(source_char, relation_type, defs, sex=None)
"""
import random

from systems.character_gen import _random_traits, _random_hobbies, _random_physical_traits

# Blood relations close enough to inherit at the full rate.
_SHARED_RELATIONS = {"parent", "sibling", "child"}
# More diluted blood relations -- half the direct-relation inheritance chance.
_DILUTED_RELATIONS = {"grandparent", "aunt_uncle", "cousin"}
# Not blood relations -- no derivation, fully random (same as today).
_NO_DERIVATION_RELATIONS = {"spouse", "ex_spouse"}

_DIRECT_TRAIT_CHANCE = 0.45
_DIRECT_HOBBY_CHANCE = 0.275
_DILUTED_MULTIPLIER = 0.5


def _inherit_from_pool(source_items, pool, count, chance):
    """
    Each of the source's items has an independent `chance` shot at being
    copied. Top up to `count` total with random draws from `pool` for any
    remaining slots (never re-picking an item already chosen).
    """
    inherited = [item for item in source_items if item in pool and random.random() < chance]
    chosen = list(dict.fromkeys(inherited))  # de-dupe, preserve order
    remaining_pool = [k for k in pool if k not in chosen]
    while len(chosen) < count and remaining_pool:
        pick = random.choice(remaining_pool)
        remaining_pool.remove(pick)
        chosen.append(pick)
    return chosen[:count]


def derive_relative(source_char, relation_type, defs, sex=None):
    """
    relation_type: "parent" | "sibling" | "child" | "spouse" | "grandparent"
                  | "aunt_uncle" | "cousin" | "ex_spouse"
    sex: unused here (age/sex are relation-appropriate concerns the caller
         already handles) -- accepted for call-site symmetry only.
    Returns: {"traits": [...], "hobbies": [...], "physical_traits": [...]}
    """
    if relation_type in _NO_DERIVATION_RELATIONS:
        return {
            "traits": _random_traits(defs),
            "hobbies": _random_hobbies(defs),
            "physical_traits": _random_physical_traits(defs),
        }

    trait_chance = _DIRECT_TRAIT_CHANCE
    hobby_chance = _DIRECT_HOBBY_CHANCE
    if relation_type in _DILUTED_RELATIONS:
        trait_chance *= _DILUTED_MULTIPLIER
        hobby_chance *= _DILUTED_MULTIPLIER

    trait_pool = defs.get("trait_templates", {})
    trait_keys = [k for k in trait_pool if not k.startswith("_")] if isinstance(trait_pool, dict) else list(trait_pool)
    hobby_pool = defs.get("hobby_templates", {})
    hobby_keys = [k for k in hobby_pool if not k.startswith("_")] if isinstance(hobby_pool, dict) else list(hobby_pool)

    source_traits = source_char.get("traits", []) or source_char.get("personality_traits", [])
    source_hobbies = source_char.get("hobbies", [])
    source_physical = source_char.get("physical_traits", [])

    physical_pool = list(defs.get("physical_trait_templates", {}).keys())

    return {
        "traits": _inherit_from_pool(source_traits, trait_keys, min(3, len(trait_keys)), trait_chance),
        "hobbies": _inherit_from_pool(source_hobbies, hobby_keys, min(2, len(hobby_keys)), hobby_chance),
        "physical_traits": _inherit_from_pool(source_physical, physical_pool, min(4, len(physical_pool)), trait_chance),
    }


_RELATION_LABELS = {
    "parent": "parent", "sibling": "sibling", "child": "child",
    "spouse": "spouse", "grandparent": "grandparent",
    "aunt_uncle": "aunt or uncle", "cousin": "cousin", "ex_spouse": "ex-spouse",
}


def _fallback_bio(source_char, relation_type, derived_traits):
    source_name = source_char.get("name", "them")
    relation_label = _RELATION_LABELS.get(relation_type, relation_type)
    if derived_traits:
        return f"Known for being {derived_traits[0].lower()}, {source_name}'s {relation_label}."
    return f"{source_name}'s {relation_label}."


# Rough age/sex estimation for relation_type -- used only by the
# Character-Creator-triggered single-relative endpoint, which (unlike
# family.py's generate_family_for_character()) has no existing age-band
# logic of its own to defer to.
_AGE_OFFSET_RANGES = {
    "parent":      (20, 35),
    "child":       (-35, -20),
    "sibling":     (-10, 10),
    "spouse":      (-8, 8),
    "ex_spouse":   (-10, 10),
    "grandparent": (40, 60),
    "aunt_uncle":  (15, 40),
    "cousin":      (-15, 15),
}
_OPPOSITE_SEX_RELATIONS = {"spouse", "ex_spouse"}


def estimate_age_sex(source_age, source_sex, relation_type):
    lo, hi = _AGE_OFFSET_RANGES.get(relation_type, (-10, 10))
    age = max(1, int(source_age or 25) + random.randint(lo, hi))
    if relation_type in _OPPOSITE_SEX_RELATIONS:
        sex = "female" if source_sex == "male" else "male"
    else:
        sex = random.choice(["male", "female"])
    return age, sex
