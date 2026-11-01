"""
systems/scripted_conversations.py

Real playback of a systems/events.py remote shared_event's pre-generated
script (llm/scripted_conversation.py) -- a call plays out with short,
realistic pauses between lines inside a real phone_call activity; an
SMS exchange plays out with real minutes-scale gaps and a separate,
independently-randomized "time until the recipient checks their phone"
delay, WITHOUT occupying either character's activity between messages
(they keep doing whatever else they'd otherwise be doing).

world["scripted_conversations"][conv_id] = {
    "conv_id", "medium": "call"|"text", "participants": [a_id, b_id],
    "script": [{"speaker_id","line"}, ...], "next_idx", "next_tick",
    "started_tick", "tier", "severity", "subcategory",
}

A script is written before any of this starts: request_script() records the request in world["pending_scripts"] and
tick_pending_scripts() hands it to systems/bg_llm (a model call off the tick thread), then begins the call/text when the
answer is taken. If the model gives nothing usable three times, or the people can no longer talk (asleep, jailed, no
phone), the exchange simply doesn't happen -- no stock lines pretending it did.
"""

import random

# Real, live-feeling pauses between spoken lines in a call.
CALL_LINE_DELAY_RANGE = (5, 30)  # seconds

# Real minutes-scale gap before the NEXT line is even "sent" (the
# speaking character's own reply pacing).
SMS_SEND_DELAY_RANGE_MIN = (2, 20)  # minutes

# Real, separate "time until the recipient checks their phone" delay --
# skewed toward checking soon, MORE skewed the longer the conversation
# has already been running (a live exchange pulls attention harder than
# a single stray text).
SMS_CHECK_DELAY_RANGE_MIN = (1, 45)  # minutes


# A script that hasn't come back (or been given up on) after this long is dropped: the moment has passed.
SCRIPT_WAIT_TICKS = 2 * 3600
MAX_SCRIPT_ATTEMPTS = 3


def request_script(world, event, a, b, tier, severity, subcategory):
    """Record that this remote event needs its script written. Plain data only: the request goes to a worker."""
    from llm.scripted_conversation import build_script_request
    world.setdefault("pending_scripts", {})[event["id"]] = {
        "event_id": event["id"], "tier": tier, "severity": severity, "subcategory": subcategory,
        "req": build_script_request(world, a, b, tier, severity, event.get("medium") or "call", subcategory),
        "attempts": 0, "requested_tick": world["tick"],
    }


def _events_named(world, event_id):
    return [e for key in ("events", "shared_events") for e in world.get(key, []) if e.get("id") == event_id]


def _give_up(world, pending, event_id, why):
    p = pending.pop(event_id, None) or {}
    req = p.get("req") or {}
    verb = "call" if req.get("medium") == "call" else "text"
    for e in _events_named(world, event_id):
        e["text"] = f"{req.get('a_name', 'Someone')} tried to {verb} {req.get('b_name', 'someone')}, but it went nowhere."
        e["script_failed"] = why
    print(f"[scripted_conversations] {event_id}: no script ({why})")


def tick_pending_scripts(world):
    """Collect scripts that have been written and start their call/text."""
    pending = world.get("pending_scripts")
    if not pending:
        return
    from systems import bg_llm
    from llm.scripted_conversation import write_script, script_from_lines
    from systems.events import is_reachable
    chars = world.get("characters", {})
    for event_id in list(pending):
        p = pending[event_id]
        req = p["req"]
        a, b = chars.get(req["a_id"]), chars.get(req["b_id"])
        if not a or not b:
            _give_up(world, pending, event_id, "participant gone")
            continue
        if world["tick"] - p["requested_tick"] > SCRIPT_WAIT_TICKS:
            _give_up(world, pending, event_id, "took too long")
            continue
        key = f"script:{event_id}:{p['attempts']}"
        bg_llm.submit(key, write_script, req)        # no-op while this attempt is still running
        ready, lines = bg_llm.take(key)
        if not ready:
            continue
        script = script_from_lines(req, lines)
        if not script:
            p["attempts"] += 1
            if p["attempts"] >= MAX_SCRIPT_ATTEMPTS:
                _give_up(world, pending, event_id, "the model gave nothing usable")
            continue
        if not (is_reachable(a) and is_reachable(b)):
            _give_up(world, pending, event_id, "they could no longer talk")
            continue
        begin = begin_scripted_call if req["medium"] == "call" else begin_scripted_sms
        conv = begin(world, a, b, script, p["tier"], p["severity"], p["subcategory"])
        for e in _events_named(world, event_id):
            e["conv_id"] = conv["id"]
        del pending[event_id]


def begin_scripted_call(world, a, b, script, tier, severity=None, subcategory=None):
    from brain.conversations import get_or_create_conversation
    from systems.action_router import _scaffold
    conv = get_or_create_conversation(world, [a["id"], b["id"]], medium="call")
    duration = max(60, len(script) * CALL_LINE_DELAY_RANGE[1])
    a["activity"] = _scaffold(a, world, "phone_call", target_id=b["id"],
                               interaction="phone_call", duration=duration)
    b["activity"] = _scaffold(b, world, "phone_call", target_id=a["id"],
                               interaction="phone_call", duration=duration)
    _register(world, conv["id"], "call", a["id"], b["id"], script, tier, severity, subcategory)
    return conv


def begin_scripted_sms(world, a, b, script, tier, severity=None, subcategory=None):
    from brain.conversations import get_or_create_conversation
    conv = get_or_create_conversation(world, [a["id"], b["id"]], medium="text")
    # Deliberately does NOT touch either character's activity.
    _register(world, conv["id"], "text", a["id"], b["id"], script, tier, severity, subcategory)
    return conv


def _register(world, conv_id, medium, a_id, b_id, script, tier, severity, subcategory):
    first_delay = (
        random.randint(*CALL_LINE_DELAY_RANGE) if medium == "call"
        else _sms_turn_delay_ticks(0)
    )
    entry = {
        "conv_id": conv_id, "medium": medium, "participants": [a_id, b_id],
        "script": script, "next_idx": 0, "next_tick": world["tick"] + first_delay,
        "started_tick": world["tick"],
        "tier": tier, "severity": severity, "subcategory": subcategory,
    }
    world.setdefault("scripted_conversations", {})[conv_id] = entry


def _sms_turn_delay_ticks(turns_so_far):
    """Combined send-delay + check-delay for one SMS turn -- functionally
    equivalent to waiting for each separately (nothing else reads the
    intermediate "sent but not yet seen" state), but keeps both real,
    independently-randomized components."""
    send_lo, send_hi = SMS_SEND_DELAY_RANGE_MIN
    send_minutes = random.uniform(send_lo, send_hi)

    check_lo, check_hi = SMS_CHECK_DELAY_RANGE_MIN
    # Skewed toward checking soon; the exponent grows with how long the
    # conversation's already run, sharpening the skew toward short delays.
    k = 1.0 + min(turns_so_far, 6) * 0.5
    frac = random.random() ** k
    check_minutes = check_lo + frac * (check_hi - check_lo)

    return int((send_minutes + check_minutes) * 60)


def sms_check_delay_minutes(turns_so_far):
    """Exposed separately (not just via _sms_turn_delay_ticks) purely so
    the check-delay's own skew can be tested/verified in isolation."""
    check_lo, check_hi = SMS_CHECK_DELAY_RANGE_MIN
    k = 1.0 + min(turns_so_far, 6) * 0.5
    frac = random.random() ** k
    return check_lo + frac * (check_hi - check_lo)


def _end_conversation(world, entry):
    from systems.events import _apply_negative_consequence, _apply_positive_consequence, _NEGATIVE_TIERS
    characters = world.get("characters", {})
    a_id, b_id = entry["participants"]
    a, b = characters.get(a_id), characters.get(b_id)

    if entry["medium"] == "call":
        for c in (a, b):
            # Confirmed live bug (froze the entire tick loop): c["activity"]
            # can be explicitly None (not just absent), and dict.get()'s
            # default only covers a MISSING key, not a present key whose
            # value already IS None -- c.get("activity", {}).get(...) still
            # raised AttributeError on None.get(...) every single tick,
            # uncaught, before update_world_tick()/save_world() ever ran
            # (main.py::_run_tick_and_persist calls tick() before either),
            # so the whole simulation silently stopped persisting/advancing.
            if c and (c.get("activity") or {}).get("interaction") == "phone_call":
                c["activity"] = {}

    tier = entry["tier"]
    subcategory = entry.get("subcategory")
    sub_type = subcategory.get("subcategory") if subcategory else None
    if a and b:
        if tier in _NEGATIVE_TIERS:
            if sub_type == "sympathy":
                _apply_positive_consequence(a, b, world, subcategory)
            else:
                _apply_negative_consequence(a, b, world, tier, entry.get("severity"), subcategory)
        elif tier == "pleasant" and subcategory:
            _apply_positive_consequence(a, b, world, subcategory)

    world.get("scripted_conversations", {}).pop(entry["conv_id"], None)


def tick_scripted_conversations(world):
    """Called from sim_loop.py on a frequent-enough cadence to make
    short call-pacing feel real."""
    from brain.conversations import add_message
    tick_pending_scripts(world)
    scripted = world.get("scripted_conversations")
    if not scripted:
        return
    tick = world["tick"]
    conv_lookup = world.get("conversations", {})

    for conv_id in list(scripted.keys()):
        entry = scripted.get(conv_id)
        if not entry or tick < entry["next_tick"]:
            continue

        conv = conv_lookup.get(conv_id)
        script = entry["script"]
        idx = entry["next_idx"]
        if idx >= len(script) or not conv:
            _end_conversation(world, entry)
            continue

        turn = script[idx]
        topic = (entry.get("subcategory") or {}).get("subcategory") or entry["tier"]
        add_message(world, conv, turn["speaker_id"], turn["line"], "smalltalk", topic, tick)

        entry["next_idx"] += 1
        if entry["next_idx"] >= len(script):
            _end_conversation(world, entry)
            continue

        if entry["medium"] == "call":
            entry["next_tick"] = tick + random.randint(*CALL_LINE_DELAY_RANGE)
        else:
            entry["next_tick"] = tick + _sms_turn_delay_ticks(entry["next_idx"])
