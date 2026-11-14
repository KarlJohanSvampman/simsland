"""
cpl/state_machine.py -- the conversation lifecycle as a pure transition table (docs/cpl_implementation_plan.md
section 8).

    transition(conv, event, now) -> Result(state, reason, effects)

`conv` is the stored conversation (plain dict; only read here), `event` a dict with a "type", `now` the sim time.
Nothing here touches the world: the effects are data that cpl/conversations.py carries out --

    {"do": "schedule", "kind": k, "in": seconds}    a timer owned by the conversation (core/scheduler.py), stamped
                                                    with the state_version it was set at (conv["timers"][kind]):
                                                    one replaced or cancelled since is stale and a no-op
    {"do": "cancel", "kind": k}
    {"do": "request_turn", "who": cid}              that participant is asked for their turn
    {"do": "set_floor", "holder": cid | None}
    {"do": "wind_down"}                             the next turn prompt says "wrap up"
    {"do": "participant_left", "who": cid, "reason": r}
    {"do": "settle_open", "status": s}              the open requests of this conversation take this status
    {"do": "publish", "event": name}                a cpl.* event (cpl/adapters/events.py)
    {"do": "notify_initiator", "why": w}

A rejected event (an illegal transition, a stale timer) returns the state unchanged, no effects, and
`rejected` set to why. Transitions out of RESOLVED / EXPIRED are always rejected.

Events:
    open         {reachable}                                        CREATED -> PENDING | EXPIRED(unavailable)
    turn         {by, control?, leave_reason?, requires_response?, raises_item?, settles_all?, wrap_up?}
    timer        {kind: invite|reply|pause|close, version, holder_thinking?, holder_busy?}
    interrupt    {by?, kind?}
    unavailable  {who}
    escalation   {}
    force_resolve {reason}                                         any live -> RESOLVED (EXPIRED if never started)
"""

from dataclasses import dataclass, field

from cpl import policies
from cpl.model.enums import ConvState as S, ResolutionReason as R, FINAL


@dataclass
class Result:
    state: str
    reason: str | None = None
    effects: list = field(default_factory=list)
    rejected: str | None = None

    @property
    def changed(self):
        return self.rejected is None


def _policy(conv):
    return policies.from_key(conv.get("policy_key"))


def _others(conv, who):
    return [p for p, d in (conv.get("participants") or {}).items() if p != who and d.get("status") in ("active",
                                                                                                       "invited")]


def _active(conv):
    return [p for p, d in (conv.get("participants") or {}).items() if d.get("status") == "active"]


def _stale(conv, event):
    """A timer is current only if it is the last one set for its kind (conv["timers"][kind] = the version then)."""
    return event.get("version") is None or event.get("version") != (conv.get("timers") or {}).get(event.get("kind"))


def _reject(conv, why):
    return Result(conv.get("state"), conv.get("reason"), [], rejected=why)


def _end(state, reason, extra=()):
    eff = [{"do": "cancel", "kind": k} for k in ("invite", "reply", "pause", "close")]
    eff += list(extra)
    eff.append({"do": "publish", "event": "cpl.conversation_ended"})
    return Result(state, reason, eff)


def _over_length(conv, now, pol):
    lines = conv.get("lines", 0)
    started = next((t for t in (conv.get("started_at"), conv.get("created_at")) if t is not None), now)
    elapsed = now - started
    if lines >= pol["hard_lines"] or elapsed >= pol["hard_seconds"]:
        return "hard"
    if lines >= pol["max_lines"] or elapsed >= pol["max_seconds"]:
        return "soft"
    return None


def closing_reason(conv):
    """Why a conversation that wound down ended -- from what was settled, not from the model (plan section 8)."""
    hint = conv.get("outcome_hint")
    if hint in {r.value for r in R}:
        return hint
    return R.TOPIC_EXHAUSTED.value


def transition(conv, event, now):
    state = conv.get("state")
    kind = event.get("type")
    if state in FINAL:
        return _reject(conv, f"the conversation is {state}")
    pol = _policy(conv)

    # ── anywhere live ────────────────────────────────────────────────────────────────────────────────────────────
    if kind == "unavailable":
        left = {"do": "participant_left", "who": event.get("who"), "reason": "unavailable"}
        if state in (S.CREATED, S.PENDING):
            return _end(S.EXPIRED, R.UNAVAILABLE.value, [left, {"do": "settle_open", "status": "open"}])
        if len(_active(conv)) <= 2:
            return _end(S.RESOLVED, R.UNAVAILABLE.value, [left])
        return Result(state, None, [left, {"do": "set_floor", "holder": None}])
    if kind == "force_resolve":                       # from outside: an admin, or the legacy path ending it (shadow)
        final = S.EXPIRED if state in (S.CREATED, S.PENDING) else S.RESOLVED
        return _end(final, event.get("reason") or R.ABANDONED.value)
    if kind == "escalation":
        if state in (S.ACTIVE, S.RESOLVING, S.PAUSED):
            return _end(S.RESOLVED, R.CONFLICT_ESCALATION.value)
        return _reject(conv, "nothing to escalate")

    # ── CREATED ──────────────────────────────────────────────────────────────────────────────────────────────────
    if state == S.CREATED:
        if kind != "open":
            return _reject(conv, f"{kind} before the conversation was opened")
        if not event.get("reachable", True):
            return _end(S.EXPIRED, R.UNAVAILABLE.value, [{"do": "notify_initiator", "why": "unreachable"}])
        return Result(S.PENDING, None, [{"do": "schedule", "kind": "invite", "in": pol["invite_s"]},
                                        {"do": "publish", "event": "cpl.conversation_invited"}]
                      + [{"do": "request_turn", "who": p} for p in _others(conv, conv.get("initiator_id"))])

    # ── PENDING: invited, not yet answered ───────────────────────────────────────────────────────────────────────
    if state == S.PENDING:
        if kind == "timer":
            if event.get("kind") != "invite" or _stale(conv, event):
                return _reject(conv, "stale or foreign timer")
            if event.get("holder_thinking"):
                return Result(S.PENDING, None, [{"do": "schedule", "kind": "invite", "in": pol["invite_s"]}])
            return _end(S.EXPIRED, R.NO_ANSWER.value, [{"do": "notify_initiator", "why": "no_answer"},
                                                        {"do": "settle_open", "status": "open"}])
        if kind == "turn":
            if event.get("by") == conv.get("initiator_id"):
                if event.get("control") == "leave":
                    return _end(S.EXPIRED, R.ABANDONED.value)
                return _reject(conv, "the initiator waits for an answer")
            ctl = event.get("control")
            if ctl == "decline":
                return _end(S.RESOLVED, R.DECLINED.value, [{"do": "settle_open", "status": "rejected"},
                                                            {"do": "notify_initiator", "why": "declined"}])
            if ctl == "defer":
                return _end(S.RESOLVED, R.DECLINED.value, [{"do": "settle_open", "status": "deferred"},
                                                            {"do": "notify_initiator", "why": "later"}])
            if ctl == "leave":
                return _end(S.RESOLVED, R.DECLINED.value, [{"do": "settle_open", "status": "rejected"},
                                                            {"do": "notify_initiator", "why": "walked_off"}])
            # any other reply -- "What do you want?", "No.", even a hostile one -- starts it (spec invariant 7)
            eff = [{"do": "cancel", "kind": "invite"}, {"do": "publish", "event": "cpl.conversation_started"}]
            eff += _floor_after(conv, event, pol)
            return Result(S.ACTIVE, None, eff)
        if kind == "interrupt":
            return _reject(conv, "nothing to interrupt yet")
        return _reject(conv, f"{kind} while pending")

    # ── PAUSED ───────────────────────────────────────────────────────────────────────────────────────────────────
    if state == S.PAUSED:
        if kind == "timer":
            if event.get("kind") != "pause" or _stale(conv, event):
                return _reject(conv, "stale or foreign timer")
            return _end(S.RESOLVED, R.INTERRUPTED.value)
        if kind == "turn":
            ctl = event.get("control")
            if ctl == "leave":
                return _leave(conv, event)
            if ctl in ("resume", None):
                eff = [{"do": "cancel", "kind": "pause"}, {"do": "publish", "event": "cpl.conversation_resumed"}]
                if ctl is None:
                    eff += _floor_after(conv, event, pol)
                return Result(S.ACTIVE, None, eff)
            return _reject(conv, f"{ctl} while paused")
        return _reject(conv, f"{kind} while paused")

    # ── ACTIVE and RESOLVING ─────────────────────────────────────────────────────────────────────────────────────
    if kind == "timer":
        tk = event.get("kind")
        if _stale(conv, event):
            return _reject(conv, "stale timer")
        if tk == "close" and state == S.RESOLVING:
            return _end(S.RESOLVED, closing_reason(conv))
        if tk == "reply":
            if event.get("holder_thinking"):
                return Result(state, None, [{"do": "schedule", "kind": "reply", "in": pol["reply_s"]}])
            attempts = (conv.get("floor") or {}).get("attempts", 0) + 1
            if attempts >= pol["reply_attempts"]:
                reason = R.ABANDONED.value if conv.get("lines", 0) <= 1 else R.TIMEOUT.value
                return _end(S.RESOLVED, reason)
            return Result(state, None, [{"do": "set_floor", "holder": (conv.get("floor") or {}).get("holder"),
                                         "attempts": attempts},
                                        {"do": "schedule", "kind": "reply", "in": pol["reply_s"]},
                                        {"do": "request_turn", "who": (conv.get("floor") or {}).get("waiting_on")
                                         or conv.get("initiator_id"), "follow_up": True}])
        return _reject(conv, f"timer {tk} in {state}")

    if kind == "interrupt":
        return Result(state, None, [{"do": "publish", "event": "cpl.conversation_interrupted"}]
                      + [{"do": "request_turn", "who": p, "interrupted": True} for p in _active(conv)])

    if kind == "turn":
        ctl = event.get("control")
        if ctl == "leave":
            return _leave(conv, event)
        if ctl == "pause":
            return Result(S.PAUSED, None, [{"do": "cancel", "kind": "reply"}, {"do": "cancel", "kind": "close"},
                                           {"do": "schedule", "kind": "pause", "in": pol["pause_s"]},
                                           {"do": "publish", "event": "cpl.conversation_paused"}])
        if ctl in ("decline", "defer", "accept", "resume"):
            return _reject(conv, f"{ctl} in a conversation already under way")
        over = _over_length(conv, now, pol)
        if over == "hard":
            return _end(S.RESOLVED, R.TIMEOUT.value)
        if state == S.RESOLVING:
            if event.get("raises_item"):
                eff = [{"do": "cancel", "kind": "close"}] + _floor_after(conv, event, pol)
                return Result(S.ACTIVE, None, eff)                  # talk picks up again
            done = set(conv.get("closed_by") or ()) | {event.get("by")}
            if done >= set(_active(conv)):
                return _end(S.RESOLVED, closing_reason(conv))
            return Result(S.RESOLVING, None, [{"do": "closed_by", "who": event.get("by")}]
                          + [{"do": "request_turn", "who": p, "closing": True} for p in _active(conv) if p not in done])
        # ACTIVE
        if event.get("wrap_up") or event.get("settles_all") or over == "soft" or ctl == "close":
            return Result(S.RESOLVING, None, [{"do": "cancel", "kind": "reply"},
                                              {"do": "schedule", "kind": "close", "in": pol["close_s"]},
                                              {"do": "wind_down"}, {"do": "closed_by", "who": event.get("by")}]
                          + [{"do": "request_turn", "who": p, "closing": True} for p in _others(conv, event.get("by"))])
        return Result(S.ACTIVE, None, _floor_after(conv, event, pol))

    return _reject(conv, f"{kind} in {state}")


def _floor_after(conv, event, pol):
    """After a line: if it wants an answer, the floor goes to whoever is to answer and the reply timer runs."""
    by = event.get("by")
    others = _others(conv, by)
    if event.get("requires_response") and others:
        holder = event.get("addressed") or others[0]
        return [{"do": "set_floor", "holder": holder, "waiting_on": by, "attempts": 0},
                {"do": "schedule", "kind": "reply", "in": pol["reply_s"]},
                {"do": "request_turn", "who": holder}]
    return [{"do": "set_floor", "holder": None}, {"do": "cancel", "kind": "reply"}] + \
           [{"do": "request_turn", "who": p, "optional": True} for p in others]


def _leave(conv, event):
    who = event.get("by")
    reason = event.get("leave_reason") or "excuse"
    left = {"do": "participant_left", "who": who, "reason": reason}
    if len(_active(conv)) <= 2:
        r = {"angry": R.ANGRY_WITHDRAWAL.value, "unavailable": R.UNAVAILABLE.value}.get(reason,
                                                                                         R.PARTICIPANT_LEFT.value)
        return _end(S.RESOLVED, r, [left])
    return Result(conv.get("state"), None, [left, {"do": "set_floor", "holder": None}])
