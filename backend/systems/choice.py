"""
systems/choice.py

Generic "have the character pick one option from a list" utility --
usable for anything shaped like a choice (which clothing item to wear,
which restaurant to call, which time slot to book, ...), not tied to any
one activity. Built for systems/activities.py's upcoming "get_dressed"
interaction, but deliberately not clothing-specific.

Call from normal tick processing only (systems/activities.py's
complete_activity(), off-grid resolution, etc.) -- like every other real
LLM call in this codebase (see offgrid_narrative.py), this blocks the
calling thread via llm.llm_gate.run_llm_call() while waiting on the
model. That's fine from a tick already running on sim_loop.py's
dedicated tick executor thread; it would NOT be fine from inside a
synchronous API request handler holding world_lock() (see
character_gen.py's bio-generation decision for why that path stays
deterministic instead).
"""

import random


def choose(c, world, choice_type, options, occasion=None, max_num_options=None):
    """
    choice_type: short label for what's being chosen ("clothing item",
    "restaurant", "time slot", ...) -- shapes the LLM prompt only, no
    other behavioral effect.

    options: list of dicts, each with at least {"id", "label"}. "tags"
    (list of strings), if present, is used for occasion-based narrowing.
    Any other keys ride along untouched -- the caller gets back the
    exact dict it passed in, not a stripped-down copy.

    occasion: optional string describing WHY this choice is being made
    ("cold weather", "job interview", "casual weekend"). Options tagged
    with a matching tag are preferred (narrows the pool passed to the
    LLM); if nothing matches, the full pool is used instead of returning
    nothing. The occasion text is always given to the LLM regardless of
    whether the tag filter narrowed anything, so it can use real
    judgment ("seems appropriate") rather than being limited to exact
    tag matches.

    max_num_options: optional cap on how many options are actually shown
    to the LLM (randomly sampled from the occasion-filtered pool) --
    keeps the prompt bounded for a large closet/catalog.

    Returns the chosen option dict, or None if `options` is empty.
    Falls back to a random pick from the (filtered) pool if the LLM is
    unreachable or its answer doesn't resolve to a real option id --
    "no choice at all" isn't a sensible failure mode for something like
    getting dressed, unlike offgrid_narrative.py's narration calls
    (which fall back to a different, still-good procedural generator on
    failure, so returning None there is fine).
    """
    if not options:
        return None

    pool = options
    if occasion:
        tagged = [o for o in options if occasion in (o.get("tags") or [])]
        if tagged:
            pool = tagged

    if max_num_options and len(pool) > max_num_options:
        pool = random.sample(pool, max_num_options)

    if len(pool) == 1:
        return pool[0]

    try:
        from llm.llm_gate import run_llm_call
        from llm.choice_narration import generate_choice
        picked_id = run_llm_call(generate_choice(c, world, choice_type, pool, occasion))
    except Exception:
        picked_id = None

    if picked_id:
        match = next((o for o in pool if str(o["id"]) == str(picked_id)), None)
        if match:
            return match

    return random.choice(pool)


# NOTE: validation-seeking used to live here as an inline
# maybe_seek_validation() called right after a choice. Superseded by
# systems/validation.py's queue-based design (queue_choice_for_validation
# + maybe_seek_validation_from_queue/check_validation_refresh, run on a
# cadence from brain/agent_loop.py) -- a choice now waits in
# c["validation_queue"] with an expiration instead of firing a
# validation-seek immediately inline. See systems/dressing.py for the
# current call site.
