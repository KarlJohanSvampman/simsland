"""
Step 4: character decisions as requests and responses (brain/cognition_actor.py).

Run inside the backend container:   python tests/test_cognition_actor.py
"""

import copy
import sys
import threading
import time

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]     # nothing else may reach the model
import brain.llm_brain as llm_brain
import brain.cognition_actor as ca
import brain.agent_loop as agent_loop
import sim_loop
from db import load_world
from core.definitions import load_definitions
from systems.schema_defaults import ensure_world_defaults

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# a model we control: answers after `delay` seconds, records every call
calls = []
delay = [0.3]
gate = threading.Event()
gate.set()


def fake_think(context, char_id=None, session=None, priority=None):
    calls.append((char_id, time.time()))
    gate.wait(30)
    time.sleep(delay[0])
    return {"thought": "Nothing to do.", "action": {"type": "wait", "reason": "test"}}


llm_brain.think = fake_think

processed = []
real_process = agent_loop.process_decision
agent_loop.process_decision = lambda c, w, d, available_actions=None: (processed.append((c["id"], w["tick"], d["action"]["type"])), None)[1]

live = load_world("default")
base = copy.deepcopy(live)
base["definitions"] = load_definitions("default")
for c in base["characters"].values():
    c["off_grid"] = False
    c["travel_state"] = None
    c["alive"] = True
    c["posture"] = "standing"
    c.get("cognition", {}).pop("pending", None)
    c.pop("_body_lazy", None)
cid = next(iter(base["characters"]))


def fresh():
    w = copy.deepcopy(base)
    ensure_world_defaults(w)
    return w, w["characters"][cid]


# ── request / response ─────────────────────────────────────────────────────────
w, c = fresh()
ctx = {"available_actions": {"wait": {}}}
req = ca.request_decision(c, w, ctx, "idle", 1)
check("a request is recorded on the character", ca.pending(c)["id"] == req and ca.is_waiting(c))
time.sleep(0.8)
check("the model call ran off the tick thread and answered", len(calls) == 1 and ca.is_waiting(c))   # answer is in the bus, not applied yet
event_bus.flush(w)
check("the answer is applied when the event is handled", not ca.is_waiting(c) and processed and processed[-1][2] == "wait", str(processed))
check("note_think ran (next think scheduled, wake cleared)", c["cognition"]["last_think_tick"] == w["tick"] and c["cognition"]["wake_reason"] is None)

# ── stale / superseded answers are ignored ──────────────────────────────────────
processed.clear()
w, c = fresh()
ca.request_decision(c, w, ctx, "idle", 1)
c["cognition"]["pending"]["id"] = "someone-elses-request"       # the request was replaced meanwhile
time.sleep(0.8); event_bus.flush(w)
check("an answer to a different request is ignored", not processed and ca.pending(c)["id"] == "someone-elses-request")

# ── timeout -> asked again ───────────────────────────────────────────────────────
w, c = fresh()
ca.request_decision(c, w, ctx, "idle", 1)
c["cognition"]["pending"]["wall"] -= ca.REQUEST_TIMEOUT_SECONDS + 5
check("a request nobody answered is dropped after the timeout", not ca.is_waiting(c) and ca.pending(c) is None)
time.sleep(0.8); event_bus.flush(w)

# ── a character who left the map doesn't act on a late answer ─────────────────────
processed.clear()
w, c = fresh()
ca.request_decision(c, w, ctx, "idle", 1)
c["off_grid"] = True
time.sleep(0.8); event_bus.flush(w)
check("an answer for someone now off-grid is noted but not acted on", not processed and c["cognition"]["pending"] is None and c["cognition"]["last_think_tick"] == w["tick"])
processed.clear()
w, c = fresh()
ca.request_decision(c, w, ctx, "idle", 1)
c["alive"] = False
time.sleep(0.8); event_bus.flush(w)
check("nor for someone who died while thinking", not processed)

# ── the tick never waits for the model ─────────────────────────────────────────────
calls.clear(); processed.clear()
delay[0] = 2.0
gate.clear()                                         # the model is "hung" until we release it
w, c = fresh()
for ch in w["characters"].values():
    ch["cognition"]["next_think_tick"] = 0
    ch["cognition"]["wake_reason"] = "idle"
    ch["activity"] = None
    ch["active_intentions"] = []
durations = []
for _ in range(25):
    ensure_world_defaults(w)
    t0 = time.time(); sim_loop.tick(w); durations.append(time.time() - t0)
n_chars = len([x for x in w["characters"].values() if not x.get("is_workplace_npc")])
print(f"   {len(calls)} model calls started; slowest tick {max(durations) * 1000:.0f} ms; model still hung")
check("ticks run at full speed while the model hasn't answered (the first tick pays for imports)", max(durations[2:]) < 0.3, f"{max(durations[2:]):.2f}s")
asked = sum(1 for x in w["characters"].values() if ca.pending(x))     # some characters are off at work instead of thinking
check("each character that wanted to think asked the model once, not every tick", asked >= 1 and len(calls) == asked, f"{len(calls)} calls, {asked} pending, {n_chars} chars")
gate.set()
time.sleep(2.6)
for _ in range(3):
    ensure_world_defaults(w); sim_loop.tick(w)
check("the answers are applied on a later tick", len(processed) == asked and not any(ca.pending(x) for x in w["characters"].values()), str(processed))
t_applied = {p[0]: p[1] for p in processed}
check("they landed at the tick after the model finished, not mid-way", all(v > 25 for v in t_applied.values()), str(t_applied))

# ── restart: a pending request with no worker is re-asked after the timeout ────────────
calls.clear(); processed.clear(); delay[0] = 0.2
w, c = fresh()
c["cognition"]["pending"] = {"id": "lost", "tick": w["tick"], "wall": time.time() - ca.REQUEST_TIMEOUT_SECONDS - 1, "wake_reason": "idle"}
c["cognition"]["next_think_tick"] = 0; c["cognition"]["wake_reason"] = "idle"; c["activity"] = None; c["active_intentions"] = []
for _ in range(3):
    ensure_world_defaults(w); sim_loop.tick(w)
time.sleep(0.6)
ensure_world_defaults(w); sim_loop.tick(w)
check("after a restart a lost request is re-asked", any(call[0] == cid for call in calls), str(calls))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
