"""
systems/memory_consolidation.py

Two things, per the user's explicit ask:

1. Once per real hour, fold the past hour of a character's raw memory
   log (c["memories"] -- kept as the actual field name; see the note
   below on why this isn't a literal rename) into one condensed
   "highlights" summary, appended to a NEW, separate c["long_term_memory"]
   list. Skipped entirely while the character is asleep or incapacitated
   -- nothing worth aggregating happens then anyway.
2. Every ~3 real hours, the raw short-term log randomly forgets some of
   its own entries -- not the oldest, not the least important, just a
   real random subset, the same way real memory doesn't forget in a neat
   FIFO order.

Naming note: the user asked for this to literally be "short_term_memory"/
"long_term_memory". Renaming c["memories"] would mean touching every one
of its ~30+ existing readers/writers across this codebase (reflection.py,
stories.py, behavior_patterns.py, social_memory.py, context_builder.py,
the frontend Memory tab, ...) in one pass -- too large and risky to do
blind. c["memories"] stays as the real short-term store's field name;
c["long_term_memory"] is the new, literal piece.
"""

import random

CONSOLIDATION_INTERVAL_TICKS = 3600    # once per real hour
FORGET_INTERVAL_TICKS        = 10800   # every ~3 real hours
# Per the user's explicit ask ("remember somewhat longer... don't drop
# before X"): a memory is never even considered for forgetting until
# it's at least this old, regardless of its own drop_probability.
MIN_AGE_BEFORE_FORGETTING_TICKS = 3600
DEFAULT_DROP_PROBABILITY_PCT    = 40   # used for memories nobody stamped one onto

_UNCONSCIOUS_ACTIVITY_TYPES = {"sleep"}


def _is_unconscious(c):
    if (c.get("activity") or {}).get("type") in _UNCONSCIOUS_ACTIVITY_TYPES:
        return True
    if c.get("posture") == "incapacitated":
        return True
    return False


def maybe_consolidate_memories(c, world):
    if _is_unconscious(c):
        return

    tick = world.get("tick", 0)

    # Confirmed live bug: defaulting a never-before-seen character's
    # "last checked" to 0 made them read as hours overdue on the very
    # FIRST check after this feature shipped, immediately treating their
    # entire memory history as due for consolidation/forgetting all at
    # once. Seed silently on first sight instead (matching the same
    # "don't treat never-seen-before as overdue" fix already applied to
    # main.js's thought-bubble reload bug) -- the real interval only
    # starts counting from here.
    if "_last_memory_consolidation_tick" not in c:
        c["_last_memory_consolidation_tick"] = tick
        return

    last = c["_last_memory_consolidation_tick"]
    if tick - last < CONSOLIDATION_INTERVAL_TICKS:
        return
    c["_last_memory_consolidation_tick"] = tick

    memories = c.get("memories", [])
    window_start = tick - CONSOLIDATION_INTERVAL_TICKS
    in_window = [m for m in memories if m.get("tick", 0) >= window_start]
    if not in_window:
        return

    # Per the user's explicit ask: an off-grid trip's departure note
    # (systems/offgrid.py::_send_offgrid_immediate) and its arrival
    # summary (process_return) share a "trip:<id>" tag -- if BOTH halves
    # of the same trip landed in this window, merge them into one
    # concise, tag-like entry (a real, short LLM call) instead of
    # aggregating them separately as two half-stories about one outing.
    in_window, trip_merge_ids = _merge_trip_pairs(c, in_window)

    # Per the user's explicit ask: a memory's own "aggregate" flag
    # (defaults True -- most memory-writing call sites never set it and
    # get the original blur-into-a-summary behavior) decides its fate.
    # aggregate=True entries get folded into one condensed hourly
    # highlight (real detail lost, matching how a routine hour actually
    # gets remembered). aggregate=False entries (stamped by dialogue_
    # memory.py/social_memory.py for a salient moment) are important
    # enough to skip the blur entirely -- moved into long-term memory
    # completely unchanged instead.
    to_aggregate = [m for m in in_window if m.get("aggregate", True)]
    to_preserve  = [m for m in in_window if not m.get("aggregate", True)]

    long_term = c.setdefault("long_term_memory", [])
    processed_ids = {m["id"] for m in to_preserve if m.get("id")}
    for m in to_preserve:
        long_term.append(dict(m))

    if len(to_aggregate) >= 3:
        summary_text = _summarize(c, to_aggregate)
        if summary_text:
            long_term.append({
                "id":   f"ltm_{tick}",
                "text": summary_text,
                "tick": tick,
                "tags": ["highlights"],
            })
            processed_ids.update(m["id"] for m in to_aggregate if m.get("id"))
    # to_aggregate entries that DIDN'T end up in a summary (too few of
    # them this hour) stay in short-term untouched -- nothing to show
    # for removing them yet, so they simply wait for the next pass.

    # The merged trip entries above stand in for their two REAL raw
    # memories (departure + arrival) -- those need clearing out of
    # short-term regardless of which bucket the merged stand-in landed
    # in, since its own id is synthetic and wouldn't otherwise match
    # either real entry for removal.
    processed_ids |= trip_merge_ids

    # Everything processed this pass (folded into the summary, or moved
    # over as-is) now lives in long-term memory -- clear it out of the
    # raw short-term log rather than keeping it in both places.
    if processed_ids:
        c["memories"] = [m for m in memories if m.get("id") not in processed_ids]


def _merge_trip_pairs(c, in_window):
    """Groups memories sharing a "trip:<id>" tag; a pair (departure +
    arrival summary) gets condensed into one concise entry via
    _condense_trip() below and marked aggregate=False (it's already been
    condensed once -- blurring it further into the hour's generic
    summary would just lose the specific trip details again). A trip
    with only ONE half present in this window (the other already
    processed, or still to come) is left completely alone -- returned
    unchanged, nothing forced. Returns (new_list, consumed_real_ids)."""
    from collections import defaultdict

    by_trip = defaultdict(list)
    passthrough = []
    for m in in_window:
        trip_tag = next((t for t in (m.get("tags") or []) if str(t).startswith("trip:")), None)
        if trip_tag:
            by_trip[trip_tag].append(m)
        else:
            passthrough.append(m)

    consumed_ids = set()
    merged_entries = []
    for trip_tag, group in by_trip.items():
        if len(group) < 2:
            passthrough.extend(group)
            continue
        group.sort(key=lambda m: m.get("tick", 0))
        combined_text = _condense_trip(c, group)
        merged_entries.append({
            "id":         f"trip_merged_{trip_tag}",
            "text":       combined_text,
            "tick":       group[-1].get("tick", 0),
            "tags":       ["offgrid", trip_tag],
            "aggregate":  False,
            "importance": max(m.get("importance", 0.2) for m in group),
        })
        consumed_ids.update(m["id"] for m in group if m.get("id"))

    return passthrough + merged_entries, consumed_ids


def _condense_trip(c, group):
    """Per the user's explicit ask: have the LLM make this as concise as
    possible -- almost tag-like, just the essential facts -- rather than
    a full sentence combining both halves verbatim."""
    lines = [m.get("text", "") for m in group if m.get("text")]
    if not lines:
        return ""
    try:
        from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND
        from llm.llm_client import call_llm_safe
        messages = [
            {
                "role": "system",
                "content": (
                    "These two notes are about the same trip (leaving, and what "
                    "happened). Combine them into ONE extremely short, tag-like "
                    "phrase -- just the essential facts (where, how long, what "
                    "happened) -- no more than about 10 words, no full sentence."
                ),
            },
            {"role": "user", "content": "\n".join(lines)},
        ]
        raw = run_llm_call(call_llm_safe(messages, char_id=c.get("id")), priority=PRIORITY_BACKGROUND)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    except Exception:
        pass
    return " -- ".join(lines)


def _summarize(c, memories):
    lines = [m.get("text", "") for m in memories if m.get("text")]
    if not lines:
        return None
    try:
        from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND
        from llm.llm_client import call_llm_safe
        messages = [
            {
                "role": "system",
                "content": (
                    "Summarize the following hour of a character's raw memory "
                    "log into ONE short paragraph (2-3 sentences), first-person "
                    "past tense, capturing the real highlights -- skip trivial/"
                    "routine entries that don't add anything."
                ),
            },
            {"role": "user", "content": "\n".join(lines[:40])},
        ]
        raw = run_llm_call(call_llm_safe(messages, char_id=c.get("id")), priority=PRIORITY_BACKGROUND)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    except Exception:
        pass

    best = max(memories, key=lambda m: m.get("importance", 0))
    extra = len(memories) - 1
    return f"{best.get('text', '')}" + (f" (+{extra} other things that hour)" if extra > 0 else "")


def maybe_forget_short_term(c, world):
    """Per the user's explicit ask: real, randomized forgetting -- not an
    importance/age-based prune (brain/memory.py::prune_memories() already
    covers that as a hard cap). Each memory rolls independently against
    its OWN drop_probability (%) -- stamped at creation time by systems/
    memory_detail.py::compute_drop_probability(), lower for a salient
    moment or someone close, higher for routine chatter about a stranger
    -- rather than one flat rate applied to everything. A memory younger
    than MIN_AGE_BEFORE_FORGETTING_TICKS is never even rolled -- it
    hasn't had a chance to be remembered yet, let alone forgotten.

    Confirmed live bug (player report: a retired, mostly-asleep elderly
    character ended up with ZERO memories at all): unlike
    maybe_consolidate_memories() above, this had no _is_unconscious()
    skip -- it kept rolling drop chances against the SAME short-term log
    every ~3 real hours regardless of whether the character was awake to
    make any new memories in between. A character who sleeps through
    most real hours nets a steady drain with nothing to offset it,
    converging on an empty memory bank over enough real time. Forgetting
    should pause the same way remembering already does."""
    if _is_unconscious(c):
        return

    tick = world.get("tick", 0)

    # Same cold-start fix as maybe_consolidate_memories() above -- seed
    # silently on first sight rather than defaulting to 0 and reading as
    # hours overdue immediately.
    if "_last_memory_forget_tick" not in c:
        c["_last_memory_forget_tick"] = tick
        return

    last = c["_last_memory_forget_tick"]
    if tick - last < FORGET_INTERVAL_TICKS:
        return
    c["_last_memory_forget_tick"] = tick

    memories = c.get("memories", [])
    if not memories:
        return

    survivors = []
    for m in memories:
        age = tick - m.get("tick", tick)
        if age < MIN_AGE_BEFORE_FORGETTING_TICKS:
            survivors.append(m)
            continue
        drop_pct = m.get("drop_probability", DEFAULT_DROP_PROBABILITY_PCT)
        if random.random() * 100 < drop_pct:
            continue   # forgotten -- not necessarily in age/insertion order
        survivors.append(m)
    c["memories"] = survivors
