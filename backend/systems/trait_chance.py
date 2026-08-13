"""
systems/trait_chance.py — shared trait/belief learn-chance formula.

Single source of truth for "what's the odds character `c` learns/rolls
trait-or-belief template `T`", used both at character generation
(character_gen.py::_random_traits, weighted instead of the old uniform
random.sample) and at runtime adoption (systems/peer_influence.py) so the
same learn_chance/cognitive_modifiers/conditions math governs a trait's
odds everywhere, not two parallel implementations.
"""

from systems.schema_defaults import COGNITION_CORE_TRAITS


def cognition_type_of(traits):
    """Which of the 3 core cognition keys (logical/balanced/self_aware) a
    character's traits list implies. Defaults to 'balanced' if the
    mandatory core trait is somehow missing."""
    for t in traits or []:
        key = COGNITION_CORE_TRAITS.get(t)
        if key:
            return key
    return "balanced"


def _condition_met(cond, c, num_influencers=None):
    ctype = cond.get("type")
    if ctype == "sex":
        return c.get("sex") == cond.get("value")
    if ctype == "age_gt":
        return c.get("age", 0) > cond.get("value", 0)
    if ctype == "age_lt":
        return c.get("age", 0) < cond.get("value", 0)
    if ctype == "num_influencers":
        # Household members + close/best-friend contacts who already hold
        # the trait -- generation-time callers have no relationships yet,
        # so this fails closed (condition not met) when no count is given.
        if num_influencers is None:
            return False
        op = cond.get("op", ">=")
        value = cond.get("value", 0)
        if op == ">":
            return num_influencers > value
        if op == "<":
            return num_influencers < value
        return num_influencers == value
    return True


def compute_learn_chance(template, c, cognition_key, modifier_specs=None, num_influencers=None):
    """0-100 effective chance of `c` learning/rolling the trait or belief
    described by `template`, given their cognition type.

    `modifier_specs` is a list of (list_key, id_field, existing_ids)
    tuples, each checked independently against the running chance -- a
    trait template typically passes both `cognitive_modifiers` (checked
    against the character's other traits) and `belief_modifiers` (checked
    against their held beliefs); a belief template passes `trait_modifiers`
    (checked against their traits). Any single 0%-modifier match is a hard
    block (incompatible); any 100% match is an automatic grant."""
    learn_chance = template.get("learn_chance") or {}
    chance = float(learn_chance.get(cognition_key, 15.0))

    for cond in template.get("conditions") or []:
        if not _condition_met(cond, c, num_influencers):
            return 0.0

    for list_key, id_field, existing in (modifier_specs or []):
        existing = existing or set()
        for mod in template.get(list_key) or []:
            if mod.get(id_field) not in existing:
                continue
            m = mod.get("modifier", 0)
            if m == 0:
                return 0.0       # incompatible
            if m == 100:
                return 100.0     # automatic
            chance = max(0.0, min(100.0, chance + m))

    return max(0.0, min(100.0, chance))


def weighted_trait_pick(pool, c, cognition_key, count, existing=None):
    """Pick up to `count` distinct trait ids from `pool` (dict of id ->
    template), weighted by compute_learn_chance(). Falls back to a flat
    minimum weight for any trait that rolls 0 so a small pool doesn't
    starve -- this is generation-time flavor, not the strict pass/fail
    gate runtime adoption uses."""
    import random

    existing = set(existing or [])
    ids = list(pool.keys())
    if not ids:
        return []

    weights = []
    for tid in ids:
        chance = compute_learn_chance(
            pool[tid], c, cognition_key,
            modifier_specs=[("cognitive_modifiers", "trait", existing)],
        )
        weights.append(max(0.5, chance))  # small floor so nothing is un-rollable

    picked = []
    remaining_ids, remaining_weights = list(ids), list(weights)
    for _ in range(min(count, len(remaining_ids))):
        choice = random.choices(remaining_ids, weights=remaining_weights, k=1)[0]
        idx = remaining_ids.index(choice)
        remaining_ids.pop(idx)
        remaining_weights.pop(idx)
        picked.append(choice)
        existing.add(choice)

    return picked
