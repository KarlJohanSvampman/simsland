"""
cpl/adapters/events.py -- World Event Adapter: a delivered line and everything it does
(docs/cpl_implementation_plan.md section 7; C12: the per-line side effects of apply_speech move here unchanged).

    on_delivered(fn)              fn(world, delivery) runs for every line delivered to a listener, synchronously and
                                  in registration order (the order they ran in inside apply_speech: ledger, memory,
                                  reactions, analysis depend on each other's writes and on the shared random stream)
    deliver(world, delivery)      runs them, then emits `cpl.message_delivered` on the event bus for anything that only
                                  needs to know (logs, replay, debug views)

delivery: {"speaker", "listener", "conv", "utterance", "speech_act", "topic", "tick", "medium", "volume", "speech",
           "conversation_type", "target_id"} -- the live dicts; a subscriber reads what it needs.
"""

_subscribers = []


def on_delivered(fn):
    if fn not in _subscribers:
        _subscribers.append(fn)
    return fn


def subscribers():
    return list(_subscribers)


def deliver(world, d):
    for fn in _subscribers:
        fn(world, d)
    from core.event_bus import emit
    emit("cpl.message_delivered", {"conversation_id": (d.get("conv") or {}).get("id"),
                                   "speaker_id": d["speaker"]["id"], "recipient_id": d["listener"]["id"],
                                   "speech_act": d.get("speech_act"), "medium": d.get("medium"),
                                   "line": len((d.get("conv") or {}).get("history", [])) - 1})
