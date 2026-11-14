"""
CPL phase 1, step 1 (docs/cpl_implementation_plan.md sections 4, 8): the lifecycle table, the store and the
timer-driven engine, on a bare world (no database, no model).

  * every row of the transition table, illegal transitions rejected, nothing leaves RESOLVED / EXPIRED;
  * stale timers do nothing; a generation in progress holds a deadline;
  * the engine: ids and sequence numbers, duplicates dropped, timers on the scheduler, requests settled,
    wind-down at the soft cap and a hard stop at twice it;
  * the envelope validates its payload.

Run inside the backend container:   python tests/test_cpl_state_machine.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from cpl import policies, state_machine as sm, store
from cpl.model.enums import ConvState as S, ResolutionReason as R


def conv(state, parts=("a", "b"), **kw):
    c = {"id": "cv_1", "state": state, "state_version": 3, "initiator_id": parts[0], "lines": 1,
         "participants": {p: {"status": "active"} for p in parts}, "floor": {"holder": "b", "waiting_on": "a",
                                                                               "attempts": 0},
         "policy_key": policies.key("social", "in_person"), "created_at": 0.0, "started_at": 0.0,
         "timers": {"invite": 3, "reply": 3, "pause": 3, "close": 3}, "closed_by": []}
    if state == S.PENDING.value:
        c["participants"]["b"]["status"] = "invited"
    c.update(kw)
    return c


def T(c, ev, now=10.0):
    return sm.transition(c, ev, now)


def did(res, do, **match):
    return any(e["do"] == do and all(e.get(k) == v for k, v in match.items()) for e in res.effects)


P = S.PENDING.value
A = S.ACTIVE.value

# ── CREATED ──────────────────────────────────────────────────────────────────────────────────────────────────────────
r = T(conv(S.CREATED.value), {"type": "open", "reachable": True})
check("open, reachable: PENDING, invite timer, the recipient asked",
      r.state == S.PENDING and did(r, "schedule", kind="invite") and did(r, "request_turn", who="b"))
r = T(conv(S.CREATED.value), {"type": "open", "reachable": False})
check("open, nobody reachable: EXPIRED (unavailable), the initiator told",
      r.state == S.EXPIRED and r.reason == R.UNAVAILABLE.value and did(r, "notify_initiator"))
check("a turn before opening is rejected", not T(conv(S.CREATED.value), {"type": "turn", "by": "a"}).changed)

# ── PENDING ──────────────────────────────────────────────────────────────────────────────────────────────────────────
r = T(conv(P), {"type": "turn", "by": "b", "content": "What do you want?", "requires_response": False})
check("any reply starts it -- even 'What do you want?' (invariant 7)", r.state == S.ACTIVE and did(r, "cancel", kind="invite"))
r = T(conv(P), {"type": "turn", "by": "b", "content": "No."})
check("... even 'No.' as a line", r.state == S.ACTIVE)
r = T(conv(P), {"type": "turn", "by": "b", "control": "decline"})
check("decline: RESOLVED (declined), open requests rejected",
      r.state == S.RESOLVED and r.reason == R.DECLINED.value and did(r, "settle_open", status="rejected"))
r = T(conv(P), {"type": "turn", "by": "b", "control": "defer"})
check("'later': RESOLVED (declined), requests deferred", r.reason == R.DECLINED.value and did(r, "settle_open", status="deferred"))
r = T(conv(P), {"type": "timer", "kind": "invite", "version": 3})
check("invite timer, unanswered: EXPIRED (no answer)", r.state == S.EXPIRED and r.reason == R.NO_ANSWER.value)
r = T(conv(P), {"type": "timer", "kind": "invite", "version": 3, "holder_thinking": True})
check("... but not while the invitee is still thinking: re-armed", r.state == S.PENDING and did(r, "schedule", kind="invite"))
check("a stale invite timer is a no-op", not T(conv(P), {"type": "timer", "kind": "invite", "version": 2}).changed)
check("the initiator can't talk over the pending invitation", not T(conv(P), {"type": "turn", "by": "a"}).changed)
r = T(conv(P), {"type": "turn", "by": "a", "control": "leave"})
check("... but can give up (EXPIRED, abandoned)", r.state == S.EXPIRED and r.reason == R.ABANDONED.value)

# ── ACTIVE ───────────────────────────────────────────────────────────────────────────────────────────────────────────
r = T(conv(A), {"type": "turn", "by": "a", "requires_response": True})
check("a question: the floor goes to the other, reply timer, they are asked",
      r.state == S.ACTIVE and did(r, "set_floor", holder="b") and did(r, "schedule", kind="reply") and did(r, "request_turn", who="b"))
r = T(conv(A), {"type": "turn", "by": "a"})
check("a statement: no floor held, the other may answer", did(r, "set_floor", holder=None) and did(r, "request_turn", who="b", optional=True))
r = T(conv(A), {"type": "timer", "kind": "reply", "version": 3, "holder_thinking": True})
check("reply timer while the holder is thinking: re-armed, no timeout", r.state == S.ACTIVE and did(r, "schedule", kind="reply"))
r = T(conv(A), {"type": "timer", "kind": "reply", "version": 3})
check("reply timer, first miss: attempt 1, the speaker may follow up", r.state == S.ACTIVE and did(r, "set_floor", attempts=1)
      and did(r, "request_turn", who="a", follow_up=True))
r = T(conv(A, floor={"holder": "b", "waiting_on": "a", "attempts": 1}, lines=3), {"type": "timer", "kind": "reply", "version": 3})
check("reply timer, attempts used up: RESOLVED (timeout)", r.state == S.RESOLVED and r.reason == R.TIMEOUT.value)
r = T(conv(A, floor={"holder": "b", "waiting_on": "a", "attempts": 1}, lines=1), {"type": "timer", "kind": "reply", "version": 3})
check("... or abandoned if it never got past the first line", r.reason == R.ABANDONED.value)
r = T(conv(A), {"type": "turn", "by": "b", "control": "leave", "leave_reason": "angry"})
check("one of two leaves angry: RESOLVED (angry withdrawal)", r.state == S.RESOLVED and r.reason == R.ANGRY_WITHDRAWAL.value
      and did(r, "participant_left", who="b", reason="angry"))
r = T(conv(A), {"type": "turn", "by": "b", "control": "leave"})
check("one of two leaves with an excuse: RESOLVED (participant left)", r.reason == R.PARTICIPANT_LEFT.value)
r = T(conv(A, parts=("a", "b", "c")), {"type": "turn", "by": "c", "control": "leave"})
check("one of three leaves: still ACTIVE, they are marked left", r.state == S.ACTIVE and did(r, "participant_left", who="c"))
r = T(conv(A), {"type": "turn", "by": "a", "control": "pause"})
check("pause: PAUSED with a pause deadline", r.state == S.PAUSED and did(r, "schedule", kind="pause"))
r = T(conv(A), {"type": "interrupt", "by": "doorbell"})
check("an interruption: both asked (ignore / pause / leave), still ACTIVE", r.state == S.ACTIVE and did(r, "request_turn", who="a", interrupted=True))
r = T(conv(A), {"type": "turn", "by": "a", "wrap_up": True})
check("wrap up: RESOLVING, close timer, the other gets a closing turn", r.state == S.RESOLVING and did(r, "schedule", kind="close")
      and did(r, "request_turn", who="b", closing=True))
pol = policies.from_key(policies.key("social", "in_person"))
r = T(conv(A, lines=pol["max_lines"]), {"type": "turn", "by": "a"})
check("the length policy reached: winding down (RESOLVING), not a hard stop", r.state == S.RESOLVING and did(r, "wind_down"))
r = T(conv(A, lines=pol["hard_lines"]), {"type": "turn", "by": "a"})
check("twice the policy: RESOLVED (timeout) -- every conversation ends (invariant 15)", r.state == S.RESOLVED and r.reason == R.TIMEOUT.value)
r = T(conv(A), {"type": "turn", "by": "a"}, now=pol["hard_seconds"] + 1)
check("... by time as well as by lines", r.reason == R.TIMEOUT.value)
check("accepting an invitation mid-conversation is rejected", not T(conv(A), {"type": "turn", "by": "b", "control": "decline"}).changed)
r = T(conv(A), {"type": "unavailable", "who": "b"})
check("someone becomes unavailable: RESOLVED (unavailable)", r.state == S.RESOLVED and r.reason == R.UNAVAILABLE.value)
r = T(conv(A), {"type": "escalation"})
check("it turns into a fight: RESOLVED (conflict escalation)", r.reason == R.CONFLICT_ESCALATION.value)

# ── RESOLVING / PAUSED ───────────────────────────────────────────────────────────────────────────────────────────────
Z = S.RESOLVING.value
r = T(conv(Z, closed_by=["a"]), {"type": "turn", "by": "b"})
check("winding down: once everyone has said their closing line, RESOLVED", r.state == S.RESOLVED)
r = T(conv(Z, closed_by=["a"], outcome_hint=R.QUESTION_ANSWERED.value), {"type": "turn", "by": "b"})
check("... with the reason from what was settled (question answered), not from the model", r.reason == R.QUESTION_ANSWERED.value)
r = T(conv(Z, closed_by=[]), {"type": "turn", "by": "b", "raises_item": True})
check("winding down, a new question: talk picks up again (ACTIVE)", r.state == S.ACTIVE)
r = T(conv(Z), {"type": "timer", "kind": "close", "version": 3})
check("winding down, close timer: RESOLVED", r.state == S.RESOLVED and r.reason == R.TOPIC_EXHAUSTED.value)
r = T(conv(S.PAUSED.value), {"type": "turn", "by": "a", "control": "resume"})
check("paused, resume: ACTIVE", r.state == S.ACTIVE and did(r, "cancel", kind="pause"))
r = T(conv(S.PAUSED.value), {"type": "timer", "kind": "pause", "version": 3})
check("paused too long: RESOLVED (interrupted)", r.state == S.RESOLVED and r.reason == R.INTERRUPTED.value)

for final in (S.RESOLVED.value, S.EXPIRED.value):
    rej = [T(conv(final), ev) for ev in ({"type": "turn", "by": "a"}, {"type": "timer", "kind": "close", "version": 3},
                                         {"type": "open"}, {"type": "unavailable", "who": "a"})]
    check(f"nothing leaves {final}", all(not x.changed for x in rej))

# ── the engine, on a bare world ──────────────────────────────────────────────────────────────────────────────────────
from core import event_bus, scheduler
from cpl import conversations as CV
from cpl.protocol.envelope import Envelope

seen = []
for name in ("cpl.turn_requested", "cpl.conversation_started", "cpl.conversation_ended", "cpl.initiator_notified"):
    event_bus.subscribe(name, lambda data, world=None, _n=name: seen.append((_n, data.get("who"))))

w = {"tick": 0, "sim_time": 1000.0, "characters": {"a": {"id": "a"}, "b": {"id": "b"}}, "timers": []}
c = CV.open_conversation(w, "a", ["b"], channel="in_person", purpose="request", topic="the car")
check("opened: PENDING, an id from the world's counter, an invite timer on the scheduler",
      c["state"] == "pending" and c["id"] == "cv_000001" and any(t["owner"] == "cpl:cv_000001" and t["key"] == "invite"
                                                                 for t in w["timers"]))
req = store.add_request(w, c, kind="request", requester_id="a", recipient_id="b", action="borrow the car",
                        source_message_id=None, now=1000.0)
env = Envelope(message_id="msg_t1", conversation_id=c["id"], sender_id="a", recipient_ids=["b"], message_type="request",
               world_ts=1000.0, payload={"action": "borrow the car"}, content="Could I borrow your car tonight?").stored()
m1 = store.append_message(w, c, env)
m2 = store.append_message(w, c, env)
check("a message gets the next sequence number; the same message id twice is stored once",
      m1 and m1["sequence_number"] == 1 and m2 is None and len(c["messages"]) == 1 and c["lines"] == 1)
w["sim_time"] += 30
CV.submit(w, c, {"type": "turn", "by": "b", "requires_response": True})
check("the reply: ACTIVE, b now active, started_at set, the invite timer gone",
      c["state"] == "active" and c["participants"]["b"]["status"] == "active" and c["started_at"] == 1030.0
      and not any(t["key"] == "invite" for t in w["timers"] if t["owner"] == "cpl:cv_000001"))
w["sim_time"] += policies.policy("request", "in_person")["reply_s"] + 1
due = [t for t in w["timers"] if t["owner"] == "cpl:cv_000001"]
scheduler.fire_due(w)
check("its reply timer firing: the first miss (attempt 1), re-armed", c["state"] == "active" and c["floor"]["attempts"] == 1
      and any(t["key"] == "reply" for t in w["timers"] if t["owner"] == "cpl:cv_000001"), (due, c["floor"]))
old = dict(w["timers"][0]) if w["timers"] else None
CV.submit(w, c, {"type": "turn", "by": "a"})          # a statement: replaces the reply timer
if old:
    stale = CV.state_machine.transition(c, {"type": "timer", "kind": "reply", "version": old["payload"]["version"]}, 0)
    check("a timer cancelled since is stale", not stale.changed)
CV.submit(w, c, {"type": "turn", "by": "b", "control": "leave", "leave_reason": "angry"})
check("an angry exit: RESOLVED, the outcome records it and the request it left open",
      c["state"] == "resolved" and c["reason"] == "angry_withdrawal" and c["outcome"]["settled"] == {req["id"]: "open"})
check("... and the open request outlives the conversation (invariant 9)", store.open_requests(w, "b")[0]["id"] == req["id"])
check("no timers left behind for it", not [t for t in w["timers"] if t["owner"] == "cpl:cv_000001"])

c2 = CV.open_conversation(w, "a", ["b"], channel="call", purpose="request", topic="dinner")
req2 = store.add_request(w, c2, kind="request", requester_id="a", recipient_id="b", action="come to dinner",
                         source_message_id=None, now=w["sim_time"])
CV.submit(w, c2, {"type": "turn", "by": "b", "control": "decline"})
event_bus.flush(w)
check("a declined call: RESOLVED (declined), its request rejected, the initiator told",
      c2["reason"] == "declined" and w["cpl_requests"][req2["id"]]["status"] == "rejected"
      and ("cpl.initiator_notified", "a") in seen)
check("a call's invitation is shorter than face to face", policies.policy("request", "call")["invite_s"] < policies.policy("request", "in_person")["invite_s"])

# ── the envelope ─────────────────────────────────────────────────────────────────────────────────────────────────────
try:
    Envelope(message_id="m", conversation_id="c", sender_id="a", recipient_ids=["b"], message_type="response",
             world_ts=0, payload={"response_type": "accept"})
    ok = False
except Exception:
    ok = True
check("a response without what it answers is invalid", ok)
try:
    Envelope(message_id="m", conversation_id="c", sender_id="a", recipient_ids=["b"], message_type="control", world_ts=0)
    ok = False
except Exception:
    ok = True
check("a control message must name its control", ok)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
