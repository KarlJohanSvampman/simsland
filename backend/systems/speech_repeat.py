"""
systems/speech_repeat.py

A character says a given line to a given person once. Saying the exact same
thing to the same listener again within REPEAT_WINDOW_TICKS is dropped: no
bubble, no speech_log entry, no conversation message, nobody woken.

Why (live report, 2026-11-01): speech bubbles looked like they never went
away. They did expire after SPEECH_BUBBLE_TICKS, but a character whose action
kept failing re-ran the same decision every tick and re-said the same line
each time ("I need to get the kids to school, where's the school
schedule?" six times in ten ticks), and the busy listener answered every
fresh approach with the same stock excuse. The bubble was replaced by an
identical one before it could disappear.

Checked at every place a line is spoken: action_router.apply_speech /
apply_speech_to_group, expressions.express and incidental_speech.
fire_incidental. They all record what was said in c["speech_log"]
(newest last, capped at 20 entries), which is what this reads.
"""

import re

# 30 sim-minutes at TICK_RATE_SECONDS=1. Long enough to cover a decision or
# reply loop; short enough that a line can come up again later in the day.
REPEAT_WINDOW_TICKS = 1800

_TRAILING_PUNCT = re.compile(r"[\s.!?,;:…\-–—]+$")
_SPACES = re.compile(r"\s+")


def _normalize(text):
    """Case, spacing and trailing punctuation don't make a line new."""
    text = _SPACES.sub(" ", (text or "").strip().lower())
    return _TRAILING_PUNCT.sub("", text)


def is_repeat(c, world, utterance, target_id=None):
    """True if c already said this line to target_id (None = to nobody in
    particular) within the last REPEAT_WINDOW_TICKS."""
    line = _normalize(utterance)
    if not line:
        return False
    tick = world.get("tick", 0)
    for entry in reversed(c.get("speech_log") or []):
        if tick - entry.get("tick", 0) > REPEAT_WINDOW_TICKS:
            break                       # the log is in time order -- nothing older can match
        if entry.get("target") == target_id and _normalize(entry.get("utterance")) == line:
            return True
    return False
