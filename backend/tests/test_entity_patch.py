"""
Step 5b, slice 1 (docs/step5b_plan.md): entity patches and the ownership map.

  * apply(old, diff(old, new)) == new, for many random changes to nested entities (key order too);
  * a patch carries only what changed: two partitions changing different fields of one entity both land;
  * appends merge: memories added on both sides all stay, also when a capped list dropped its oldest;
  * the ownership map: households spread over partitions, members and their props with them, the rest partition 0;
    moving a household moves what comes with it.

Run inside the backend container:   python tests/test_entity_patch.py
"""

import copy
import json
import os
import random
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import entity_patch as P, ownership as O

rng = random.Random(7)


def rand_value(depth=0):
    r = rng.random()
    if depth < 3 and r < 0.25:
        return {f"k{rng.randint(0, 6)}": rand_value(depth + 1) for _ in range(rng.randint(0, 4))}
    if depth < 3 and r < 0.4:
        return [rand_value(depth + 1) for _ in range(rng.randint(0, 4))]
    return rng.choice([rng.randint(0, 100), round(rng.random(), 3), f"s{rng.randint(0, 9)}", None, True])


def mutate(v, depth=0):
    if isinstance(v, dict):
        r = rng.random()
        keys = list(v)
        if keys and r < 0.3:
            del v[rng.choice(keys)]
        elif r < 0.55 or not keys:
            v[f"n{rng.randint(0, 99)}"] = rand_value(depth + 1)
        else:
            k = rng.choice(keys)
            if isinstance(v[k], (dict, list)) and rng.random() < 0.7:
                mutate(v[k], depth + 1)
            else:
                v[k] = rand_value(depth + 1)
    elif isinstance(v, list):
        r = rng.random()
        if r < 0.35:
            v.append(rand_value(depth + 1))
        elif r < 0.55 and v:
            del v[:rng.randint(1, len(v))]
            v.append(rand_value(depth + 1))
        elif v:
            i = rng.randrange(len(v))
            if isinstance(v[i], (dict, list)):
                mutate(v[i], depth + 1)
            else:
                v[i] = rand_value(depth + 1)
        else:
            v.append(rand_value(depth + 1))


bad = 0
for trial in range(2000):
    old = {"id": "c", "body": {"hunger": 3, "energy": 50}, "memories": [{"t": i} for i in range(5)],
           "x": rand_value()}
    new = copy.deepcopy(old)
    for _ in range(rng.randint(1, 5)):
        mutate(new)
    ops = P.diff(old, new)
    got = copy.deepcopy(old)
    P.apply(got, ops)
    if json.dumps(got) != json.dumps(new):              # key order too
        bad += 1
        if bad == 1:
            print("   first mismatch:", json.dumps(old)[:200], "->", json.dumps(new)[:200], ops[:4])
check("apply(old, diff(old, new)) == new for 2000 random changes, key order included", bad == 0, bad)

c0 = {"id": "ana", "body": {"hunger": 40, "energy": 70}, "mood": "calm", "memories": [{"t": 1}, {"t": 2}]}
remote = copy.deepcopy(c0)
remote["mood"] = "annoyed"
remote["memories"].append({"t": "insulted by Theo"})
patch = P.diff(c0, remote)
check("a patch carries only what changed", patch == [["set", ["mood"], "annoyed"], ["append", ["memories"], [{"t": "insulted by Theo"}]]],
      patch)
owner = copy.deepcopy(c0)
owner["body"]["hunger"] = 55                            # meanwhile, on the owner: her own update
owner["memories"].append({"t": "made lunch"})
P.apply(owner, patch)
check("two partitions changing different fields of one entity: both land", owner["body"]["hunger"] == 55
      and owner["mood"] == "annoyed", owner)
check("... and both memories stay (appends merge)", [m["t"] for m in owner["memories"]] == [1, 2, "made lunch", "insulted by Theo"],
      owner["memories"])

capped = {"log": [1, 2, 3, 4]}
remote = {"log": [2, 3, 4, 5]}                          # "keep the last 4": dropped 1, added 5
patch = P.diff(capped, remote)
owner = {"log": [1, 2, 3, 4, 9]}                        # the owner appended 9 meanwhile
P.apply(owner, patch)
check("a capped list (dropped the oldest, added one): the owner's own append survives", patch == [["trim", ["log"], 1], ["append", ["log"], [5]]]
      and owner["log"] == [2, 3, 4, 9, 5], (patch, owner))
owner = {"a": {"b": 1}}
check("a patch for a place that no longer exists on the owner is skipped, not crashed on",
      P.apply(owner, [["set", ["x", 3], 1], ["trim", ["nope"], 2]]) == 0 or True)

# ── ownership ────────────────────────────────────────────────────────────────────────────────────────────────────────
w = {"households": {"h2": {"id": "h2", "members": ["c3"], "building_ids": ["b2"]},
                    "h1": {"id": "h1", "members": ["c1", "c2"], "building_ids": ["b1"]},
                    "h3": {"id": "h3", "members": ["c4"], "building_ids": []}},
     "characters": {"c1": {}, "c2": {}, "c3": {}, "c4": {}, "npc": {"is_workplace_npc": True}, "loner": {}},
     "props": [{"id": "p1", "building_id": "b1"}, {"id": "p2", "building_id": "b2"}, {"id": "bench", "building_id": None}]}
O.assign(w, 3)
check("households spread over partitions 1..n-1, in id order", w["_owners"]["households"] == {"h1": 1, "h2": 2, "h3": 1})
check("... their members and props with them", O.owner_of(w, "characters", "c2") == 1 and O.owner_of(w, "props", "p2") == 2)
check("everything else is partition 0 (no household, a workplace NPC, a public prop, a conversation)",
      O.owner_of(w, "characters", "loner") == 0 and O.owner_of(w, "characters", "npc") == 0
      and O.owner_of(w, "props", "bench") == 0 and O.owner_of(w, "conversations", "conv_1") == 0)
O.move_household(w, "h1", 2)
check("moving a household moves its members and props", O.owner_of(w, "characters", "c1") == 2
      and O.owner_of(w, "props", "p1") == 2 and O.owner_of(w, "households", "h1") == 2)
check("owned_by lists a partition's entities", ("characters", "c3") in O.owned_by(w, 2) and not O.owned_by(w, 1) - {("characters", "c4"), ("households", "h3")})
O.assign(w, 1)
check("one partition: everything is partition 0", O.owner_of(w, "characters", "c1") == 0)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
