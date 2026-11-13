"""
Turn-taking (systems/conversation_floor.py) and conversation endings (systems/conversation_outcome.py) run as the
"floor" active loop (core/active_loops.py): only live spoken conversations are looked at, nothing at all while nobody
is talking, and a conversation leaves the loop when it ends -- by whatever path.

Run inside the backend container:   python tests/test_floor_loop.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import active_loops
from brain.conversations import create_conversation, reopen_conversation
import systems.conversation_floor as cf

world = {"tick": 10, "characters": {i: {"id": i, "name": i.title(), "x": 0, "y": 0} for i in ("a", "b", "c")},
         "conversations": {}}
spoken = create_conversation(world, ["a", "b"], medium="in_person")
text = create_conversation(world, ["a", "c"], medium="text")
check("a spoken conversation joins the floor loop when it is made", active_loops.members(world, "floor") == [spoken["id"]],
      active_loops.members(world, "floor"))
check("... a text conversation does not", text["id"] not in active_loops.members(world, "floor"))

world["characters"]["a"]["floor_status"] = "waiting_for_reply"
world["_floor_status_ids"] = ["a"]
spoken["active"] = False                        # ended somewhere else (an action route, the idle timer, ...)
active_loops.run_one(world, "floor")
check("a conversation that ended elsewhere leaves the loop", active_loops.members(world, "floor") == [])
check("... and its cues are cleared", world["characters"]["a"].get("floor_status") is None)

steps = active_loops.stats()["floor"]["steps"]
for _ in range(50):
    active_loops.run_one(world, "floor")
check("nobody talking: the loop does not run", active_loops.stats()["floor"]["steps"] == steps)

reopen_conversation(world, spoken)
check("a reopened conversation joins again", active_loops.members(world, "floor") == [spoken["id"]])

old = {"tick": 1, "characters": {"x": {"id": "x", "floor_status": "thinking"}},
       "conversations": {"k": {"id": "k", "active": True, "medium": "call", "participants": ["x"]}}}
cf.ensure_floor_members(old)
check("an older save's live calls join once; stale cues are cleared",
      active_loops.members(old, "floor") == ["k"] and old["characters"]["x"]["floor_status"] is None)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
