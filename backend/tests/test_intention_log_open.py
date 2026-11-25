"""
The intentions log keeps an intention open while the activity started for it runs (live 2026-11-25: "sleep" was logged
done the minute the character lay down, hours before they woke).

Run inside the backend container:   python tests/test_intention_log_open.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from brain import intention_history as H

c = {"id": "a", "active_intentions": [{"type": "sleep", "reason": "tired"}], "activity": None}
w = {"tick": 100}
H.track(c, w)
c["active_intentions"], c["activity"], c["_activity_starts"] = [], {"type": "sleep"}, [[101, "sleep", "sleep"]]
w["tick"] = 101
H.track(c, w)
check("asleep: the sleep intention is still open", not c.get("intention_history"))
w["tick"] = 30000
c["activity"] = None
c["_intention_done"] = {"sleep|": {"outcome": "done", "how": "sleep", "tick": 30000}}
H.track(c, w)
h = (c.get("intention_history") or [{}])[-1]
check("woke up: logged from when it came to when they woke, done", h.get("since") == 100 and h.get("ended") == 30000
      and h.get("outcome") == "done", h)

d = {"id": "b", "active_intentions": [{"type": "eat_food"}], "activity": None}
H.track(d, {"tick": 5})
d["active_intentions"], d["activity"], d["_activity_starts"] = [], {"type": "eat_meal"}, [[6, "eat_meal", "eat_food"]]
H.track(d, {"tick": 6})
check("eating for eat_food: open while eating", not d.get("intention_history"))
d["activity"] = {"type": "watch_tv"}
H.track(d, {"tick": 50})
check("doing something else: it closes", d.get("intention_history") and d["intention_history"][-1]["ended"] == 50)

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
