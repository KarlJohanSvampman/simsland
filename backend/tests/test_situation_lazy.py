"""
select_situation() runs when a decision needs it, not every tick.

Run inside the backend container:   python tests/test_situation_lazy.py
"""

import copy
import json
import sys
import time

import os
os.environ.setdefault("COGNITION_MODE", "local")     # never reach a live cognition worker
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]
import brain.llm_brain as llm_brain
import sim_loop
from brain.situations import selector, history
from db import load_world, _STATIC_WORLD_KEYS
from core.definitions import load_definitions
from systems.schema_defaults import ensure_world_defaults

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


requests = []
llm_brain.think = lambda context, char_id=None, session=None, priority=None: (requests.append(char_id), {"thought": "ok", "action": {"type": "wait", "reason": "x"}})[1]

live = load_world("default")
w = json.load(open("/tmp/backup_world.json", encoding="utf-8"))
for k in set(_STATIC_WORLD_KEYS):
    if k in live:
        w[k] = live[k]
w["definitions"] = load_definitions("default")
for c in w["characters"].values():
    c["off_grid"] = False
    c["travel_state"] = None
    c.pop("_body_lazy", None)
    c.pop("_situation_history", None)
    c.pop("selected_situation", None)

selects = []
real = selector.select_situation
selector.select_situation = lambda c, world: (selects.append(c["id"]), real(c, world))[1]

for _ in range(1500):
    ensure_world_defaults(w)
    sim_loop.tick(w)
    time.sleep(0.0005)
time.sleep(0.5)
ensure_world_defaults(w); sim_loop.tick(w)

n_req = len(requests)
print(f"   1500 ticks: {n_req} decisions requested, select_situation called {len(selects)} times (per-tick would be ~{1500 * 4})")
check("select_situation runs per decision, not per tick", len(selects) <= n_req + 4 and len(selects) < 300, f"{len(selects)} vs {n_req} requests")
per_char = {}
for cid in requests:
    per_char[cid] = per_char.get(cid, 0) + 1
hist_len = {cid: len(c.get("_situation_history") or []) for cid, c in w["characters"].items()}
# (+1: a request may still be in flight when the count is taken)
check("the history records decisions, not ticks", all(hist_len.get(cid, 0) <= per_char.get(cid, 0) + 1 for cid in hist_len), f"history {hist_len} vs decisions {per_char}")

# the selection is the same function of the same state, whether it was computed per tick or at read time
c = next(iter(w["characters"].values()))
from brain.intentions import add_intention
c["active_intentions"] = []
add_intention(c, {"type": "eat_food", "category": "survival", "priority": 65, "reason": "hungry"})
add_intention(c, {"type": "socialize", "category": "social", "priority": 50, "reason": "lonely"})
c["_situation_history"] = []
a = real(copy.deepcopy(c), w)
b = real(copy.deepcopy(c), w)
check("same state -> same selection", a and b and [s["type"] for s in a["situations"]] == [s["type"] for s in b["situations"]])

# what the old per-tick recording did: the situation just chosen got penalised for being chosen
c2 = copy.deepcopy(c)
first = real(c2, w)["situations"][0]["type"]
seen = [first]
for t in range(1, 60):
    w2 = dict(w, tick=w["tick"] + t)
    seen.append(real(c2, w2)["situations"][0]["type"])
flips = sum(1 for x, y in zip(seen, seen[1:]) if x != y)
c3 = copy.deepcopy(c); c3["_situation_history"] = []
seen3 = []
for t in range(0, 60 * 60, 60):               # one decision a minute instead of one per tick
    w3 = dict(w, tick=w["tick"] + t)
    seen3.append(real(c3, w3)["situations"][0]["type"])
flips3 = sum(1 for x, y in zip(seen3, seen3[1:]) if x != y)
print(f"   per-tick recording flipped the winner {flips}x in 60 ticks; one selection a minute flipped it {flips3}x in 60 selections")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
