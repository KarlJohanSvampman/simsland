"""
Step 5b, slice 3c (docs/step5b_plan.md): the server side of partitions -- what main.py and core/world_state.py do with
SIM_PARTITIONS / SIM_PARTITION.

  * SIM_PARTITIONS unset: nothing changes (one process is the core; it persists everything);
  * a partition process: its node is made from the world as loaded, the owner map the same in every partition;
  * it persists only what it owns (partition 0 also the manifest and the bookkeeping keys);
  * only partition 0 is the core: commands, the gateway replica, the backup blob.

Run inside the backend container:   python tests/test_partition_server.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import ownership, partitions as P


def world():
    return {"households": {"h1": {"id": "h1", "members": ["a"], "building_ids": []},
                           "h2": {"id": "h2", "members": ["b"], "building_ids": []}},
            "characters": {"a": {"id": "a"}, "b": {"id": "b"}, "z": {"id": "z"}}, "props": [], "timers": [],
            "incidents": [], "tick": 1}


check("SIM_PARTITIONS unset: one process, the core, persisting everything",
      P.SERVER_N == 1 and P.is_core() and P.persists(world(), ("characters", "a")))

P.SERVER_N, P.SERVER_P = 3, 2
w = world()
node = P.server_node(w, "srvtest")
check("a partition process: its node, the owner map made from the world as loaded",
      node.id == 2 and not node.lockstep and w["_owners"]["n"] == 3 and ownership.owner_of(w, "characters", "b") == 2)
w2 = world()
ownership.assign(w2, 3)
check("... the same map any partition makes on its own (no coordination needed)", w2["_owners"] == w["_owners"])
check("it persists only what it owns", P.persists(w, ("characters", "b")) and not P.persists(w, ("characters", "a"))
      and not P.persists(w, ("characters", "z")) and not P.persists(w, ("key", "incidents"))
      and not P.persists(w, ("meta", "manifest")))
check("... and is not the core (no commands, no gateway replica, no backup blob)", not P.is_core())
P.SERVER_P = 0
check("partition 0 persists the rest: unowned characters, world keys, the manifest; it is the core",
      P.persists(w, ("characters", "z")) and P.persists(w, ("key", "incidents")) and P.persists(w, ("meta", "manifest"))
      and not P.persists(w, ("characters", "b")) and P.is_core())
src = open("main.py").read()
check("main.py steps through the partition node and gates the replica and the command consumer on the core",
      "_parts.server_node(world, sim_id).tick(tick)" in src and src.count("if _parts.is_core():") >= 3)
P.SERVER_N, P.SERVER_P = 1, 0

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
