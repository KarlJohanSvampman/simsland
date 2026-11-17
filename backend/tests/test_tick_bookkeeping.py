"""
Per-character bookkeeping that used to be a pass over every character on every tick now happens where it is caused
(docs/distributed_architecture_plan.md, "no component ticks to check"):

  * departure flags (_departed_this_tick / _announced_departure / _previous_location) are cleared at the end of the
    step for exactly the characters that were marked, not by sweeping everyone;
  * a missing week schedule is generated when the character is first seen (load / arrival) or where it is cleared;
  * the story arc follows the newest memories when one is stored.

Run inside the backend container:   python tests/test_tick_bookkeeping.py
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


from systems.incidental_speech import mark_departure, note_announced, clear_departure_flags

# ── departure flags ──────────────────────────────────────────────────────────────────────────────────────────────────
world = {"characters": {i: {"id": i} for i in ("a", "b", "c")}}
clear_departure_flags(world)                                     # an old save: swept once, then only the marked ones
world["characters"]["c"]["_announced_departure"] = True          # set by something that never registered it
clear_departure_flags(world)
check("a world without the list is swept once, not every step", world["characters"]["c"].get("_announced_departure"))

world["characters"]["c"].pop("_announced_departure")
mark_departure(world["characters"]["a"], "house_1", world)
note_announced(world["characters"]["b"], world)
check("marking lists who carries the flags", world.get("_departure_flagged") == ["a", "b"], world.get("_departure_flagged"))
check("... and sets them", world["characters"]["a"].get("_departed_this_tick")
      and world["characters"]["a"].get("_previous_location") == "house_1"
      and world["characters"]["b"].get("_announced_departure"))
clear_departure_flags(world)
leftover = [k for c in world["characters"].values() for k in c if k.startswith(("_departed", "_announced", "_previous"))]
check("the end of the step clears the marked characters", not leftover, leftover)
check("... and the list", "_departure_flagged" not in world)

# ── schedules ────────────────────────────────────────────────────────────────────────────────────────────────────────
import sim_loop

w = {"characters": {"x": {"id": "x"}, "y": {"id": "y"}}, "tick": 0}
first = sim_loop._announce_new_characters(w)
check("the first look after a load returns everyone", first == ["x", "y"], first)
check("... once", sim_loop._announce_new_characters(w) == [])
w["characters"]["z"] = {"id": "z"}
check("a new arrival is returned", sim_loop._announce_new_characters(w) == ["z"])

calls = []
_real_gen, _real_adj = sim_loop.generate_week_schedule, sim_loop.adjust_for_household
sim_loop.generate_week_schedule = lambda c, world: calls.append(c["id"]) or {"week": []}
sim_loop.adjust_for_household = lambda c, world: None
try:
    sim_loop.ensure_schedule(w["characters"]["z"], w)
    sim_loop.ensure_schedule(w["characters"]["z"], w)
    sim_loop.ensure_schedule({"id": "npc", "is_workplace_npc": True}, w)
finally:
    sim_loop.generate_week_schedule, sim_loop.adjust_for_household = _real_gen, _real_adj
check("a missing schedule is generated once; workplace NPCs never get one", calls == ["z"], calls)

# ── story arc ────────────────────────────────────────────────────────────────────────────────────────────────────────
from brain.memory import store_memory

c = {"id": "s", "memories": []}
store_memory(c, "went to the shop", importance=0.9, tick=1)
store_memory(c, "met an old friend", importance=0.9, tick=2)
check("the story arc follows the stored memories", c.get("story_arc", [])[-2:] == ["went to the shop", "met an old friend"],
      c.get("story_arc"))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
