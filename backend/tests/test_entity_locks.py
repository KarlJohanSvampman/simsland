"""
Per-entity locks (core/entity_locks.py, ENTITY_LOCKS=on): the tick's step and declared commands share the world and lock
entities as they reach them; everything else takes the world exclusively. Checked here, with real threads:

  * the read/write world lock: shared holders run together, exclusive waits for them, a waiting writer goes first;
  * a declared command on another entity runs WHILE a step runs; one on an entity the step holds waits for it;
  * a lock cycle (the step holds A, a command holds B and reaches A, the step then reaches B) aborts the command with
    LockConflict, never the step, and the step carries on;
  * exclusive access (db._world_lock) waits for the step to end.

Run inside the backend container:   python tests/test_entity_locks.py
"""

import os
import sys
import threading
import time

os.environ.setdefault("COGNITION_MODE", "local")
os.environ["ENTITY_LOCKS"] = "on"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import entity_locks as EL, world_view as WV

check("ENTITY_LOCKS=on is picked up", EL.ENABLED)

# ── the read/write lock ──────────────────────────────────────────────────────────────────────────────────────────────
rw = EL._RW()
log = []
rw.acquire_shared()
t = threading.Thread(target=lambda: (rw.acquire_shared(), log.append("shared2"), rw.release_shared()))
t.start(); t.join(1)
check("two shared holders run together", log == ["shared2"])
got = []
tw = threading.Thread(target=lambda: (rw.acquire_exclusive(), got.append("x"), rw.release_exclusive()))
tw.start(); time.sleep(0.05)
check("exclusive waits for a shared holder", got == [])
late = []
tl = threading.Thread(target=lambda: (rw.acquire_shared(), late.append(time.monotonic()), rw.release_shared()))
tl.start(); time.sleep(0.05)
check("... and a new shared holder waits behind the waiting writer", late == [])
rw.release_shared()
tw.join(1); tl.join(1)
check("released: the writer, then the reader", got == ["x"] and len(late) == 1)

# ── entity locks with a WorldView world ──────────────────────────────────────────────────────────────────────────────
world = WV.install({"characters": {"a": {"id": "a"}, "b": {"id": "b"}, "c": {"id": "c"}}, "tick": 1}, "locks_test")
in_step, end_step, step_done = threading.Event(), threading.Event(), threading.Event()
step_log = []


def step(touch_after=None):
    with EL.tick_unit():
        world["characters"]["a"]["x"] = 1           # the step reaches a
        in_step.set()
        end_step.wait(2)
        if touch_after:
            world["characters"][touch_after]["y"] = 1
            step_log.append("reached " + touch_after)
    step_done.set()


T = threading.Thread(target=step); T.start()
in_step.wait(1)
t0 = time.monotonic()
with EL.command_unit([("characters", "b")]):
    world["characters"]["b"]["z"] = 1
ran_during = not step_done.is_set()
check("a declared command on another entity runs while the step runs", ran_during and time.monotonic() - t0 < 0.5)
waited = []


def cmd_a():
    t1 = time.monotonic()
    with EL.command_unit([("characters", "a")]):
        waited.append(step_done.is_set())


Ta = threading.Thread(target=cmd_a); Ta.start()
time.sleep(0.1)
check("a command on an entity the step holds waits ...", waited == [])
end_step.set(); T.join(2); Ta.join(2)
check("... until the step ends", waited == [True], waited)

# ── a lock cycle: the command is aborted, the step carries on ────────────────────────────────────────────────────────
in_step.clear(); end_step.clear(); step_done.clear()
T = threading.Thread(target=step, kwargs={"touch_after": "c"}); T.start()
in_step.wait(1)
result = []


def cmd_cycle():
    try:
        with EL.command_unit([("characters", "c")]):
            time.sleep(0.05)
            world["characters"]["a"]["w"] = 1        # undeclared, held by the step: waits
            result.append("ran")
    except EL.LockConflict as exc:
        result.append("conflict")


Tc = threading.Thread(target=cmd_cycle); Tc.start()
time.sleep(0.1)
end_step.set()                                       # the step now reaches c, which the command holds: a cycle
T.join(3); Tc.join(3)
check("in a lock cycle the command is aborted ...", result == ["conflict"], result)
check("... and the step carries on", step_log == ["reached c"] and step_done.is_set(), step_log)
check("... counted", EL.stats()["conflicts"] >= 1 and EL.stats()["undeclared"] >= 1, EL.stats())

# ── exclusive waits for the step ─────────────────────────────────────────────────────────────────────────────────────
in_step.clear(); end_step.clear(); step_done.clear()
T = threading.Thread(target=step); T.start()
in_step.wait(1)
lock = EL.lock()
excl = []
Tx = threading.Thread(target=lambda: (lock.acquire(), excl.append(step_done.is_set()), lock.release()))
Tx.start(); time.sleep(0.1)
check("exclusive access waits while a step runs", excl == [])
end_step.set(); T.join(2); Tx.join(2)
check("... and gets in after it", excl == [True], excl)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
