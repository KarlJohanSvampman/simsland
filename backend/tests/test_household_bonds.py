"""
Housemates who are kin start out close (systems/household_bonds.py), through family.sync_kinship_to_relationships.

Run inside the backend container:   python tests/test_household_bonds.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import household_bonds as hb
from systems.family import _new_family, _set_relation, _add_member, sync_kinship_to_relationships

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, household, age=30):
    return {"id": cid, "name": cid.title(), "age": age, "household_id": household, "relationships": {}, "memories": [], "alive": True}


def world_with(*chars):
    return {"tick": 1000, "characters": {c["id"]: c for c in chars}}


mum, dad, kid, kid2, gran = person("mum", "h1", 36), person("dad", "h1", 38), person("kid", "h1", 9), person("kid2", "h1", 6), person("gran", "h2", 70)
w = world_with(mum, dad, kid, kid2, gran)
fam = _new_family("Test")
for c in (mum, dad, kid, kid2, gran):
    _add_member(fam, c["id"])
_set_relation(fam, "mum", "dad", "spouse")
_set_relation(fam, "mum", "kid", "parent")
_set_relation(fam, "dad", "kid", "parent")
_set_relation(fam, "kid", "kid2", "sibling")
_set_relation(fam, "gran", "mum", "parent")
sync_kinship_to_relationships(fam, w)


def r(a, b):
    return a["relationships"][b["id"]]


check("a couple living together are close", r(mum, dad)["familiarity"] >= 90 and r(mum, dad)["trust"] >= 70 and r(mum, dad)["friendship"] >= 65, str(r(mum, dad)))
check("a parent knows and trusts their child", r(mum, kid)["familiarity"] >= 90 and r(mum, kid)["friendship"] >= 60)
check("a child is attached to their parent", r(kid, mum)["comfort"] >= 65 and r(kid, mum)["trust"] >= 65)
check("siblings are close, a bit less", r(kid, kid2)["friendship"] >= 45 and r(kid, kid2)["friendship"] < r(kid, mum)["friendship"])
check("they read as people with a history", r(mum, kid)["interaction_count"] >= 50)
check("kinship is still stamped", r(mum, kid)["kinship"] == "parent" and r(kid, mum)["kinship"] == "child" and "spouse" in r(mum, dad)["labels"])
check("kin in another household are left as they were", r(gran, mum).get("familiarity", 0) < 10 and "bonded" not in r(gran, mum))

r(mum, kid)["friendship"] = 5            # a bad year
sync_kinship_to_relationships(fam, w)
check("a second stamp doesn't undo a falling-out", r(mum, kid)["friendship"] == 5)

mum2, kid3 = person("mum2", "h3"), person("kid3", "h3")
mum2["relationships"]["kid3"] = {"familiarity": 100, "trust": 99, "friendship": 98, "comfort": 97}
w2 = world_with(mum2, kid3)
f2 = _new_family("T2")
_add_member(f2, "mum2"); _add_member(f2, "kid3")
_set_relation(f2, "mum2", "kid3", "parent")
sync_kinship_to_relationships(f2, w2)
check("nothing is ever lowered", mum2["relationships"]["kid3"]["friendship"] == 98 and mum2["relationships"]["kid3"]["trust"] == 99)

ex1, ex2 = person("ex1", "h4"), person("ex2", "h4")
f3 = _new_family("T3")
_add_member(f3, "ex1"); _add_member(f3, "ex2")
_set_relation(f3, "ex1", "ex2", "ex_spouse")
w3 = world_with(ex1, ex2)
sync_kinship_to_relationships(f3, w3)
check("an ex-spouse is not bonded", ex1["relationships"]["ex2"].get("familiarity", 0) < 10)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
