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

# Hard caps on personality/physical traits. Physical is enforced only at
# generation today (character_gen.py's _random_physical_traits) -- no
# runtime physical-trait-learning path exists yet, so MAX_PHYSICAL_TRAITS
# just documents the ceiling for whenever one does. Personality applies to
# the UNION of innate (c["traits"]) + learned (c["personality_traits"]),
# excluding the mandatory cognition-core trait (see schema_defaults.py's
# COGNITION_CORE_TRAITS) which sits outside the cap entirely. Beliefs
# share this same cap rather than getting a separate pool -- the original
# ask didn't call for two tunable caps.
MAX_PERSONALITY_TRAITS = 10
MAX_PHYSICAL_TRAITS    = 5


def _cap_count(observer):
    from systems.schema_defaults import COGNITION_CORE_TRAITS
    all_traits = set(observer.get("traits", []) + observer.get("personality_traits", []))
    return len([t for t in all_traits if t not in COGNITION_CORE_TRAITS])


def _make_room_for_trait(observer, new_trait_id, world):
    """If `observer` is at MAX_PERSONALITY_TRAITS, evict one LEARNED trait
    (never innate c["traits"], never the cognition-core trait) to make
    room for `new_trait_id`. Prefers a trait flagged incompatible (0%
    cognitive_modifiers) with the new one; otherwise the oldest learned
    trait by acquisition tick. Returns False (refuses to promote) only if
    at cap with nothing evictable, i.e. every held trait is innate."""
    if _cap_count(observer) < MAX_PERSONALITY_TRAITS:
        return True

    learned = observer.get("personality_traits", [])
    if not learned:
        return False

    try:
        from core.definitions import load_definitions
        trait_templates = load_definitions(world.get("sim_id", "default")).get("trait_templates", {})
    except Exception:
        trait_templates = {}

    new_tmpl = trait_templates.get(new_trait_id, {})
    incompatible = {m.get("trait") for m in new_tmpl.get("cognitive_modifiers", []) if m.get("modifier") == 0}
    victim = next((t for t in learned if t in incompatible), None)

    if victim is None:
        by_tick = {e["trait"]: e.get("acquired_tick", 0)
                   for e in observer.get("absorbed_traits", []) if not e.get("removed")}
        victim = min(learned, key=lambda t: by_tick.get(t, 0))

    learned.remove(victim)
    observer.setdefault("absorbed_traits", []).append({
        "trait": victim, "source": "cap_eviction",
        "acquired_tick": world.get("tick", 0), "removed": True,
        "replaced_by": new_trait_id,
    })
    return True


def _make_room_for_belief(observer, new_belief_id, world):
    """Belief-side mirror of _make_room_for_trait() -- shares the same
    MAX_PERSONALITY_TRAITS ceiling and observer["held_beliefs"] instead.
    No belief-to-belief incompatibility list exists (only trait_modifiers,
    checked against held traits, not other beliefs), so eviction always
    picks the oldest held belief."""
    all_beliefs = observer.get("held_beliefs", [])
    if len(all_beliefs) < MAX_PERSONALITY_TRAITS:
        return True
    if not all_beliefs:
        return False

    by_tick = {e["belief"]: e.get("acquired_tick", 0)
               for e in observer.get("absorbed_beliefs", []) if not e.get("removed")}
    victim = min(all_beliefs, key=lambda b: by_tick.get(b, 0))

    all_beliefs.remove(victim)
    observer.setdefault("absorbed_beliefs", []).append({
        "belief": victim, "source": "cap_eviction",
        "acquired_tick": world.get("tick", 0), "removed": True,
        "replaced_by": new_belief_id,
    })
    return True


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
    mirrors conditioning.py::_convert_to_trait()'s shape. Gated by cap
    room (MAX_PERSONALITY_TRAITS, evicting if needed -- see
    _make_room_for_trait()) and by the character's annual trait-learning
    budget (systems/trait_budget.py). Either gate failing defers
    promotion (NOT marked converted) so it's retried on the next
    qualifying exposure."""
    trait = entry["trait"]
    if trait in observer.get("personality_traits", []) or trait in observer.get("traits", []):
        entry["trait_converted"] = True
        return

    if not _make_room_for_trait(observer, trait, world):
        return

    from systems.trait_budget import try_consume_learn_slot
    if not try_consume_learn_slot(observer):
        return

    traits = observer.setdefault("personality_traits", [])
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
    # Solidarity's conform/non-conform axis is selective (in-group,
    # order-minded) vs. universal (open, not selective about who
    # deserves it) -- not generosity vs. individualism, which actively
    # contradicted the refined meaning (non-conform solidarity is still
    # solidarity, just unbounded). Reuses real trait_templates entries
    # already mapped from other categories -- see this dict's
    # ("work", False)/("romance", False) both already sharing
    # "free_spirited", so cross-category reuse is an established pattern.
    ("solidarity", True):  "loyal",
    ("solidarity", False): "open_minded",
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
    this is driven by aggregate daily exposure, not one person. Shares the
    same cap-eviction and annual budget gates as _promote_absorbed_trait()."""
    trait = entry["trait"]
    if trait in observer.get("personality_traits", []) or trait in observer.get("traits", []):
        entry["trait_converted"] = True
        return

    if not _make_room_for_trait(observer, trait, world):
        return

    from systems.trait_budget import try_consume_learn_slot
    if not try_consume_learn_slot(observer):
        return

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


# =========================================================
# COGNITIVE ADOPTION ENGINE (contact-hours + cognition-chance driven)
# =========================================================
# The general-purpose successor to record_positive_exposure() above for
# BOTH traits and beliefs: instead of raw exposure_ticks (proximity-only,
# decayed every 30 ticks by systems/influence.py::resolve_exposure_influence),
# this is driven by real hours logged with a contact (rel["hours_since_
# adoption_eval"], accumulated by systems/contact_designation.py's
# accumulate_hours -- same underlying proximity sweep, different
# non-decaying counter) weighted by that contact's designation tier's
# cognitive_bonus_per_hour, and gated per-trait/per-belief by
# trait_chance.py::compute_learn_chance() (learn_chance for the
# character's cognition type, cognitive_modifiers/trait_modifiers against
# what they already hold, and conditions).
#
# Reciprocal similarity cross-influence per the original design: shared
# BELIEFS make a character more open to a contact's TRAITS (traits are
# "the how", easier to absorb once you already see the world the same
# way); shared TRAITS make a character more open to a contact's BELIEFS
# (you already relate to how they operate, so their worldview carries
# more weight). Both are plain Jaccard overlap, deliberately not reusing
# brain/beliefs.py's belief_alignment() (that stays scoped to the
# political-axis system).

def _jaccard(a, b):
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def record_positive_belief_exposure(observer, source, belief, world, strength_gain=STRENGTH_GAIN_POSITIVE):
    """Belief-side mirror of record_positive_exposure() -- grows a
    belief_influence_profile entry, promoting past threshold into
    held_beliefs. See _promote_absorbed_belief()."""
    profile = observer.setdefault("belief_influence_profile", [])
    entry = next(
        (e for e in profile if e["source_person_id"] == source["id"] and e["belief"] == belief),
        None,
    )
    if entry is None:
        entry = {
            "source_person_id": source["id"],
            "belief":           belief,
            "strength":         0.0,
            "exposure_count":   0,
            "last_tick":        world.get("tick", 0),
        }
        profile.append(entry)

    entry["strength"]       = min(1.0, entry["strength"] + strength_gain)
    entry["exposure_count"] += 1
    entry["last_tick"]      = world.get("tick", 0)

    if (not entry.get("belief_converted")
            and entry["strength"] >= TRAIT_CONVERSION_THRESHOLD
            and entry["exposure_count"] >= MIN_REINFORCEMENTS):
        _promote_absorbed_belief(observer, entry, world)

    return entry


def _promote_absorbed_belief(observer, entry, world):
    """Promote an accumulated belief_influence_profile entry to a
    permanent held belief -- mirrors _promote_absorbed_trait()'s shape,
    sharing the same cap-eviction pool (_make_room_for_belief) and annual
    trait+belief budget as trait promotion."""
    belief = entry["belief"]
    if belief in observer.get("held_beliefs", []):
        entry["belief_converted"] = True
        return

    if not _make_room_for_belief(observer, belief, world):
        return

    from systems.trait_budget import try_consume_learn_slot
    if not try_consume_learn_slot(observer):
        return

    held = observer.setdefault("held_beliefs", [])
    if belief not in held:
        held.append(belief)
        observer.setdefault("absorbed_beliefs", []).append({
            "belief":            belief,
            "source":            "peer_influence",
            "source_person_id":  entry["source_person_id"],
            "acquired_tick":     world.get("tick", 0),
            "exposure_count":    entry["exposure_count"],
        })
    entry["belief_converted"] = True


def resolve_cognitive_adoption(world, defs, characters):
    """Main entry point for the trait/belief adoption pass -- called from
    sim_loop.py at the age-appropriate cadence (weekly for children/teens,
    monthly for adults; see systems/tick_schedule.py / sim_loop.py). For
    each character in `characters`, rolls trait and belief adoption
    against every relationship's accumulated contact hours."""
    from systems.trait_chance import cognition_type_of, compute_learn_chance
    from systems.trait_budget import record_social_engagement

    trait_templates  = defs.get("trait_templates", {})
    belief_templates = defs.get("belief_templates", {})
    tiers            = defs.get("contact_designations", {})
    tier_order       = tiers.get("order", [])
    chars            = world.get("characters", {})

    for c in characters:
        cognition_key = cognition_type_of(c.get("traits", []))
        my_traits  = set(c.get("traits", []) + c.get("personality_traits", []))
        my_beliefs = set(c.get("held_beliefs", []))

        for other_id, rel in list(c.get("relationships", {}).items()):
            hours = rel.get("hours_since_adoption_eval", 0.0)
            rel["hours_since_adoption_eval"] = 0.0  # consumed this cycle regardless of outcome
            if hours <= 0:
                continue

            other = chars.get(other_id)
            if not other:
                continue

            designation = rel.get("designation", "stranger")
            level = tier_order.index(designation) if designation in tier_order else 0
            record_social_engagement(c, hours, level)

            bonus = tiers.get(designation, {}).get("cognitive_bonus_per_hour", 0.0)
            weighted_exposure = hours * bonus
            if weighted_exposure <= 0:
                continue

            other_beliefs = set(other.get("held_beliefs", []))
            other_traits  = set(other.get("traits", []) + other.get("personality_traits", []))

            # "More beliefs in common -> more influenced in traits"
            trait_sim_mult = 1.0 + _jaccard(my_beliefs, other_beliefs)
            for trait_id in other_traits - my_traits:
                tmpl = trait_templates.get(trait_id)
                if not tmpl or tmpl.get("is_cognition_core"):
                    continue
                chance = compute_learn_chance(
                    tmpl, c, cognition_key,
                    modifier_specs=[
                        ("cognitive_modifiers", "trait",  my_traits),
                        ("belief_modifiers",    "belief", my_beliefs),
                    ],
                )
                if chance <= 0:
                    continue
                gain = weighted_exposure * (chance / 100.0) * trait_sim_mult * STRENGTH_GAIN_POSITIVE
                record_positive_exposure(c, other, trait_id, world, strength_gain=gain)

            # "More traits in common -> more influenced by beliefs"
            belief_sim_mult = 1.0 + _jaccard(my_traits, other_traits)
            for belief_id in other_beliefs - my_beliefs:
                tmpl = belief_templates.get(belief_id)
                if not tmpl:
                    continue
                chance = compute_learn_chance(
                    tmpl, c, cognition_key,
                    modifier_specs=[("trait_modifiers", "trait", my_traits)],
                )
                if chance <= 0:
                    continue
                gain = weighted_exposure * (chance / 100.0) * belief_sim_mult * STRENGTH_GAIN_POSITIVE
                record_positive_belief_exposure(c, other, belief_id, world, strength_gain=gain)
