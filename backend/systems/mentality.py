"""
systems/mentality.py

Background sweep that (re)compiles a character's principles/mentality/
opinions from their held_beliefs -- deliberately NOT run inline from
character_gen.py (see that module's _random_beliefs() docstring: a
blocking LLM call while world_lock() is held would stall the tick
loop). Every character with c["_mentality_pending"] = True (freshly
generated, or just adopted a new belief via systems/peer_influence.py)
gets processed here instead, in a normal un-locked tick-loop call --
the same safe context systems/household_summary.py's/
career_ladder.py's own LLM-backed sweeps already use.

Pipeline per character:
  held_beliefs -> llm/mentality_compiler.py::compile_principles()
               -> c["principles"], mentality summary
  principles + held_beliefs -> _compute_mentality_tags() (deterministic)
               -> c["mentality"]["tags"]/["concepts"]
  mentality -> llm/mentality_compiler.py::compile_political_views()
               -> seeds c["opinions"][topic] for every political topic
                  (brain/opinions.py::update_opinion())
"""

import random
from collections import Counter

# Small per-sweep batch cap -- mirrors this session's household_summary.py/
# career_ladder.py precedent for bounding an LLM-backed sweep's burst size.
MAX_PER_SWEEP = 5

# Confirmed Decision #5: a moderate starting confidence -- an inferred
# starting position, not yet reinforced by real lived experience.
_INITIAL_OPINION_CONFIDENCE = 0.35

# Phase H.2: real characters auto-derive their 1-3 "society category" areas
# from their own highest-importance c["values"] entries rather than picking
# manually (the preview tool's own manual picker is the other half of this,
# built in Phase H.5). VALUE_CATEGORIES (schema_defaults.py) barely overlaps
# with society_categories (definitions.json) -- only "religion" matches
# directly -- so this is a small, explicit translation table, not a reuse.
VALUE_TO_SOCIETY_CATEGORY = {
    "family":     "family",
    "friends":    "equality",
    "work":       "economy",
    "leisure":    "entertainment",
    "education":  "school",
    "romance":    "family",
    "children":   "school",
    "religion":   "religion",
    "politics":   "crime",
    "community":  "equality",
    "solidarity": "equality",
    "traditions": "religion",
}

# Phase H.2: reasoning lens auto-derived from cognition type for real
# characters (the preview tool's manual 3-way selector is the other half,
# Phase H.5) -- mirrors the same cognition-type-driven-flavor pattern the
# belief/trait descriptions system already uses.
_COGNITION_TO_REASONING_LENS = {
    "logical":    "pragmatism",
    "self_aware": "faith_superstition",
    "balanced":   "philosophy",
}


def derive_society_categories(c, defs):
    """1-3 real society_categories ids, auto-derived from c's own top
    highest-importance c["values"] entries via VALUE_TO_SOCIETY_CATEGORY
    (Confirmed Decision #4). Falls back to a uniform random 1-3 pick when
    c["values"] is missing/empty."""
    categories = list((defs.get("society_categories") or {}).keys())
    if not categories:
        return []

    values = c.get("values") or {}
    ranked = sorted(
        values.items(), key=lambda kv: kv[1].get("importance", 0), reverse=True,
    )
    candidates = []
    for value_cat, _ in ranked[:3]:
        mapped = VALUE_TO_SOCIETY_CATEGORY.get(value_cat)
        if mapped and mapped in categories and mapped not in candidates:
            candidates.append(mapped)

    if not candidates:
        candidates = list(categories)

    k = min(random.randint(1, 3), len(candidates))
    return random.sample(candidates, k)


def derive_reasoning_lens(c):
    """'philosophy' / 'faith_superstition' / 'pragmatism' -- auto-derived
    from the character's own cognition-core trait (Confirmed Decision #5)."""
    from systems.trait_chance import cognition_type_of

    cognition_key = cognition_type_of(c.get("traits", []))
    return _COGNITION_TO_REASONING_LENS.get(cognition_key, "philosophy")


def _principle_concept_ids(p):
    """The concept (not adjective) ids a principle references -- Phase
    I's `left`/`right` are {"type","id"} dicts now, only "concept"-typed
    sides carry real tags/relatedness (adjectives don't)."""
    ids = []
    for side in (p.get("left"), p.get("right")):
        if isinstance(side, dict) and side.get("type") == "concept" and side.get("id"):
            ids.append(side["id"])
    return ids


def _compute_mentality_tags(c, world):
    """Tags common across a character's held beliefs + the concepts
    their principles reference -- kept if it appears on 2+ of those
    items, or on every item when there are only 1-2 (Confirmed Decision
    #9). Purely deterministic, no LLM call."""
    defs = world.get("definitions", {})
    belief_templates = defs.get("belief_templates", {})
    concepts = world.get("principle_concepts") or defs.get("principle_concepts", {})

    items = []
    for bid in c.get("held_beliefs", []):
        tags = set(belief_templates.get(bid, {}).get("tags", []))
        if tags:
            items.append(tags)

    concept_ids = set()
    for p in c.get("principles", []):
        concept_ids.update(_principle_concept_ids(p))
    for cid in concept_ids:
        tags = set(concepts.get(cid, {}).get("tags", []))
        if tags:
            items.append(tags)

    if not items:
        return []

    counter = Counter()
    for tags in items:
        counter.update(tags)

    threshold = len(items) if len(items) <= 2 else 2
    return sorted(tag for tag, count in counter.items() if count >= threshold)


def _compile_one(c, world, categories=None, traits=None, reasoning_lens=None):
    """categories/traits/reasoning_lens are optional overrides -- a real
    character leaves them None and gets them auto-derived here
    (Phase H.2); the admin preview tool (Phase H.5) passes its own
    manual picks straight through to llm.mentality_compiler."""
    from llm.mentality_compiler import compile_principles, compile_political_views
    from brain.opinions import update_opinion

    defs = world.get("definitions", {})
    if categories is None:
        categories = derive_society_categories(c, defs)
    if traits is None:
        traits = c.get("traits", []) or []
    if reasoning_lens is None:
        reasoning_lens = derive_reasoning_lens(c)

    principles, summary, trait_coherence_suggestions = compile_principles(
        c, world, categories=categories, traits=traits, reasoning_lens=reasoning_lens,
    )
    c["principles"] = principles

    concept_ids = []
    for p in principles:
        for cid in _principle_concept_ids(p):
            if cid not in concept_ids:
                concept_ids.append(cid)

    tags = _compute_mentality_tags(c, world)

    c["mentality"] = {
        "principle_ids": [p["id"] for p in principles],
        "concepts": concept_ids,
        "tags": tags,
        "summary": summary,
        "society_categories": categories,
        "reasoning_lens": reasoning_lens,
        "trait_coherence_suggestions": trait_coherence_suggestions,
    }

    stances = compile_political_views(c, world, tags)
    tick = world.get("tick", 0)
    for topic, stance in stances.items():
        update_opinion(
            c, topic, stance, _INITIAL_OPINION_CONFIDENCE,
            "Inferred from mentality.", [], tick,
        )

    c["_mentality_pending"] = False


def tick_mentality_compilation(world):
    """Called from sim_loop.py's regular tick body (not inside any
    world_lock() section). Processes up to MAX_PER_SWEEP pending
    characters per call -- a character left over rolls into the next
    call rather than blocking a burst of LLM calls in one tick."""
    pending = [
        c for c in world.get("characters", {}).values()
        if c.get("_mentality_pending") and not c.get("is_workplace_npc")
    ]
    for c in pending[:MAX_PER_SWEEP]:
        try:
            _compile_one(c, world)
        except Exception:
            # Never let one character's compilation failure wedge the
            # whole sweep -- leave _mentality_pending set so it's retried
            # next call, matching this codebase's general "degrade, don't
            # crash the tick loop" posture for background LLM work.
            continue


# Phase I: sex -> gender-axis concept, mirrors mentality_compiler.py's
# own (private) _AXIS_SEX_CONCEPTS -- small, deliberate duplication
# rather than importing a private llm/ symbol into systems/.
_SEX_TO_GENDER_CONCEPT = {"male": "men", "female": "women"}


def _character_matches_concept(character, concept_id, world):
    """A real, narrow matcher (Confirmed Decision #7, Phase I) -- only
    resolves what's actually derivable from a character's own fields:
    sex for the men/women concepts, held_beliefs membership for any
    concept id that doubles as a belief id (religion/government_form,
    Phase A/H.1's convention). False for anything else (e.g.
    "the_rich"/"immigrants") -- a real, if narrow, matcher rather than
    one that always fires."""
    if not character or not concept_id:
        return False
    if _SEX_TO_GENDER_CONCEPT.get(character.get("sex")) == concept_id:
        return True
    return concept_id in (character.get("held_beliefs") or [])


def principle_stance_toward(c, other, world):
    """The strongest real stance c's own principles imply toward
    `other`, if any -- Confirmed Decision #7, Phase I's wired
    consequence (see brain/context_builder.py::_build_proposal_context()
    for the actual consumer -- item_loan/request proposal bias).

    Scans c["principles"] for a concept side `other` matches
    (_character_matches_concept): an `adjective_concept` match with a
    negative adjective, or a `concept_concept` match where `other` is
    the LESS-favored (right) side, is "unfavorable"; the mirror cases
    are "favorable". Returns the single strongest match by conviction
    ('>' beats '==' beats '<'), or None."""
    defs = world.get("definitions", {})
    adjectives = defs.get("adjectives_registry", {})
    concepts = world.get("principle_concepts") or defs.get("principle_concepts", {})

    def _op_strength(op):
        return {">": 2, "==": 1, "<": 0}.get(op, 0)

    def _label(side):
        if not side or not side.get("id"):
            return None
        if side.get("type") == "adjective":
            return adjectives.get(side["id"], {}).get("name", side["id"])
        return concepts.get(side["id"], {}).get("name", side["id"])

    best = None
    for p in c.get("principles", []):
        left, right = p.get("left") or {}, p.get("right") or {}
        shape = p.get("shape")
        sentiment = concept_label = adjective_label = None

        if shape == "adjective_concept" and _character_matches_concept(other, right.get("id"), world):
            polarity = adjectives.get(left.get("id"), {}).get("polarity")
            sentiment = "unfavorable" if polarity != "positive" else "favorable"
            concept_label, adjective_label = _label(right), _label(left)
        elif shape == "concept_adjective" and _character_matches_concept(other, left.get("id"), world):
            polarity = adjectives.get(right.get("id"), {}).get("polarity")
            sentiment = "favorable" if polarity != "negative" else "unfavorable"
            concept_label, adjective_label = _label(left), _label(right)
        elif shape == "concept_concept":
            if _character_matches_concept(other, left.get("id"), world):
                sentiment, concept_label = "favorable", _label(left)
            elif _character_matches_concept(other, right.get("id"), world):
                sentiment, concept_label = "unfavorable", _label(right)

        if not sentiment:
            continue
        if best is None or _op_strength(p.get("op")) > _op_strength(best["op"]):
            best = {
                "sentiment": sentiment, "op": p.get("op"),
                "concept_label": concept_label, "adjective_label": adjective_label,
            }

    return best
