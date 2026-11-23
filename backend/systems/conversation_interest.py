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
    """Returns (accepted: bool, engagement: str, excuse: str|None).
    `engagement` is the choice: "engage_fully"/"engage_briefly" when accepted (feeds planned_length_ticks()),
    "decline_busy"/"decline_uninterested" when not; `excuse` is the listener's own reason, said instead, when declining.

    Asked for (2026-11-22): less rejecting, and a real reason when they do say no. The model is told that most people
    stop and answer someone they know, even if only to say what they're in the middle of; it gives the reason in the
    listener's own words; and it is told when they have already turned this person down lately. No session history
    (it used to carry the last answers along -- a run of "decline_uninterested" fed the next one), no reply cache, and
    no answer from the model is a brief yes, never a dice roll."""
    busy = _busy_description(listener)
    initiator = (world.get("characters") or {}).get(initiator_id) or {}
    who = (initiator.get("name") or "Someone")
    from systems.rejection import declined_recently
    n = declined_recently(listener, initiator_id, world)
    history = (f" You have already turned {who.split(' ')[0]} down {n} time{'s' if n != 1 else ''} today."
               if n else "")
    prompt = (
        f"You are {listener.get('name', 'someone')}. Traits: {', '.join(listener.get('traits') or []) or 'none listed'}.\n"
        f"{who} wants to talk to you about \"{topic}\". You are currently {busy}. "
        f"They are {_relationship_line(listener, initiator_id)}.{history}\n\n"
        "Most people stop and answer someone they know, at least briefly -- even busy, they say what they're in the "
        "middle of. Only turn them down for a real reason, and say what it is.\n\n"
        "Reply with exactly two lines:\n"
        "CHOICE: engage_fully | engage_briefly | decline_busy | decline_uninterested\n"
        "REASON: what you say to them, in your own words (one short sentence; for a decline, the real reason)"
    )
    choice, reason = _ask(listener, world, prompt)
    if choice is None:
        return True, DEFAULT_ENGAGEMENT, None
    if choice == "decline_busy":
        return False, choice, reason or f"Sorry, I'm right in the middle of {busy} -- can we talk later?"
    if choice == "decline_uninterested":
        return False, choice, reason or "I'd rather not get into that right now, honestly."
    return True, choice, None


_CHOICES = ("engage_fully", "engage_briefly", "decline_busy", "decline_uninterested")


def _ask(listener, world, prompt):
    """(choice, reason) from the model, or (None, None) when it gave nothing usable."""
    try:
        from llm.llm_gate import run_llm_call, gate_failed
        from llm.llm_client import call_llm_safe
        raw = run_llm_call(call_llm_safe(
            [{"role": "system", "content": "You decide, in character, whether to stop and talk. Two lines only."},
             {"role": "user", "content": prompt}],
            char_id=listener.get("id"), max_tokens=60, use_cache=False))
        if gate_failed(raw) or not isinstance(raw, str):
            return None, None
    except Exception:                                     # noqa: BLE001
        return None, None
    choice, reason = None, None
    for line in raw.splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip().upper(), val.strip().strip('"')
        if key == "CHOICE":
            v = val.lower().replace(" ", "_")
            choice = next((c for c in _CHOICES if c in v), None)
        elif key == "REASON" and val:
            reason = val[:200]
    if choice is None:                                    # a bare id, as the old prompt asked for
        low = raw.lower()
        choice = next((c for c in _CHOICES if c in low), None)
    return choice, reason


def planned_length_ticks(engagement):
    lo, hi = _LENGTH_RANGES_TICKS.get(engagement, _LENGTH_RANGES_TICKS[DEFAULT_ENGAGEMENT])
    return random.randint(lo, hi)
