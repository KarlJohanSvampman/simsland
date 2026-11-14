"""
cpl/lifecycle.py -- what happens to a conversation from outside it (docs/cpl_implementation_plan.md phase 2,
section 6.3): the only ways other systems change a conversation.

    interrupt(world, char_id, by, kind, priority="normal", can_resume=True)
                                    someone in a conversation is interrupted (the doorbell, an incoming call, the
                                    director's stop): the conversation carries the interruption, and each participant's
                                    next turn is asked what to do about it -- carry on, pause, or leave
    notify_unavailable(world, char_id, reason)
                                    someone can no longer talk (asleep, arrested, gone off the map): a two-person
                                    conversation ends (unavailable), a larger one carries on without them
    recover(world)                  once after a load: a turn whose model request was lost with the old process is
                                    asked again; conversations whose people can no longer talk are resolved
    summarize(conv, world)          the template summary (no model call): how long it has gone on, what is agreed
                                    and what is still open

Wired to existing events here (sleep, arrest, off-grid, the world loading); interruptions are called where they
happen (systems/doorbell.py, systems/action_router.py for a call, systems/directors_cut.py). CPL_MODE shadow or on.
"""

from core.event_bus import subscribe

from cpl import store
from cpl.model.enums import ConvState


def _live_for(world, char_id, states=None):
    out = []
    for conv in store.live(world, char_id):
        p = (conv.get("participants") or {}).get(char_id) or {}
        if p.get("status") in ("active", "invited") and (states is None or conv.get("state") in states):
            out.append(conv)
    return out


def _following(world):
    from cpl import shadow
    return shadow.active(world)


def interrupt(world, char_id, by=None, kind="interruption", priority="normal", can_resume=True, channel=None):
    """`channel`: only conversations on it (an incoming call interrupts the face-to-face ones); never one with `by`
    in it (the caller's own call goes on)."""
    if world is None or not _following(world):
        return []
    from core.clock import now_ts
    from cpl import conversations as CV
    hit = []
    for conv in _live_for(world, char_id, {ConvState.ACTIVE.value, ConvState.RESOLVING.value}):
        if (channel and conv.get("channel") != channel) or (by and by in (conv.get("participants") or {})):
            continue
        conv["interruption"] = {"who": char_id, "by": by, "kind": kind, "priority": priority,
                                "can_resume": can_resume, "since": now_ts(world)}
        CV.submit(world, conv, {"type": "interrupt", "by": by, "kind": kind})
        hit.append(conv["id"])
    return hit


def notify_unavailable(world, char_id, reason):
    if world is None or not _following(world):
        return []
    from cpl import conversations as CV
    ended = []
    for conv in _live_for(world, char_id):
        CV.submit(world, conv, {"type": "unavailable", "who": char_id, "reason": reason})
        ended.append(conv["id"])
    return ended


def _unavailable_reason(c):
    if not c or c.get("alive") is False:
        return "gone"
    if c.get("off_grid"):
        return "off_grid"
    if (c.get("activity") or {}).get("type") in ("sleep", "nap"):
        return "asleep"
    if (c.get("legal") or {}).get("status") == "jailed":
        return "jailed"
    return None


def recover(world):
    """After a load: re-ask lost turns, resolve what can't go on. Returns what it did."""
    if not _following(world):
        return {}
    from core.event_bus import emit
    chars = world.get("characters") or {}
    done = {"re_asked": [], "unavailable": []}
    for conv in list(store.live(world)):
        gone = [p for p, d in conv["participants"].items() if d.get("status") in ("active", "invited")
                and _unavailable_reason(chars.get(p))]
        if gone:
            notify_unavailable(world, gone[0], _unavailable_reason(chars.get(gone[0])))
            done["unavailable"].append(conv["id"])
            continue
        holder = (conv.get("floor") or {}).get("holder")
        hc = chars.get(holder) if holder else None
        if hc is not None and not ((hc.get("cognition") or {}).get("pending")):
            emit("cpl.turn_requested", {"conversation_id": conv["id"], "who": holder, "recovered": True,
                                        "state": conv["state"], "state_version": conv["state_version"]})
            done["re_asked"].append(conv["id"])
    return done


def summarize(conv, world=None):
    """A short template summary, kept up to date line by line (spec section 10.1; a model-written one is phase 5)."""
    lines = conv.get("lines", 0)
    parts = [f"{lines} line{'s' if lines != 1 else ''} so far" + (f" about {conv['topic']}" if conv.get("topic") else "")]
    reqs = (world or {}).get("cpl_requests") or {}
    settled = [r for r in reqs.values() if r.get("conversation_id") == conv.get("id")
               and r.get("status") not in ("open", "negotiating")]
    for r in settled[-3:]:
        parts.append(f"{r.get('action')}: {r.get('status')}")
    answered = [q for q in (conv.get("questions") or {}).values() if q.get("status") != "open"]
    if answered:
        parts.append(f"{len(answered)} question{'s' if len(answered) != 1 else ''} answered")
    return "; ".join(parts)


# ── wiring to existing events ────────────────────────────────────────────────────────────────────────────────────────

def _on_offgrid(data, world):
    notify_unavailable(world, data.get("character_id"), "off_grid")


def _on_arrested(data, world):
    notify_unavailable(world, data.get("character_id"), "arrested")


def _on_activity(data, world):
    if data.get("activity_type") in ("sleep", "nap"):
        notify_unavailable(world, data.get("character_id"), "asleep")


def _on_loaded(data, world):
    recover(world)


def _on_turn_requested(data, world):
    """CPL_MODE=on: a turn CPL asks for that nothing else would prompt -- a follow-up after no answer, a closing line,
    what to do about an interruption, one lost in a restart -- wakes that character (a line heard already wakes its
    listener through heard_speech)."""
    from cpl import shadow
    if world is None or not shadow.deciding(world):
        return
    if not (data.get("follow_up") or data.get("closing") or data.get("interrupted") or data.get("recovered")):
        return
    c = (world.get("characters") or {}).get(data.get("who"))
    if c is None:
        return
    from brain.cognition_scheduler import wake_character
    why = ("cpl_interrupted" if data.get("interrupted") else "cpl_closing" if data.get("closing")
           else "cpl_follow_up" if data.get("follow_up") else "cpl_turn")
    wake_character(c, world, why, {"conversation_id": data.get("conversation_id")})


subscribe("character.offgrid", _on_offgrid)
subscribe("character_arrested", _on_arrested)
subscribe("character_jailed", _on_arrested)
subscribe("activity_started", _on_activity)
subscribe("world.loaded", _on_loaded)
subscribe("cpl.turn_requested", _on_turn_requested)
