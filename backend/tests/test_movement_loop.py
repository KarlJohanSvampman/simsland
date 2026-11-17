"""
Movement is a temporary active loop (core/active_loops.py): only the people who are walking are advanced, from the
moment something sets them off (systems/movement.py::start_moving) until they stop. Nothing scans the population.

Checked here:
  * every place in the backend that sets a character walking goes through start_moving() (a static check, so new code
    can't quietly bypass the loop);
  * a world without a movement loop (an older save) gets its walkers as members once;
  * members who stop, die or disappear leave the loop; the loop costs nothing with no members;
  * the safety sweep picks up (and reports) a walker set off without start_moving().

Run inside the backend container:   python tests/test_movement_loop.py
"""

import os
import re
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


BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── static: nobody sets is_moving = True by hand ─────────────────────────────────────────────────────────────────────
pattern = re.compile(r'\[\s*["\']is_moving["\']\s*\]\s*=\s*True\b|["\']is_moving["\']\s*:\s*True\b')
offenders = []
for root, dirs, files in os.walk(BACKEND):
    dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "frontend", "data")]
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            if pattern.search(line):
                offenders.append(f"{os.path.relpath(path, BACKEND)}:{n}")
# the one allowed place is start_moving() itself
offenders = [o for o in offenders if not o.startswith(os.path.join("systems", "movement.py"))]
check("every walk is started through start_moving()", not offenders, offenders)

# ── the loop ─────────────────────────────────────────────────────────────────────────────────────────────────────────
from core import active_loops
import systems.movement as mv

steps = []
_real = mv.update_character_movement


def fake_update(c, world):
    steps.append(c["id"])
    c["_left"] = c.get("_left", 3) - 1
    if c["_left"] <= 0:
        c["is_moving"] = False


mv.update_character_movement = fake_update
import sim_loop
sim_loop._mark_dirty = lambda world, **k: None
try:
    world = {"characters": {"a": {"id": "a", "is_moving": True}, "b": {"id": "b"}, "c": {"id": "c", "is_moving": True},
                            "npc": {"id": "npc", "is_moving": True, "is_workplace_npc": True}}}
    mv.ensure_movement_members(world)
    check("an older save's walkers join the loop once (workplace NPCs never)",
          active_loops.members(world, "movement") == ["a", "c"], active_loops.members(world, "movement"))
    world["characters"]["c"]["is_moving"] = False      # stopped by something else
    active_loops.run_one(world, "movement")
    check("only members who are still moving are advanced", steps == ["a"], steps)
    check("... a member who stopped leaves the loop", active_loops.members(world, "movement") == ["a"])

    mv.start_moving(world["characters"]["b"], world)
    check("start_moving() makes a member", active_loops.members(world, "movement") == ["a", "b"])
    for _ in range(5):
        active_loops.run_one(world, "movement")
    check("members leave when they arrive", active_loops.members(world, "movement") == [], active_loops.members(world, "movement"))
    n = len(steps)
    for _ in range(100):
        active_loops.run_one(world, "movement")
    check("no members: nothing runs", len(steps) == n)

    mv.start_moving(world["characters"]["a"], world)
    del world["characters"]["a"]
    active_loops.run_one(world, "movement")
    check("a member who is gone leaves the loop", active_loops.members(world, "movement") == [])

    world["characters"]["b"]["is_moving"] = True         # set off by hand, not through start_moving()
    missing = mv.safety_sweep(world)
    check("the safety sweep picks up a walker set off by hand", missing == ["b"] and active_loops.members(world, "movement") == ["b"], missing)
    check("... and finds nothing the second time", mv.safety_sweep(world) == [])
finally:
    mv.update_character_movement = _real

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
