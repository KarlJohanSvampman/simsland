"""
Children with friends nearby want to play with them (systems/kids_play.py).

Run inside the backend container:   python tests/test_kids_play.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import kids_play as kp
from systems import neighbours as nb

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def kid(cid, age, household, **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "household_id": household, "hobbies": ["football"], "traits": [],
         "memories": [], "relationships": {}, "alive": True, "body": {"hunger": 20, "hydration": 80}, "active_intentions": []}
    d.update(extra)
    return d


def town(*chars, hour=14, weekday="saturday"):
    homes = {"h1": (0, 0), "h2": (25, 0), "h3": (30, 10)}
    return {"tick": 100000, "calendar": {"hour": hour, "minute": 0, "weekday": weekday}, "characters": {c["id"]: c for c in chars},
            "households": {h: {"id": h} for h in homes},
            "buildings": [{"id": f"b_{h}", "x": x, "y": y, "owner_household_id": h} for h, (x, y) in homes.items()]}


def intention(c):
    return next((i for i in c["active_intentions"] if i["type"] == "play_with_friend"), None)


random.seed(1)
kp.PLAY_CHANCE = 1.0

# ---- the basic urge ----------------------------------------------------------------------------------------------------------
lia, mo = kid("lia", 7, "h1"), kid("mo", 8, "h2")
w = town(lia, mo)
nb.seed_neighbour_ties(w, lia)
check("the street made them friends", "mo" in nb._friends(lia))
kp.tick_kids_play(w)
i = intention(lia)
check("a free child with a free friend wants to play with them", i is not None and i["target_id"] == "mo", str(i))
check("it is a social intention aimed at the friend, with a reason naming them", i["category"] == "social" and "Mo" in i["reason"])
check("the friend wants it too", intention(mo) is not None and intention(mo)["target_id"] == "lia")
check("it is logged against that friend", lia["_play_log"]["mo"] == 100000)

# ---- cooldown ------------------------------------------------------------------------------------------------------------------
lia["active_intentions"].clear()
w["tick"] += kp.PLAY_COOLDOWN - 10
kp.tick_kids_play(w)
check("not suggested again during the cooldown", intention(lia) is None)
w["tick"] += 20
kp.tick_kids_play(w)
check("but again once it has passed", intention(lia) is not None)

# ---- who is left out ---------------------------------------------------------------------------------------------------------------
def fresh(**over_lia):
    a, b = kid("a", 7, "h1", **over_lia), kid("b", 8, "h2")
    return a, b, town(a, b)

def wants(a, b, w, mutate=None):
    nb.seed_neighbour_ties(w, a)
    if mutate:
        mutate(a, b, w)
    kp.tick_kids_play(w)
    return intention(a) is not None

a, b, w = fresh()
check("baseline", wants(a, b, w))
a, b, w = fresh()
check("not at night", not wants(a, b, w, lambda a, b, w: w["calendar"].update(hour=22)))
a, b, w = fresh()
check("not before the morning", not wants(a, b, w, lambda a, b, w: w["calendar"].update(hour=6)))
a, b, w = fresh()
check("not while doing something", not wants(a, b, w, lambda a, b, w: a.update(activity={"type": "homework"})))
a, b, w = fresh()
check("not when the friend is busy", not wants(a, b, w, lambda a, b, w: b.update(activity={"type": "sleep"})))
a, b, w = fresh()
check("not when the friend is away", not wants(a, b, w, lambda a, b, w: b.update(off_grid=True)))
a, b, w = fresh()
check("not when the friend is at school", not wants(a, b, w, lambda a, b, w: b.update(
    schedule={"week": {"saturday": [{"start": "00:00", "end": "23:59", "activity": "school"}]}})))
a, b, w = fresh()
check("not when starving", not wants(a, b, w, lambda a, b, w: a["body"].update(hunger=95)))
a, b, w = fresh()
check("not when parched", not wants(a, b, w, lambda a, b, w: a["body"].update(hydration=5)))
a, b, w = fresh()
check("not if the friend is a grown-up", not wants(a, b, w, lambda a, b, w: b.update(age=30)))
a, b, w = fresh()
check("not for a toddler", not wants(a, b, w, lambda a, b, w: a.update(age=2)))
a, b, w = fresh()
check("not for a grown-up", not wants(a, b, w, lambda a, b, w: a.update(age=40)))
a, b, w = fresh()
check("not with someone they only know in passing", not wants(a, b, w, lambda a, b, w: a["relationships"]["b"].update(friendship=3)))
a, b, w = fresh()
check("not with their own sibling (kin)", not wants(a, b, w, lambda a, b, w: a["relationships"]["b"].update(kinship="sibling")))

# ---- with several friends, the closest free one ------------------------------------------------------------------------------------
a, b, c3 = kid("a", 7, "h1"), kid("b", 8, "h2"), kid("c", 7, "h3")
w = town(a, b, c3)
nb.seed_neighbour_ties(w, a)
a["relationships"]["b"]["friendship"] = 20
a["relationships"]["c"]["friendship"] = 40
kp.tick_kids_play(w)
check("the closest friend is chosen", intention(a)["target_id"] == "c", str(intention(a)))
a["active_intentions"].clear()
w["tick"] += 60
c3["activity"] = {"type": "bath"}
a["_play_log"] = {}
kp.tick_kids_play(w)
check("and when they are busy, the next friend", intention(a)["target_id"] == "b", str(intention(a)))

# ---- chance ----------------------------------------------------------------------------------------------------------------------------
kp.PLAY_CHANCE = 0.0
a, b, w = fresh()
check("the urge doesn't come to every child at every check", not wants(a, b, w))
kp.PLAY_CHANCE = 1.0

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
