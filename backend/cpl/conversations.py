"""
cpl/conversations.py -- carries out the state machine (docs/cpl_implementation_plan.md sections 8-9).

    open_conversation(world, initiator_id, recipient_ids, channel, purpose, topic, ...)   CREATED -> PENDING / EXPIRED
    submit(world, conv, event)          one event through cpl/state_machine.py; its effects applied; returns the Result
    on_timer(world, entry)              a cpl:<conversation_id> timer (core/scheduler.py) -> a timer event

Every accepted transition bumps conv["state_version"]; every timer is stamped with the version it was set at, and
conv["timers"][kind] remembers the last one set: a timer replaced or cancelled since is stale and does nothing. Turn requests are published as
`cpl.turn_requested` (who should speak next and why); what answers them is the turn path (cpl/turns.py). Nothing here
polls: deadlines are timers, everything else is a reaction to an event.
"""

from core.clock import now_ts
from core.event_bus import emit

from cpl import policies, state_machine, store
from cpl.model.enums import ConvState, FINAL

OWNER = "cpl"


def _owner(conv):
    return f"{OWNER}:{conv['id']}"


def open_conversation(world, initiator_id, recipient_ids, *, channel, purpose, topic="", urgent=False,
                      reachable=True, legacy_id=None):
    now = now_ts(world)
    conv = store.create(world, initiator_id=initiator_id, recipient_ids=list(recipient_ids), channel=channel,
                        purpose=purpose, topic=topic, policy_key=policies.key(purpose, channel, urgent), now=now,
                        urgent=urgent, legacy_id=legacy_id)
    submit(world, conv, {"type": "open", "reachable": reachable})
    return conv


def submit(world, conv, event):
    now = now_ts(world)
    before = conv.get("state")
    res = state_machine.transition(conv, event, now)
    if not res.changed:
        return res
    conv["state_version"] = conv.get("state_version", 0) + 1
    conv["state"] = res.state.value if hasattr(res.state, "value") else res.state
    if conv["state"] == ConvState.ACTIVE.value and conv.get("started_at") is None:
        conv["started_at"] = now
    if before == ConvState.PENDING.value and conv["state"] == ConvState.ACTIVE.value:
        p = conv["participants"].get(event.get("by"))
        if p is not None and p.get("status") == "invited":
            p.update(status="active", joined_at=now, joined_at_seq=conv.get("seq", 0))
    if conv["state"] == ConvState.ACTIVE.value and before == ConvState.RESOLVING.value:
        conv["closed_by"] = []
        conv["winding_down"] = False
    if conv["state"] in {s.value for s in FINAL}:
        conv["reason"] = res.reason.value if hasattr(res.reason, "value") else res.reason
        conv["resolved_at"] = now
        conv["outcome"] = _outcome(world, conv, event)
    for eff in res.effects:
        _apply(world, conv, eff, event, now)
    if conv["state"] in {s.value for s in FINAL}:
        from cpl import shadow
        shadow.on_cpl_end(world, conv, event)
    return res


def _outcome(world, conv, event):
    settled = {rid: (world.get("cpl_requests") or {}).get(rid, {}).get("status")
               for rid in _all_requests(world, conv)}
    return {"reason": conv["reason"], "ended_by": event.get("by") or event.get("who"), "settled": settled,
            "agreements": list(conv["context"].get("agreements") or []),
            "disagreements": list(conv["context"].get("disagreements") or [])}


def _all_requests(world, conv):
    return [rid for rid, r in (world.get("cpl_requests") or {}).items() if r.get("conversation_id") == conv["id"]]


def _apply(world, conv, eff, event, now):
    from core import scheduler
    do = eff["do"]
    if do == "schedule":
        conv.setdefault("timers", {})[eff["kind"]] = conv["state_version"]
        scheduler.schedule_at(world, _owner(conv), eff["kind"], now + float(eff["in"]),
                              {"version": conv["state_version"]})
    elif do == "cancel":
        (conv.get("timers") or {}).pop(eff["kind"], None)
        scheduler.cancel(world, _owner(conv), eff["kind"])
    elif do == "set_floor":
        fl = conv.setdefault("floor", {})
        fl["holder"] = eff.get("holder")
        if "waiting_on" in eff:
            fl["waiting_on"] = eff["waiting_on"]
        fl["attempts"] = eff.get("attempts", 0)
    elif do == "participant_left":
        p = conv["participants"].get(eff["who"])
        if p is not None:
            p.update(status="left" if eff["reason"] != "unavailable" else "unavailable", left_at=now,
                     left_reason=eff["reason"])
        _publish(world, conv, "cpl.participant_left", event, who=eff["who"], reason=eff["reason"])
    elif do == "closed_by":
        if eff["who"] not in conv["closed_by"]:
            conv["closed_by"].append(eff["who"])
    elif do == "wind_down":
        conv["winding_down"] = True
    elif do == "settle_open":
        for rid in _all_requests(world, conv):
            req = world["cpl_requests"][rid]
            if req.get("status") in ("open", "negotiating"):
                store.set_request_status(world, rid, eff["status"], now, by=event.get("by"))
    elif do == "request_turn":
        _publish(world, conv, "cpl.turn_requested", event, who=eff["who"],
                 **{k: v for k, v in eff.items() if k not in ("do", "who")})
    elif do == "notify_initiator":
        _publish(world, conv, "cpl.initiator_notified", event, who=conv["initiator_id"], why=eff["why"])
    elif do == "publish":
        _publish(world, conv, eff["event"], event)


def _publish(world, conv, name, cause, **extra):
    emit(name, dict({"conversation_id": conv["id"], "state": conv["state"], "state_version": conv["state_version"],
                     "reason": conv.get("reason"), "participants": list(conv["participants"]),
                     "event_id": f"{conv['id']}:{conv['state_version']}:{name}:{extra.get('who', '')}",
                     "cause": cause.get("type")}, **extra))


def _thinking(world, cid):
    c = (world.get("characters") or {}).get(cid) if cid else None
    return bool(((c or {}).get("cognition") or {}).get("pending"))


def on_timer(world, entry):
    """A cpl:<conversation_id> timer: invite / reply / pause / close / idle / cap, or gc for a finished one."""
    cid = entry["owner"].split(":", 1)[1]
    conv = store.get(world, cid)
    if conv is None:
        return
    kind = entry["key"]
    if kind == "gc":                                  # finished an hour ago, and archived (cpl/archive.py)
        from cpl import archive
        archive.gc(world, cid)
        return
    waiting = (conv.get("floor") or {}).get("holder")
    if kind == "invite":
        waiting = next((p for p, d in conv["participants"].items() if d.get("status") == "invited"), None)
    submit(world, conv, {"type": "timer", "kind": kind, "version": (entry.get("payload") or {}).get("version"),
                         "holder_thinking": _thinking(world, waiting)})


def install():
    from core import scheduler
    scheduler.register(OWNER, on_timer)
    import cpl.archive  # noqa: F401 -- finished conversations go to the archive tables


install()
