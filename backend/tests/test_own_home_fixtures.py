"""
Toilets, stoves and fridges are used at home (live 2026-11-24: every fixture in the starter houses had no household_id,
so all of them counted as public, and characters walked to the neighbours' to use the toilet or cook).

A. A fixture's owner comes from the home it stands in when the prop has none.
B. Own home's, public, or the home they're a welcome guest in now -- not anyone else's.
C. The search for a fixture never picks the neighbours'.
D. Naming someone else's toilet directly doesn't use it; they're told.

Run inside the backend container:   python tests/test_own_home_fixtures.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from systems import props as P

def toilet(pid, bid, x):
    return {"id": pid, "template": "toilet_a", "building_id": bid, "household_id": None, "x": x, "y": 0,
            "anchors": [{"name": "seat", "interaction": "use_toilet", "dx": 0, "dy": 0}]}

w = {"tick": 1, "households": {"hA": {"id": "hA", "home_id": "house_A"}, "hB": {"id": "hB", "home_id": "house_B"}},
     "props": [toilet("tA", "house_A", 50), toilet("tB", "house_B", 2), toilet("tPark", "park", 80)]}
P.get_world_anchor = lambda prop, anchor: {"x": prop["x"], "y": prop["y"]}
me = {"id": "me", "household_id": "hA", "x": 0, "y": 0, "building_id": None}

check("A: owner from the home it stands in", P.owner_household_id(w, w["props"][1]) == "hB")
check("A: a park fixture is public", P.owner_household_id(w, w["props"][2]) is None)
check("B: own home's -> yes", P.may_use_fixture(me, w, w["props"][0]))
check("B: the neighbours' -> no", not P.may_use_fixture(me, w, w["props"][1]))
me_guest = dict(me, building_id="house_B", guest_visit={"status": "welcome", "household_id": "hB"})
check("B: a welcome guest in their home -> yes", P.may_use_fixture(me_guest, w, w["props"][1]))
me_uninvited = dict(me_guest, guest_visit={"status": "uninvited", "household_id": "hB"})
check("B: walked in uninvited -> no", not P.may_use_fixture(me_uninvited, w, w["props"][1]))

found = P.find_nearest_household_anchor(me, w, "use_toilet", "hA")
check("C: the nearest toilet is next door, but their own is the one found", found and found[0]["id"] == "tA",
      found and found[0]["id"])

from systems import action_router as ar
import brain.cognition_scheduler as cs
told = []
cs.wake_character = lambda c, world, reason, payload=None, delay=0: told.append(reason)
w["definitions"] = {}
me2 = dict(me_uninvited, activity=None)
ar._route_interact(me2, w, {"target": "tB"}, {})
check("D: naming the neighbours' toilet doesn't use it", not me2.get("activity") and told == ["cant_talk"], (me2.get("activity"), told))

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
