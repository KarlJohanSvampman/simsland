"""
llm/mentality_compiler.py

The two AI-backed compilation steps in the belief -> principle ->
mentality -> opinion pipeline (see systems/mentality.py for the sweep
that calls these, and systems/character_gen.py::_random_beliefs() for
the deterministic belief-selection step that happens earlier, inline
at generation). Both functions follow the same proven shape as
llm/work_shift_narration.py: one strict-JSON call, session-keyed on the
character, a real deterministic fallback that never returns nothing,
bridged synchronously via llm.llm_gate.run_llm_call(...,
priority=PRIORITY_BACKGROUND).

compile_principles()      -- held_beliefs -> principles. Each principle
                              is one of 3 shapes (Phase I):
                              concept_adjective (first-person, positive
                              -- "X is credible"), adjective_concept
                              (prejudice -- "dishonest > women"), or
                              concept_concept (axis-restricted, e.g.
                              gender/religion/government_form -- "men >
                              women"). `op` (>/</==) is a conviction-
                              strength quantifier, not just magnitude.
compile_political_views() -- principles -> initial c["opinions"] stance
                              values across the political topic set.
"""

import json
import random

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

# Same topic set brain/beliefs.py's IDEOLOGY_AXES used to cover, flattened --
# this is what "compile political views" seeds in c["opinions"].
POLITICAL_TOPICS = [
    "taxes", "economy", "cost_of_living", "welfare",
    "crime", "police", "safety",
    "immigration", "homelessness",
    "justice", "government", "media",
    "honor", "loyalty", "ambition", "integrity", "self_reliance",
]

# Light, defensible tag -> topic nudges for the deterministic fallback
# only (the real call reasons about this itself) -- (tag, topic, delta).
_TAG_TOPIC_NUDGES = [
    ("collectivist", "welfare", 0.3), ("individualist", "welfare", -0.2),
    ("individualist", "taxes", -0.3), ("collectivist", "taxes", 0.2),
    ("anti_establishment", "government", -0.4), ("anti_establishment", "media", -0.4),
    ("institutional", "government", 0.2),
    ("traditionalist", "immigration", -0.3), ("nationalist", "immigration", -0.3),
    ("marginalized", "welfare", 0.3), ("marginalized", "homelessness", 0.3),
    ("hierarchical", "police", 0.2), ("authoritarian", "police", 0.3),
    ("exclusionary", "immigration", -0.4),
    ("moral_order", "integrity", 0.3), ("moral_order", "honor", 0.3),
    ("elitist", "cost_of_living", -0.2),
]


# Phase H.3: how many principles a compile pass rolls -- was implicitly
# "whatever the LLM felt like producing" (2-4) before the roll-structure-
# first rewrite; kept as the same real range.
_PRINCIPLE_COUNT_RANGE = (2, 4)

_REASONING_LENS_LABELS = {
    "philosophy":        "abstract ethical/philosophical reasoning",
    "faith_superstition": "spiritual, mystical, faith-driven conviction",
    "pragmatism":        "practical, cost-benefit, real-world reasoning",
}


def _trait_relates_to_concept(trait_id, trait_templates, concept_tags):
    """Simple keyword heuristic (trait_templates entries have no tags
    field of their own, per Phase H research) -- does this trait's own
    name/description text plausibly relate to the concept's tags."""
    if not concept_tags:
        return False
    tmpl = trait_templates.get(trait_id, {})
    text = f"{tmpl.get('name', trait_id)} {tmpl.get('description', '')}".lower().replace("_", " ")
    return any(tag.replace("_", " ") in text for tag in concept_tags)


# Phase I: how the 3 principle shapes are weighted on each roll --
# documented starting weights, easily retuned.
_SHAPE_WEIGHTS = [("concept_adjective", 0.4), ("adjective_concept", 0.4), ("concept_concept", 0.2)]

# Phase I: for an axis-restricted concept_concept roll, how often the
# anchor concept is pinned to the character's OWN real value in that
# axis (sex for gender, a held belief for religion/government_form)
# rather than picked randomly from the axis.
_AXIS_SELF_ANCHOR_CHANCE = 0.8

_AXIS_SEX_CONCEPTS = {"male": "men", "female": "women"}


def _scored_concepts(held_beliefs, categories, traits, defs, world):
    """Every real principle_concepts id, scored by tag-overlap with held
    beliefs + category-relatedness + trait-flavor bonus (Phase H.3's
    original weighting) -- the shared "how similar is this concept to
    what I already believe/value" signal both concept_adjective (used
    as-is) and adjective_concept (inverted, Confirmed Decision #4)
    read from."""
    concepts = world.get("principle_concepts") or defs.get("principle_concepts", {})
    belief_templates = defs.get("belief_templates", {})
    trait_templates = defs.get("trait_templates", {})

    belief_tags = set()
    for bid in held_beliefs:
        belief_tags.update(belief_templates.get(bid, {}).get("tags", []))

    category_set = set(categories or [])
    trait_list = list(traits or [])

    scored = []
    for cid, entry in concepts.items():
        tags = set(entry.get("tags", []))
        score = len(belief_tags & tags) * 2.0
        if category_set and category_set & set(entry.get("related_categories", [])):
            score += 3.0
        if trait_list and any(_trait_relates_to_concept(t, trait_templates, tags) for t in trait_list):
            score += 2.0
        scored.append((max(score, 0.1), cid))
    return scored


def _weighted_concept_pick(scored, invert=False):
    """scored: [(score, concept_id), ...]. invert=True favors LOW-score
    (dissimilar/"opposite of us") concepts instead of high-score ones --
    Confirmed Decision #4's outgroup bias for adjective_concept."""
    if not scored:
        return None
    ids = [cid for _, cid in scored]
    if invert:
        weights = [1.0 / (1.0 + s) for s, _ in scored]
    else:
        weights = [s for s, _ in scored]
    return random.choices(ids, weights=weights, k=1)[0]


def _pick_adjective(defs, polarity):
    adjectives = defs.get("adjectives_registry", {})
    pool = [aid for aid, a in adjectives.items() if a.get("polarity") == polarity]
    if not pool:
        pool = list(adjectives.keys()) or ["notable"]
    return random.choice(pool)


def _character_own_axis_concept(c, axis_members, world):
    """Which concept in this axis the character actually holds, if any
    -- sex for the gender axis (Confirmed Decision #2), a real held
    belief for religion/government_form (belief ids double as concept
    ids, Phase A/H.1's convention). None if unresolvable (e.g. the
    economic_model axis, or a character with no belief in that axis)."""
    sex_concept = _AXIS_SEX_CONCEPTS.get(c.get("sex"))
    if sex_concept in axis_members:
        return sex_concept
    held = set(c.get("held_beliefs", []) or [])
    for bid in held:
        if bid in axis_members:
            return bid
    return None


def _roll_concept_concept(c, defs, world):
    """Axis-restricted concept-vs-concept (Confirmed Decision #2/#4,
    Phase I) -- pick a real axis, an anchor concept (biased toward the
    character's own real value in that axis when resolvable), and a
    DISTINCT counterpart from the SAME axis (the "subset of
    counterparts" -- literally the rest of the axis)."""
    axes = defs.get("principle_concept_axes", {})
    if not axes:
        return None
    axis = random.choice(list(axes.values()))
    members = [m for m in axis.get("concepts", []) if m]
    if len(members) < 2:
        return None

    own = _character_own_axis_concept(c, members, world)
    if own and random.random() < _AXIS_SELF_ANCHOR_CHANCE:
        anchor = own
    else:
        anchor = random.choice(members)
    counterpart_pool = [m for m in members if m != anchor]
    if not counterpart_pool:
        return None
    counterpart = random.choice(counterpart_pool)
    return {
        "left": {"type": "concept", "id": anchor},
        "right": {"type": "concept", "id": counterpart},
        "op": random.choice([">", "<", "=="]),
        "shape": "concept_concept",
    }


def _roll_principle(c, held_beliefs, categories, traits, defs, world):
    """One rolled principle structure -- Confirmed Decision #4, Phase I.
    Three shapes:
      concept_adjective -- left concept (similarity-weighted, unchanged
        from Phase H.3), right a POSITIVE adjective. First-person,
        positive: what the character believes about something they value.
      adjective_concept -- left a NEGATIVE adjective, right a concept
        (weighting INVERTED -- favors a concept dissimilar to the
        character's own beliefs, the "opposite of us" outgroup bias).
        The prejudice form.
      concept_concept -- axis-restricted (see _roll_concept_concept);
        falls back to concept_adjective if no axis pair resolves (e.g.
        principle_concept_axes missing from defs).
    Returns {"left": {"type","id"}, "right": {"type","id"}, "op", "shape"}.
    """
    shape = random.choices(
        [s for s, _ in _SHAPE_WEIGHTS], weights=[w for _, w in _SHAPE_WEIGHTS], k=1,
    )[0]

    if shape == "concept_concept":
        rolled = _roll_concept_concept(c, defs, world)
        if rolled:
            return rolled
        shape = "concept_adjective"  # fall through to a shape that always resolves

    scored = _scored_concepts(held_beliefs, categories, traits, defs, world)
    op = random.choice([">", "<", "=="])

    if shape == "adjective_concept":
        concept_id = _weighted_concept_pick(scored, invert=True)
        adjective_id = _pick_adjective(defs, "negative")
        return {
            "left": {"type": "adjective", "id": adjective_id},
            "right": {"type": "concept", "id": concept_id},
            "op": op, "shape": "adjective_concept",
        }

    concept_id = _weighted_concept_pick(scored, invert=False)
    adjective_id = _pick_adjective(defs, "positive")
    return {
        "left": {"type": "concept", "id": concept_id},
        "right": {"type": "adjective", "id": adjective_id},
        "op": op, "shape": "concept_adjective",
    }


def _label_side(side, defs, world):
    """Resolves a {"type","id"} principle side to its display name,
    checking the concept or adjective registry per its type."""
    if not side or not side.get("id"):
        return "something"
    if side.get("type") == "adjective":
        return defs.get("adjectives_registry", {}).get(side["id"], {}).get("name", side["id"])
    concepts = world.get("principle_concepts") or defs.get("principle_concepts", {})
    return concepts.get(side["id"], {}).get("name", side["id"])


def _fallback_principle_reasoning(shape, op, left_label, right_label):
    """Never blank (Confirmed Decision #5) -- a real templated sentence
    per shape x conviction tier, used when the batched narration LLM
    call is unreachable."""
    if shape == "concept_adjective":
        if op == ">":
            return f"Firmly convinced that {left_label} is {right_label}."
        if op == "<":
            return f"Suspects, tentatively, that {left_label} might be {right_label}."
        return f"Generally sees {left_label} as {right_label}."
    if shape == "adjective_concept":
        if op == ">":
            return f"Holds a firm, hard-to-shake conviction that {right_label} are {left_label}."
        if op == "<":
            return f"Has a nagging, not-fully-formed suspicion that {right_label} might be {left_label}."
        return f"Generally assumes {right_label} tend to be {left_label}."
    # concept_concept
    if op == ">":
        return f"Firmly identifies with {left_label} over {right_label}."
    if op == "<":
        return f"Leans toward {left_label} over {right_label}, but isn't rigid about it."
    return f"Sees {left_label} and {right_label} as basically comparable."


_SHAPE_NARRATION_HINTS = {
    "concept_adjective": "first-person and POSITIVE -- this is what the character themselves believes about something they value (e.g. \"I believe X is credible, and I'll stick with it\")",
    "adjective_concept": "a PREJUDICED generalization about that group -- a negative belief the character holds about people like them (e.g. \"I've never trusted people like that\")",
    "concept_concept": "the character identifying with one side over the other on a real, opposed axis (e.g. \"I side with X over Y\")",
}


async def _narrate_principles_and_suggestions(c, structures, belief_lines, categories, traits, reasoning_lens, defs, world):
    """ONE batched LLM call narrating every rolled principle's reasoning
    text "in a semantic way" (Confirmed Decision #5) PLUS trait-coherence
    suggestions -- mirrors llm/work_shift_narration.py's batch-JSON
    shape exactly. Phase I: each structure now also carries a `shape`
    (concept_adjective / adjective_concept / concept_concept) so the
    prompt can tell the LLM exactly what kind of statement to write."""
    session = c.setdefault("_mentality_llm_session", {"history": []})

    structure_lines = "\n".join(
        f'{i}. "{_label_side(s["left"], defs, world)}" {s["op"]} "{_label_side(s["right"], defs, world)}" '
        f'-- write this as {_SHAPE_NARRATION_HINTS.get(s["shape"], "a natural comparison")}'
        for i, s in enumerate(structures)
    )
    lens_label = _REASONING_LENS_LABELS.get(reasoning_lens, "abstract ethical/philosophical reasoning")
    categories_line = ", ".join(categories) if categories else "(none specified)"

    trait_templates = defs.get("trait_templates", {})
    held_traits = c.get("traits", []) or []
    trait_lines = "\n".join(
        f"- {trait_templates.get(t, {}).get('name', t)}: {trait_templates.get(t, {}).get('description', '')}"
        for t in held_traits
    ) or "(no notable traits on record)"

    prompt = f"""
{c.get('name', 'This character')} holds these deep beliefs:
{belief_lines}

Society areas they're currently thinking about: {categories_line}

The following {len(structures)} comparisons have ALREADY been decided --
your job is ONLY to write why, in a semantic/natural way, framed through
a lens of {lens_label}:
{structure_lines}

Also write a "summary" -- one short sentence describing this
character's overall mindset/worldview.

Finally, compare this character's CURRENT traits against the mentality
you just described, and note up to 3 real coherence suggestions (a trait
that seems to clash and should perhaps be dropped, or one that seems
implied but is missing) -- purely informational, nothing is auto-applied:
{trait_lines}

Respond with STRICT JSON only:
{{"reasonings": ["one short sentence per comparison above, in order"],
"summary": "one short sentence",
"trait_coherence_suggestions": [{{"suggestion": "add", "trait": "trait_id_or_name", "reasoning": "..."}}, ...]}}
"""
    messages = [
        {"role": "system", "content": "You write natural-language justifications for a character's already-decided worldview comparisons, and assess trait coherence, for a life-simulation game. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    reasonings = parsed.get("reasonings")
    if not isinstance(reasonings, list):
        reasonings = []
    summary = parsed.get("summary")
    suggestions = parsed.get("trait_coherence_suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    clean_suggestions = []
    for s in suggestions[:3]:
        if not isinstance(s, dict):
            continue
        if s.get("suggestion") not in ("add", "remove"):
            continue
        if not s.get("trait"):
            continue
        clean_suggestions.append({
            "suggestion": s["suggestion"],
            "trait": str(s["trait"])[:60],
            "reasoning": str(s.get("reasoning", ""))[:200],
        })
    return {
        "reasonings": [str(r)[:200] for r in reasonings],
        "summary": summary if isinstance(summary, str) and summary.strip() else None,
        "trait_coherence_suggestions": clean_suggestions,
    }


def compile_principles(c, world, categories=None, traits=None, reasoning_lens=None):
    """Sync entry point -- run from systems/mentality.py's un-locked
    sweep, never from character_gen.py (see that module's own comment
    on why LLM calls can't happen there).

    Phase H.3/I restructure: each principle's structure (which shape --
    concept_adjective / adjective_concept / concept_concept -- and its
    concept(s)/adjective/operator) is rolled DETERMINISTICALLY first
    (_roll_principle), then ONE batched LLM call narrates every slot's
    reasoning text plus a trait-coherence pass -- the LLM no longer
    invents the comparison itself, only the "why."

    `categories`/`traits`/`reasoning_lens` are all optional, defaulting
    sensibly (empty categories, the character's own held traits, and
    "philosophy") for any existing caller that doesn't pass them --
    real characters get real derived values from systems/mentality.py,
    the admin preview tool (Phase H.5) can pass its own manual picks.

    Returns (principles, summary, trait_coherence_suggestions)."""
    defs = world.get("definitions", {})
    belief_templates = defs.get("belief_templates", {})
    held_beliefs = c.get("held_beliefs", [])
    categories = categories or []
    traits = traits if traits is not None else (c.get("traits", []) or [])
    reasoning_lens = reasoning_lens or "philosophy"

    # Lazily seed world["principle_concepts"] from defs on first use --
    # same "grows at runtime" contract this module has always had.
    world.setdefault("principle_concepts", dict(defs.get("principle_concepts", {})))

    belief_lines = "\n".join(
        f"- {belief_templates.get(bid, {}).get('name', bid)}: "
        f"{belief_templates.get(bid, {}).get('descriptions', {}).get('balanced', '')}"
        for bid in held_beliefs
    ) or "(no strong deep beliefs)"

    count = random.randint(*_PRINCIPLE_COUNT_RANGE)
    structures = [_roll_principle(c, held_beliefs, categories, traits, defs, world) for _ in range(count)]

    narrated = run_llm_call(
        _narrate_principles_and_suggestions(
            c, structures, belief_lines, categories, traits, reasoning_lens, defs, world,
        ),
        priority=PRIORITY_BACKGROUND,
    )

    reasonings = (narrated or {}).get("reasonings") or []
    summary = (narrated or {}).get("summary")
    suggestions = (narrated or {}).get("trait_coherence_suggestions") or []

    principles = []
    for i, s in enumerate(structures):
        reasoning = reasonings[i] if i < len(reasonings) and reasonings[i] else None
        if not reasoning:
            reasoning = _fallback_principle_reasoning(
                s["shape"], s["op"],
                _label_side(s["left"], defs, world), _label_side(s["right"], defs, world),
            )
        principles.append({
            "id": f"pr_{c.get('id', 'x')}_{i}",
            "op": s["op"], "shape": s["shape"],
            "left": s["left"], "right": s["right"],
            "reasoning": reasoning,
        })

    if not summary:
        names = [belief_templates.get(b, {}).get("name", b) for b in held_beliefs]
        summary = ("Shaped by " + ", ".join(names) + ".") if names else "No strong worldview yet."

    return principles, summary, suggestions


# =========================================================
# POLITICAL VIEWS -- principles -> initial c["opinions"] stances
# =========================================================

# (stat_key, high_threshold, high_phrase, low_threshold, low_phrase) --
# thresholds are documented approximations, not researched benchmarks
# (this codebase's own convention for this kind of narrative-flavor
# gate elsewhere, e.g. mental_health_gen.py's base_rate comments) --
# only mentioned to the LLM when notably off from a calm baseline, so
# the prompt doesn't bloat listing every stat for an average community.
_ENVIRONMENT_STAT_GATES = [
    ("unemployment_rate", 15.0, "Unemployment is notably high in your community right now.",
                            5.0, "Unemployment is unusually low in your community right now."),
    ("violent_crime_rate", 5.0, "Violent crime is currently elevated in your community.",
                            None, None),
    ("cost_of_living_index", 1.15, "The cost of living is notably high where you live.",
                            0.9, "The cost of living is notably low where you live."),
    ("poverty_rate", 20.0, "Poverty is a visible, pressing issue in your community.",
                            None, None),
    ("homeless_pct", 6.0, "Homelessness is a visible issue in your community.",
                            None, None),
]


def _environment_context_lines(world):
    env = world.get("environment") or {}
    lines = []
    for key, high, high_phrase, low, low_phrase in _ENVIRONMENT_STAT_GATES:
        v = env.get(key)
        if v is None:
            continue
        if v >= high:
            lines.append(high_phrase)
        elif low is not None and v <= low:
            lines.append(low_phrase)
    return lines


async def _generate_political_views(c, principle_lines, mentality_summary, environment_lines):
    session = c.setdefault("_mentality_llm_session", {"history": []})
    topics_line = ", ".join(POLITICAL_TOPICS)
    environment_block = (
        "Real conditions where they live right now:\n" + "\n".join(f"- {l}" for l in environment_lines)
        if environment_lines else ""
    )

    prompt = f"""
{c.get('name', 'This character')}'s mentality: {mentality_summary}

Their principles:
{principle_lines}

{environment_block}

Based on this -- and, where relevant, the real conditions listed above
(lived reality can pull a stance in a real direction even when it cuts
against the abstract philosophy, e.g. someone philosophically pro-
policing living somewhere crime is actually low may not prioritize it
as urgently) -- give an initial political stance for each of these
topics, as a number from -1.0 (strongly against/negative) to 1.0
(strongly for/positive), 0.0 meaning genuinely undecided/neutral:
{topics_line}

Respond with STRICT JSON only:
{{"stances": {{"taxes": 0.0, "economy": 0.0, ... one entry per topic listed above}}}}
"""
    messages = [
        {"role": "system", "content": "You infer a character's initial political leanings from their stated principles and real local conditions for a life-simulation game. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    stances = parsed.get("stances")
    if not isinstance(stances, dict) or not stances:
        return None
    return stances


# Real conditions nudge the fallback too, not just the LLM prompt --
# same stat gates as _ENVIRONMENT_STAT_GATES, only the "high" direction
# (a calm/low environment is the assumed neutral default already).
_ENVIRONMENT_TOPIC_NUDGES = [
    ("unemployment_rate", "welfare", 0.3), ("unemployment_rate", "taxes", -0.1),
    ("violent_crime_rate", "crime", 0.3), ("violent_crime_rate", "police", 0.3), ("violent_crime_rate", "safety", 0.3),
    ("cost_of_living_index", "cost_of_living", 0.3), ("cost_of_living_index", "welfare", 0.2),
    ("poverty_rate", "welfare", 0.3), ("poverty_rate", "homelessness", 0.2),
    ("homeless_pct", "homelessness", 0.3),
]


def active_environment_topic_nudges(world):
    """Public helper for systems/politics.py::
    tick_environment_opinion_drift() -- which POLITICAL_TOPICS are
    currently pushed by real, notable environment conditions, and in
    which direction. Same gates/mapping the generation-time fallback
    above uses, exposed so the periodic drift tick doesn't need its own
    parallel copy."""
    env = world.get("environment") or {}
    active = []
    for key, high, _, _, _ in _ENVIRONMENT_STAT_GATES:
        v = env.get(key)
        if v is not None and v >= high:
            for stat_key, topic, delta in _ENVIRONMENT_TOPIC_NUDGES:
                if stat_key == key:
                    active.append((topic, delta))
    return active


def _fallback_political_views(mentality_tags, world=None):
    stances = {topic: 0.0 for topic in POLITICAL_TOPICS}
    for tag, topic, delta in _TAG_TOPIC_NUDGES:
        if tag in mentality_tags and topic in stances:
            stances[topic] = max(-1.0, min(1.0, stances[topic] + delta))
    env = (world or {}).get("environment") or {}
    for key, high, _, _, _ in _ENVIRONMENT_STAT_GATES:
        v = env.get(key)
        if v is not None and v >= high:
            for stat_key, topic, delta in _ENVIRONMENT_TOPIC_NUDGES:
                if stat_key == key and topic in stances:
                    stances[topic] = max(-1.0, min(1.0, stances[topic] + delta))
    return stances


def compile_political_views(c, world, mentality_tags):
    principles = c.get("principles", [])
    defs = world.get("definitions", {})

    principle_lines = "\n".join(
        f"- {_label_side(p.get('left'), defs, world)} {p['op']} "
        f"{_label_side(p.get('right'), defs, world)} ({p.get('reasoning', '')})"
        for p in principles
    ) or "(no strong principles formed yet)"

    mentality_summary = (c.get("mentality") or {}).get("summary", "")
    environment_lines = _environment_context_lines(world)

    raw = run_llm_call(
        _generate_political_views(c, principle_lines, mentality_summary, environment_lines),
        priority=PRIORITY_BACKGROUND,
    )
    if not raw:
        raw = _fallback_political_views(mentality_tags, world)

    stances = {}
    for topic in POLITICAL_TOPICS:
        try:
            v = float(raw.get(topic, 0.0))
        except (TypeError, ValueError):
            v = 0.0
        stances[topic] = max(-1.0, min(1.0, v))
    return stances
