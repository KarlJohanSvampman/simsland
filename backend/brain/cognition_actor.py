"""
brain/cognition_actor.py

A character's decisions as requests and responses, not as work the tick waits for
(docs/distributed_architecture_plan.md, step 4: character actors).

Before: every tick, each character's whole update_agent() ran on a thread pool, the tick
waited up to AGENT_WAIT_BUDGET_SECONDS (3s) for all of them, and any decision still in the
model when the budget ran out was ABANDONED -- its result and whatever it had mutated were
thrown away, the character was excluded from updates until its leaked thread returned, and
the same situation was re-offered later. Every slow model call cost the whole simulation 3
seconds of world lock.

Now update_agent() runs on the tick thread (it no longer blocks on anything slow), and when
a character has something to decide it REQUESTS a decision:

    update_agent -> request_decision()   builds the context on the tick thread (it reads the
                                         world), records a pending request on the character
                                         (c["cognition"]["pending"], so a restart can notice
                                         it), and hands the model call to a worker that touches
                                         no world state
    worker       -> think(...)           the blocking model round-trip, however long it takes
                 -> emit("decision_ready")
    on_decision_ready()                  an event handler on the tick thread: note_think(),
                                         then process_decision() -- which re-validates the
                                         action against the world AS IT IS NOW (positions,
                                         who is awake, what is reachable), so a late answer to
                                         a stale situation fails cleanly instead of acting on
                                         it.

While a request is pending the character keeps living (activities progress, needs move, they
react to events); they just don't ask the model again. A request that never answers (the
process restarted, the worker died) is given up on after REQUEST_TIMEOUT_SECONDS of wall
time and the character is offered the decision again.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from core.event_bus import emit, subscribe

WORKERS = 16
REQUEST_TIMEOUT_SECONDS = 240.0       # comfortably above llm_gate's own worst-case wait
SESSION_TURNS = 6

_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="cognition")


def pending(c):
    return (c.get("cognition") or {}).get("pending")


def is_waiting(c):
    """True while this character has a decision request the model hasn't answered yet.
    A request older than the timeout is dropped (and False returned) so it gets re-asked."""
    p = pending(c)
    if not p:
        return False
    if time.time() - p.get("wall", 0) > REQUEST_TIMEOUT_SECONDS:
        c["cognition"]["pending"] = None
        print(f"[cognition] {c.get('name', c.get('id'))}: request {p.get('id')} got no answer in "
              f"{REQUEST_TIMEOUT_SECONDS:.0f}s -- asking again")
        return False
    return True


def request_decision(c, world, context, wake_reason, priority):
    """Record the request on the character and start the model call in the background."""
    from systems.conversation_floor import mark_thinking
    tick = world.get("tick", 0)
    req_id = uuid.uuid4().hex[:10]
    c.setdefault("cognition", {})["pending"] = {
        "id": req_id, "tick": tick, "wall": time.time(), "wake_reason": wake_reason,
    }
    mark_thinking(c["id"], tick)           # "is generating a reply" -- the floor's notice cue
    session = {"history": list(((c.get("_llm_session") or {}).get("history") or [])[-SESSION_TURNS:])}
    _pool.submit(_worker, c["id"], req_id, tick, context, session, priority, wake_reason)
    return req_id


def _worker(char_id, req_id, tick, context, session, priority, wake_reason):
    """Runs on a pool thread. Touches no world state: context and session are plain data."""
    from brain.llm_brain import think
    from systems.conversation_floor import clear_thinking
    decision = None
    try:
        decision = think(context, char_id=char_id, session=session, priority=priority)
    except Exception as exc:
        print(f"[cognition] decision for {char_id} failed: {exc!r}")
    finally:
        clear_thinking(char_id, tick)
    emit("decision_ready", {
        "character_id": char_id, "request_id": req_id, "decision": decision,
        "wake_reason": wake_reason, "available_actions": context.get("available_actions"),
    })


def on_decision_ready(data, world):
    """The model answered (tick thread, at flush)."""
    cid = data.get("character_id")
    c = world.get("characters", {}).get(cid)
    if not c:
        return
    p = pending(c)
    if not p or p.get("id") != data.get("request_id"):
        return                              # superseded, timed out, or from before a restart
    c["cognition"]["pending"] = None

    from brain.cognition_scheduler import note_think
    decision = data.get("decision")
    note_think(c, world, decision, wake_reason=data.get("wake_reason"))
    if not decision:
        return

    # The world moved while the model thought. Someone who has since died, collapsed or left
    # the map can't act on the answer.
    from systems.travel import TRAVEL_FROZEN_STATES
    if (c.get("alive") is False or c.get("posture") == "incapacitated" or c.get("off_grid")
            or c.get("travel_state") in TRAVEL_FROZEN_STATES):
        return

    from brain.agent_loop import process_decision, post_update
    process_decision(c, world, decision, available_actions=data.get("available_actions"))
    post_update(c, world)
    try:
        from sim_loop import _mark_dirty
        _mark_dirty(world, char_ids={cid})
    except Exception:
        pass


subscribe("decision_ready", on_decision_ready)
