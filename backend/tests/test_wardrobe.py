"""
Clothes (systems/wardrobe.py): everyone owns some, wears them awake and pyjamas asleep, and the laundry gets done.

Run inside the backend container:   python tests/test_wardrobe.py
"""
import json, os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

defs_path = next(p for p in ("../simulations/default/definitions.json", "/data/simulations/default/definitions.json")
                 if os.path.exists(p))
defs = json.load(open(defs_path))
from systems import wardrobe as W
import brain.intentions as I

def man(cid="m", age=36, job="Host", hh="h1"):
    return {"id": cid, "name": "Anthony", "age": age, "sex": "male", "model": "adult_male", "occupation": job,
            "household_id": hh, "building_id": "home1", "inventory": [], "active_intentions": [], "activity": None}

w = {"tick": 1000, "definitions": defs, "characters": {}, "households": {"h1": {"id": "h1", "home_id": "home1", "members": []}}}
a = man(); w["characters"]["m"] = a; w["households"]["h1"]["members"].append("m")

# A. a starter wardrobe
closet = W.ensure_closet(w, a)
tids = [i["template_id"] for i in closet]
check("A: underwear, tops, bottoms, shoes, pyjamas", all(any(i["slot"] == s for i in closet) for s in ("underwear", "torso", "legs", "feet"))
      and "pyjama_bottoms" in tids, tids)
check("A: adult men get the jeans that have a model", "boot_jeans" in tids, tids)
check("A: a working adult has a smart set", "shirt_dress" in tids and "shoes_dress" in tids, tids)
check("A: stocked once", len(W.ensure_closet(w, a)) == len(closet))
girl = {"id": "g", "age": 8, "sex": "female", "model": "female_child_base", "occupation": "none"}
check("A: no boot_jeans for a girl", "boot_jeans" not in W.starter_kit(w, girl))

# B. dressing
a["worn"] = {}; a["is_nude"] = True
W.check(w, a)
check("B: nude and awake -> dressed", not a["is_nude"] and a["worn"].get("legs") and a["worn"].get("torso"), a.get("worn"))
check("B: in day clothes, not pyjamas", not W._wearing_sleepwear(a))
a["activity"] = {"type": "sleep"}
W.check(w, a)
check("B: asleep -> pyjamas", W._wearing_sleepwear(a), a["worn"].get("legs"))
a["activity"] = None
W._on_ended({"character_id": "m", "activity_type": "sleep"}, w)
check("B: up -> dressed for the day", not a["is_nude"] and not W._wearing_sleepwear(a))
check("B: the prompt says what they wear", "You're wearing" in W.prompt_line(w, a), W.prompt_line(w, a))

woman = {"id": "f", "name": "Rebecca", "age": 34, "sex": "female", "model": "adult_female", "occupation": "Crane Operator",
         "household_id": "h1", "building_id": "home1", "inventory": [], "active_intentions": [], "activity": {"type": "sleep"},
         "worn": {}, "is_nude": True}
W.check(w, woman)
check("B: a woman sleeps in underwear and pyjamas too", woman["worn"].get("underwear") and W._wearing_sleepwear(woman),
      {k: (v or {}).get("template_id") for k, v in woman["worn"].items() if v})

# C. leave them be
W.undress_to_closet(w, a)
a["active_intercourse_session_id"] = "x"
W.check(w, a)
check("C: not in an intimate moment", a["is_nude"])
a.pop("active_intercourse_session_id")
a["_undressed_on_purpose_until"] = w["tick"] + 100
W.check(w, a)
check("C: not right after undressing on purpose", a["is_nude"])
a["_undressed_on_purpose_until"] = 0
W.check(w, a)

# D. laundry
for item in a["closet"]:
    item["dirty"] = True
check("D: out of clean clothes -> laundry needed", W.needs_laundry(w, w["households"]["h1"]))
who = W.raise_laundry(w, w["households"]["h1"])
check("D: an adult at home gets the chore", who is a and any(i["type"] == "do_laundry" for i in a["active_intentions"]))
W.raise_laundry(w, w["households"]["h1"])
check("D: only once", sum(i["type"] == "do_laundry" for i in a["active_intentions"]) == 1)
from systems.strategy import resolve_strategy
check("D: the chore means the washing machine", resolve_strategy(a, w, {"type": "do_laundry"}) == "do_laundry_fill")
W.launder_closets(w, w["households"]["h1"])
check("D: a finished load cleans the closet", not any(i.get("dirty") for i in a["closet"]))
check("D: and the chore is done", not any(i["type"] == "do_laundry" for i in a["active_intentions"]))
w["household_processes"] = [{"type": "laundry", "household_id": "h1"}]
check("D: no second load while one is running", W._laundry_running(w, w["households"]["h1"]))

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
