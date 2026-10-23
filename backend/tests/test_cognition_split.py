"""
Container split, stage 1: cognition workers over Redis Streams
(core/cognition_queue.py, workers/cognition.py, brain/cognition_actor.py remote path).

Uses its own stream/key names so a running core or worker is never involved.

Run inside the backend container:   python tests/test_cognition_split.py
"""

import json
import sys
import threading
import time

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]
import brain.llm_brain as llm_brain
import brain.cognition_actor as ca
import brain.cognition_scheduler as cs
from core import cognition_queue as q
from core.cache import r
from llm import llm_client

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# isolate from anything live
q.queue.rename("test:cog")
q.queue.alive_cache_seconds = 0.0
for k in (q.queue.req_stream, q.queue.res_stream):
    r.delete(k)
for k in r.scan_iter(match=q.queue.worker_prefix + "*"):
    r.delete(k)
q.forget_alive_cache()

emitted = []
ca.emit = lambda name, data: emitted.append((name, data))
local_runs = []
ca._pool = type("P", (), {"submit": lambda self, fn, *a, **k: local_runs.append(a)})()


def wait_for(pred, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def character(cid="c1"):
    return {"id": cid, "name": cid}


CTX = {"available_actions": {"wait": {}}, "self": {"hp": 3, "tags": ("a", "b")}}

# ---- wire: roundtrip, redelivery, deadline ------------------------------------------------
q.ensure_group()
q.enqueue({"req_id": "r1", "n": 1})
sid, req = q.claim("w1", block_ms=500)
check("a request survives the wire", req == {"req_id": "r1", "n": 1})
check("nothing else is queued", q.claim("w1", block_ms=100) is None)
q.queue.claim_idle_ms = 300                           # w1 "dies" without acking
time.sleep(0.45)
got = q.claim("w2", block_ms=300)
check("an unacked request is taken over by another worker", got is not None and got[1]["req_id"] == "r1")
q.complete(got[0], {"req_id": "r1", "ok": True})
last, res = q.read_results("0-0", block_ms=300)
check("the result is readable", res == [{"req_id": "r1", "ok": True}])
check("a completed request is gone", q.claim("w3", block_ms=100) is None)
q.queue.claim_idle_ms = 150_000

# ---- heartbeat ----------------------------------------------------------------------------
check("no workers, none alive", q.workers_alive() == 0)
q.heartbeat("hb1")
check("a heartbeat counts", q.workers_alive() == 1)
r.delete(q.queue.worker_prefix + "hb1")
check("a missing heartbeat does not", q.workers_alive() == 0)

# ---- no worker -> local --------------------------------------------------------------------
ca.MODE = "auto"
c = character()
world = {"tick": 5}
ca.request_decision(c, world, CTX, "t", 1)
check("no worker alive: the decision runs locally", len(local_runs) == 1 and not ca._inflight)
c["cognition"]["pending"] = None
local_runs.clear()
ca.MODE = "local"
q.heartbeat("hb1")
ca.request_decision(c, world, CTX, "t", 1)
check("local mode ignores workers", len(local_runs) == 1)
local_runs.clear()
r.delete(q.queue.worker_prefix + "hb1")

# ---- worker in this process, end to end ----------------------------------------------------
import workers.cognition as wk
wk.runtime.worker_id = "test-worker"
wk.runtime.heartbeat_seconds = 0.5
think_calls = []


def fake_think(context, char_id=None, session=None, priority=None):
    think_calls.append((char_id, context, session, priority))
    cs.record_prompt_bytes(1234)
    llm_client.log_prompt_entry(char_id, [{"role": "user", "content": "hi"}], "ok", 0.1, False)
    return {"thought": "fine", "action": {"type": "wait", "reason": "x"}}


llm_brain.think = fake_think
wk._patch_prompt_bytes()
wk.runtime.threads = 2
wk.runtime.start()
check("the worker's heartbeat is seen", wait_for(lambda: q.workers_alive() == 1))

ca.MODE = "auto"
llm_client._PROMPT_LOG.pop("c1", None)
bytes_before = cs._prompt_byte_total
c = character("c1")
ca.request_decision(c, {"tick": 7}, CTX, "idle", 0)
rid = c["cognition"]["pending"]["id"]
check("a live worker: the request goes over the wire", rid in ca._inflight and not local_runs)
check("the decision comes back as decision_ready", wait_for(lambda: any(n == "decision_ready" for n, _ in emitted)))
name, data = emitted[-1]
check("it carries the decision, request id and actions", data["decision"]["action"]["type"] == "wait"
      and data["request_id"] == rid and data["available_actions"] == {"wait": {}} and data["wake_reason"] == "idle")
check("the worker saw the context and priority", think_calls and think_calls[0][3] == 0
      and think_calls[0][1]["self"]["hp"] == 3)
# (worker and core share this test process, so the entry is in the log twice: once logged, once merged)
done = wk.run_request({"req_id": "x", "char_id": "c1", "context": CTX, "session": None, "priority": 1})
check("the worker captures its prompt-log entry for the result", len(done["prompt_log"]) == 1
      and done["prompt_bytes"] == 1234)
llm_client._PROMPT_LOG.pop("c1", None)
ca._merge_worker_telemetry(done)
check("the worker's prompt log reaches this process", len(llm_client.get_prompt_log("c1")) == 1)
check("the worker's prompt bytes are counted here", cs._prompt_byte_total - bytes_before >= 1234)
check("the request is no longer in flight", rid not in ca._inflight)

# a duplicate result for the same request is ignored
n = len(emitted)
ca._accept_remote_result({"req_id": rid, "char_id": "c1", "decision": {}})
check("a duplicate result is ignored", len(emitted) == n)

# many at once
emitted.clear()
chars = [character(f"m{i}") for i in range(12)]
for ch in chars:
    ca.request_decision(ch, {"tick": 9}, CTX, "idle", 1)
check("twelve concurrent requests all come back", wait_for(lambda: len(emitted) == 12, 15))
check("each to the right character", {d["character_id"] for _, d in emitted} == {f"m{i}" for i in range(12)})

# an expired request is dropped without calling the model
calls_before = len(think_calls)
q.enqueue({"req_id": "old", "char_id": "x", "context": CTX, "deadline": time.time() - 5})
time.sleep(2.5)
check("an expired request is dropped, the model not called", len(think_calls) == calls_before)

# a worker whose think() raises still answers
def boom(context, char_id=None, session=None, priority=None):
    raise RuntimeError("model down")
llm_brain.think = boom
emitted.clear()
c = character("e1")
ca.request_decision(c, {"tick": 1}, CTX, "idle", 1)
check("a failing model call is reported, not lost", wait_for(lambda: emitted) and emitted[-1][1]["decision"] is None)
llm_brain.think = fake_think

# ---- worker disappears with a request outstanding -----------------------------------------
wk.runtime.stop.set()                                   # the worker stops and its heartbeat lapses
time.sleep(2.5)
r.delete(q.queue.worker_prefix + "test-worker")
q.forget_alive_cache()
check("the stopped worker is no longer alive", q.workers_alive() == 0)

ca.MODE = "remote"                               # force the wire even with nobody listening
ca.REMOTE_FALLBACK_SECONDS = 1.0
local_runs.clear(); emitted.clear()
c = character("s1")
ca.request_decision(c, {"tick": 2}, CTX, "idle", 1)
sid_rid = c["cognition"]["pending"]["id"]
check("remote mode queues it regardless", sid_rid in ca._inflight)
check("with nobody answering, it falls back to running locally",
      wait_for(lambda: len(local_runs) == 1 and sid_rid not in ca._inflight, 10))

# an unserialisable context is not sent
ca.MODE = "auto"
q.heartbeat("hb2")
local_runs.clear()
c = character("u1")
ca.request_decision(c, {"tick": 3}, {"available_actions": {}, "bad": object()}, "idle", 1)
check("a context json can only stringify still goes (default=str), request tracked", "u1" in str(ca._inflight) or local_runs)

# ---- real contexts are wire-safe -----------------------------------------------------------
r.delete(q.queue.worker_prefix + "hb2")
ca.MODE = "local"
seen = []
real_request = ca.request_decision


def spy(c, world, context, wake_reason, priority):
    try:
        json.dumps(context)
        seen.append((True, None))
    except Exception as exc:
        seen.append((False, repr(exc)[:200]))
    return real_request(c, world, context, wake_reason, priority)


sys.path.insert(0, "/app/tests")
from tests import determinism
import brain.agent_loop as agent_loop
ca.request_decision = spy
determinism._install()
ca._pool = type("P", (), {"submit": lambda self, fn, *a, **k: None})()      # decisions are not needed
llm_brain.think = lambda *a, **k: None
import sim_loop
from systems.schema_defaults import ensure_world_defaults
w = determinism.fixture("2026-11-01T09:00:00")
for ch in w["characters"].values():
    ch["cognition"] = {}
for i in range(120):
    ensure_world_defaults(w)
    determinism._Clock.t += 1.0
    sim_loop.tick(w)
    for ch in w["characters"].values():                                   # let them be asked again at once
        (ch.get("cognition") or {}).pop("pending", None)
bad = [e for ok, e in seen if not ok]
print(f"   {len(seen)} real contexts built; {len(bad)} not strictly JSON-serialisable {bad[:1]}")
check("real contexts were produced", len(seen) > 0)
check("real contexts are strictly JSON-serialisable", not bad, str(bad[:1]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
