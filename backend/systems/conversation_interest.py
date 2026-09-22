"""
conversation_interest.py

Per the user's explicit ask: when a NEW conversation starts (not each
follow-up message in an ongoing one), the listener's actual willingness to
engage right now is checked by the LLM -- topic, relationship, traits, mood,
and what they're already doing (a leisure activity, a chore, nothing) all
matter. A busy or uninterested listener can decline, with a real excuse
built from what they're actually doing, rather than always being available.

On acceptance, how INTO it the listener is also decides the conversation's
planned length (randomized within a range, not fixed) -- see
planned_length_ticks() below and systems/conversation_seating.py, which
uses it to prompt someone to sit or lean partway through a conversation
that runs long.
"""

import random

from systems.choice import choose

# How long (ticks) a conversation is expected to run, based on how willing
# the listener was -- randomized within the range at creation time, not a
# fixed number, so no two conversations play out on the same clock.
_LENGTH_RANGES_TICKS = {
    "engage_fully":   (600, 1800),   # 10-30 min -- genuinely into it
    "engage_briefly": (120, 420),    # 2-7 min -- polite, keeping it short
}
DEFAULT_ENGAGEMENT = "engage_briefly"

# Whether a conversation that runs past its own planned length prompts
# someone to suggest sitting/leaning at all -- randomized once per
# conversation, not guaranteed every time. See conversation_seating.py.
SEATING_SUGGESTION_CHANCE = 0.5


def _busy_description(c):
    act = c.get("activity") or {}
    act_type = act.get("type")
    if not act_type:
        return "not doing anything in particular"
    return (act.get("interaction") or act_type).replace("_", " ")


def _relationship_line(listener, other_id):
    rel = (listener.get("relationships") or {}).get(other_id) or {}
    if not rel:
        return "a stranger to them"
    labels = rel.get("labels") or []
    if (rel.get("friendship") or 0) >= 60:
        closeness = "someone close to them"
    elif (rel.get("familiarity") or 0) >= 20:
        closeness = "an acquaintance"
    else:
        closeness = "someone they barely know"
    return closeness + (f" ({', '.join(labels)})" if labels else "")


def check_conversation_interest(listener, world, topic, initiator_id):
    """Returns (accepted: bool, engagement: str|None, excuse: str|None).
    `engagement` is "engage_fully"/"engage_briefly" when accepted (feeds
    planned_length_ticks()); `excuse` is a real line the listener says
    instead, when declining."""
    busy = _busy_description(listener)
    options = [
        {"id": "engage_fully", "label": "happy to really get into this conversation"},
        {"id": "engage_briefly", "label": "willing to talk, but wants to keep it fairly short"},
        {"id": "decline_busy", "label": f"too caught up in {busy} to stop for this right now"},
        {"id": "decline_uninterested", "label": "not in the mood to talk about this particular topic right now"},
    ]
    context = (
        f"Someone wants to talk to you about \"{topic}\". You are currently {busy}. "
        f"They are {_relationship_line(listener, initiator_id)}. "
        "How willing are you to stop and engage in this conversation right now?"
    )
    picked = choose(listener, world, "willingness to have this conversation right now",
                    options, context=context)
    choice_id = picked["id"] if picked else DEFAULT_ENGAGEMENT

    if choice_id == "decline_busy":
        return False, None, f"Sorry, I'm right in the middle of {busy} -- can we talk later?"
    if choice_id == "decline_uninterested":
        return False, None, "I'd rather not get into that right now, honestly."
    return True, choice_id, None


def planned_length_ticks(engagement):
    lo, hi = _LENGTH_RANGES_TICKS.get(engagement, _LENGTH_RANGES_TICKS[DEFAULT_ENGAGEMENT])
    return random.randint(lo, hi)
