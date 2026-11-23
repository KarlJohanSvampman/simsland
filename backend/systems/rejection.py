"""
systems/rejection.py -- being turned down when you try to talk to someone.

Asked for (2026-11-22): turning people down should be rarer and come with a real reason; someone told "I'm busy" should
naturally ask what they're doing (or offer a hand); being turned down by the same person again and again should be
noticed as a pattern; and when it happens, the one turned down should remember whether this person turned them down
last time too.

    on_rejected(world, initiator, rejector, excuse, kind)
        kind: "busy" | "uninterested" | "later" | "walked_off"
        - remembers it (a memory tagged "rejected", about the rejector) and keeps a per-person record
          (initiator["_rejections"][rejector_id], which outlives memory pruning)
        - looks back: did this person turn them down last time too?
        - a pattern: ROUTINE_COUNT or more in ROUTINE_WINDOW_S becomes a memory of its own ("X keeps turning me down")
        - wakes the initiator ("conversation_declined") with the excuse and a nudge that fits it -- busy: ask what
          they're doing, offer a hand, or try later

    declined_recently(listener, initiator_id, world)
        how many times the listener has turned this person down lately (systems/conversation_interest.py tells the
        model, so a refusal isn't the reflex every time)

Called from systems/action_router.py (the willingness check said no) and on cpl.initiator_notified (the listener's own
turn declined, deferred, or walked off).
"""

from core.event_bus import subscribe

ROUTINE_COUNT = 3                  # turned down this many times ...
ROUTINE_WINDOW_S = 24 * 3600       # ... within a sim-day is a pattern
RECORD_KEPT = 12

_HINTS = {
    "busy": "You could ask what they're busy with, offer to help, or try again later.",
    "uninterested": "You could ask what's on their mind, or leave it for now.",
    "later": "They said not now -- you could ask when would suit them.",
    "walked_off": "They walked away without answering.",
}


def _now(world):
    from core.clock import now_ts
    return now_ts(world)


def _ago(seconds):
    m = int(seconds // 60)
    if m < 2:
        return "just now"
    if m < 60:
        return f"{m} minutes ago"
    h = m // 60
    return f"{h} hour{'s' if h != 1 else ''} ago" if h < 24 else f"{h // 24} day{'s' if h >= 48 else ''} ago"


def previous_rejection(c, rejector_id):
    """The last time this person turned c down, from c's own record, else c's memories. None if never."""
    rec = (c.get("_rejections") or {}).get(rejector_id) or []
    if rec:
        return dict(rec[-1])
    for m in reversed(c.get("memories") or []):
        if "rejected" in (m.get("tags") or []) and rejector_id in (m.get("people") or []):
            return {"ts": m.get("world_ts") or m.get("ts"), "tick": m.get("tick"), "excuse": None, "from_memory": True,
                    "text": m.get("text")}
    return None


def declined_recently(listener, initiator_id, world):
    t = _now(world)
    return sum(1 for r in (listener.get("_declined") or {}).get(initiator_id) or [] if t - r < ROUTINE_WINDOW_S)


def on_rejected(world, initiator, rejector, excuse=None, kind="busy"):
    if not initiator or not rejector or initiator.get("id") == rejector.get("id"):
        return None
    t, tick = _now(world), world.get("tick", 0)
    rid, name = rejector["id"], (rejector.get("name") or "they").split(" ")[0]
    rec = initiator.setdefault("_rejections", {}).setdefault(rid, [])
    if rec and rec[-1].get("tick") == tick:
        return None                                   # the same refusal reported twice (willingness check + CPL)
    before = previous_rejection(initiator, rid)
    rec.append({"ts": t, "tick": tick, "kind": kind, "excuse": excuse})
    del rec[:-RECORD_KEPT]
    rejector.setdefault("_declined", {}).setdefault(initiator["id"], []).append(t)
    del rejector["_declined"][initiator["id"]][:-RECORD_KEPT]

    recent = [r for r in rec if t - (r.get("ts") or t) < ROUTINE_WINDOW_S]
    routine = len(recent) >= ROUTINE_COUNT

    from brain.memory import store_memory
    said = f': "{excuse}"' if excuse else ""
    store_memory(initiator, f"I tried to talk to {name}, but they turned me down{said}.", importance=0.4,
                 tags=["rejected", "conversation"], people=[rid], emotional_impact=-0.15, source="conversation",
                 tick=tick)
    if routine and not initiator.setdefault("_rejection_patterns", {}).get(rid, 0) >= recent[0].get("tick", 0):
        store_memory(initiator, f"{name} keeps turning me down when I try to talk to them -- {len(recent)} times "
                                f"today. It's becoming a pattern.", importance=0.7, tags=["rejected", "pattern"],
                     people=[rid], emotional_impact=-0.3, source="conversation", tick=tick)
        initiator["_rejection_patterns"][rid] = tick

    hint = _HINTS.get(kind, "")
    if before and before.get("ts"):
        hint += f" Last time you tried to talk to {name} ({_ago(t - before['ts'])}), they turned you down too."
    elif before:
        hint += f" {name} turned you down last time too."
    if routine:
        hint += f" That's {len(recent)} times today -- it's becoming a pattern."
    from brain.cognition_scheduler import wake_character
    wake_character(initiator, world, "conversation_declined",
                   {"listener_name": name, "excuse": excuse or "(no reason given)", "hint": hint.strip()})
    return {"previous": before, "count_today": len(recent), "routine": routine}


def _on_initiator_notified(data, world):
    why = data.get("why")
    kind = {"declined": "uninterested", "later": "later", "walked_off": "walked_off"}.get(why)
    if not kind:
        return
    from cpl import store
    conv = store.get(world, data.get("conversation_id"))
    chars = world.get("characters") or {}
    initiator = chars.get(data.get("who"))
    if not conv or not initiator:
        return
    others = [p for p in (conv.get("members") or {}) if p != initiator["id"]]
    rejector = chars.get(others[0]) if len(others) == 1 else None
    if not rejector:
        return
    said = [m for m in conv.get("messages") or [] if m.get("sender_id") == rejector["id"] and m.get("content")]
    on_rejected(world, initiator, rejector, said[-1]["content"] if said else None, kind)


subscribe("cpl.initiator_notified", _on_initiator_notified)
