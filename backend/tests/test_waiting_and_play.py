"""
Waiting for someone lasts at most 10 minutes, then the character gives up -- and gives up on what they wanted from that
person (systems/waiting.py). Ringing/knocking at a door starts such a wait. A child's urge to play with a friend ends when
they get together, or lapses after an hour (systems/kids_play.py::settle_play_urges).

Live (2026-11-01): Kathleen Okafor's "play with friend" (Susan Moreau) sat at priority 100, "long overdue", for hours,
while she waited at the door and kept asking.

Run inside the backend container:   python tests/test_waiting_and_play.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from brain import intentions as intents
from systems.action_router import _route_door_signal
from systems.waiting import tick_waiting, start_waiting_for, PERSON_WAIT_MAX_TICKS
from systems.kids_play import settle_play_urges, PLAY_URGE_TTL


def setup(tick=10000):
    world = make_world()
    world["tick"] = tick
    intents.set_current_tick(tick)
    k, s = world["characters"]["kathleen"], world["characters"]["susan"]
    k.update(age=10, x=81, y=11, building_id=None, memories=[], active_intentions=[], activity=None)
    s.update(age=11, memories=[], active_intentions=[], activity=None)
    intents.add_intention(k, {"type": "play_with_friend", "category": "social", "priority": 48, "target_id": "susan",
                              "source": "kids_play", "reason": "Susan Moreau lives close by and you feel like playing"})
    return world, k, s


def run_until(world, c, ticks):
    for _ in range(ticks):
        world["tick"] += 1
        tick_waiting(c, world)


def has_play(c):
    return any(i.get("type") == "play_with_friend" for i in c.get("active_intentions") or [])


# ---- at the door, nobody comes ------------------------------------------------------------------------------------
world, k, s = setup()
_route_door_signal(k, world, {"type": "ring_doorbell", "target": "susan"}, method="ring_doorbell")
check("ringing the doorbell starts a wait at the door", (k.get("_door_wait") or {}).get("target_id") == "susan")
run_until(world, k, PERSON_WAIT_MAX_TICKS - 5)
check("after almost 10 minutes she is still waiting", k.get("_door_wait") and has_play(k))
_route_door_signal(k, world, {"type": "ring_doorbell", "target": "susan"}, method="ring_doorbell")
check("ringing again doesn't make her wait longer",
      k["_door_wait"]["expires_at_tick"] == k["_door_wait"]["started_at_tick"] + PERSON_WAIT_MAX_TICKS)
run_until(world, k, 10)
check("at 10 minutes she gives up", not k.get("_door_wait") and not (k.get("activity") or {}).get("type"))
check("... and gives up on playing with Susan", not has_play(k))
gave = [m["text"] for m in k["memories"] if "gave_up" in (m.get("tags") or [])]
check("... and remembers why", gave == ["I waited for Susan Moreau but nobody came to the door, so I gave up on playing with Susan Moreau."],
      str(gave))
check("... and gets to decide what to do instead", (k.get("cognition") or {}).get("wake_reason") == "gave_up_waiting")

# ---- at the door, Susan comes ------------------------------------------------------------------------------------
world, k, s = setup()
_route_door_signal(k, world, {"type": "knock_on_door", "target": "susan"}, method="knock_on_door")
run_until(world, k, 200)
s.update(x=81, y=10)                                     # Susan comes to the door
run_until(world, k, 1)
check("someone from the house comes to the door: the wait is over", not k.get("_door_wait"))
check("... and she still wants to play", has_play(k))
run_until(world, k, PERSON_WAIT_MAX_TICKS + 50)
check("... and doesn't give up later", has_play(k) and not any("gave_up" in (m.get("tags") or []) for m in k["memories"]))

world, k, s = setup()
_route_door_signal(k, world, {"type": "ring_doorbell", "target": "susan"}, method="ring_doorbell")
k.update(x=84, y=4, building_id="starter_house_3")      # let in
run_until(world, k, 1)
check("being let in ends the wait", not k.get("_door_wait"))

# ---- waiting for someone, the general kind -----------------------------------------------------------------------
world, k, s = setup()
k["traits"] = ["patient"]
k["activity"] = {"type": "wait", "phase": "using", "duration": 1800, "phase_started_tick": world["tick"]}
start_waiting_for(k, world, "person", "susan")
wf = k["activity"]["state"]["waiting_for"]
check("even a patient character waits for a person at most 10 minutes",
      wf["expires_at_tick"] - wf["started_at_tick"] <= PERSON_WAIT_MAX_TICKS, str(wf))
run_until(world, k, PERSON_WAIT_MAX_TICKS + 1)
check("... then stops waiting and gives up on what they wanted from them",
      not (k.get("activity") or {}).get("type") and not has_play(k))

# ---- the urge to play ends ---------------------------------------------------------------------------------------
world, k, s = setup()
settle_play_urges(world)
check("a fresh urge, still apart: kept", has_play(k))
k.update(x=84, y=4, building_id="starter_house_3"); s.update(x=85, y=4)
settle_play_urges(world)
check("together: done", not has_play(k) and any("got to play with Susan Moreau" in m["text"] for m in k["memories"]))

world, k, s = setup()
world["tick"] += PLAY_URGE_TTL
settle_play_urges(world)
check("an hour on and it never happened: dropped", not has_play(k)
      and any("didn't get to play with Susan Moreau" in m["text"] for m in k["memories"]))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
