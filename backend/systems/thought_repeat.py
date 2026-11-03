"""
systems/thought_repeat.py

A thought is had once. When a character's decision produces the same thought it
already had recently, it is not stored again; instead the character notices they
can't think of anything else -- one "fixation" thought, once -- and whatever they
are focused on gets more pressing each time it happens.

Why (live report, 2026-11-01): Kathleen Okafor's short-term memory filled up with
"I head toward towards the kitchen, to grab a glass of water." dozens of times while
she stood still -- every failed move re-woke her, she decided the same thing again,
and every decision's thought was stored as a new memory
(brain/agent_loop.py::process_decision).

The extra pressure is kept as the focused intention's "fixation_boost", which
brain/intentions.py adds in final_priority() and carries across add_intention()
refreshes (a refresh otherwise recomputes "priority" from scratch and would erase a
direct bump).
"""

import re

from systems.speech_repeat import _normalize

REPEAT_WINDOW_TICKS = 1800      # 30 sim-minutes, same window as a repeated line of speech
FIXATION_STEP = 10              # priority points added per repeat
FIXATION_MAX = 50               # never more than this on top of an intention's own priority


def _is_thought(memory):
    tags = memory.get("tags") or []
    return "thought" in tags and "fixation" not in tags


def _recently_thought(c, world, text):
    line = _normalize(text)
    if not line:
        return False
    tick = world.get("tick", 0)
    for memory in reversed(c.get("memories") or []):
        if tick - memory.get("tick", 0) > REPEAT_WINDOW_TICKS:
            continue                    # short-term memories aren't strictly time-ordered; keep scanning
        if _is_thought(memory) and _normalize(memory.get("text")) == line:
            return True
    return False


def _focused_intention(c):
    """The intention the character is mainly focused on: the one brain/situations
    selected this tick, else the top of the priority order."""
    intentions = c.get("active_intentions") or []
    if not intentions:
        return None
    selected = ((c.get("selected_situation") or {}).get("situations") or [None])[0]
    if selected:
        match = next((i for i in intentions if i.get("type") == selected.get("type")), None)
        if match:
            return match
    from brain.intentions import final_priority
    return max(intentions, key=lambda i: final_priority(i, c))


_SECOND_TO_FIRST = [
    (re.compile(r"\byou're\b", re.I), "I'm"),
    (re.compile(r"\byou've\b", re.I), "I've"),
    (re.compile(r"\byou'll\b", re.I), "I'll"),
    (re.compile(r"\byou'd\b", re.I), "I'd"),
    (re.compile(r"\byourself\b", re.I), "myself"),
    (re.compile(r"\byours\b", re.I), "mine"),
    (re.compile(r"\byour\b", re.I), "my"),
    (re.compile(r"\byou\b", re.I), "I"),
]


def _first_person(text):
    """Intention reasons are written to the character ("You still need to get the kids
    to school", "Susan lives close by and you feel like playing") -- a thought is the
    character's own words."""
    for pattern, repl in _SECOND_TO_FIRST:
        text = pattern.sub(repl, text)
    return text


def _subject(intention, thought):
    """What they can't stop thinking about, in their own (first-person) words."""
    if intention:
        reason = (intention.get("reason") or "").strip().rstrip(". ")
        if reason:
            return _first_person(reason)
        kind = str(intention.get("type", "")).replace("expectation:", "").replace("lt_need:", "").replace("_", " ")
        if kind:
            return f"I need to {kind}"
    return thought.rstrip(". ")


def handle_thought(c, world, thought):
    """Call before storing a decision's thought. Returns True if it should be
    stored as usual, False if it is a repeat (already handled here)."""
    if not _recently_thought(c, world, thought):
        return True

    tick = world.get("tick", 0)
    intention = _focused_intention(c)
    if intention is not None:
        intention["fixation_boost"] = min(FIXATION_MAX, (intention.get("fixation_boost") or 0) + FIXATION_STEP)

    # The fixation thought itself: once per thing they are stuck on (the focused
    # intention -- several different repeated thoughts can all be about it), not
    # once per repeat or per repeated thought.
    key = ("intention", intention.get("type")) if intention else ("thought", _normalize(thought))
    fixation = c.get("_fixation") or {}
    if tuple(fixation.get("key") or ()) != key or tick - fixation.get("tick", 0) > REPEAT_WINDOW_TICKS:
        from brain.memory import store_memory
        store_memory(
            c,
            text=f"I can't seem to think of anything else -- {_subject(intention, thought)}.",
            tags=["thought", "fixation"],
            importance=0.5,
            tick=tick,
            source="internal",
        )
        c["_fixation"] = {"key": list(key), "tick": tick}
    return False
