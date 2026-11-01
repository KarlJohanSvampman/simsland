"""
New families, each with a house of their own (systems/household_generation.py).

Run inside the backend container:   python tests/test_household_generation.py
(builds a fresh generated world in memory; nothing is saved)
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from world.generate_world import generate_initial_world
from systems.building_manager import build_world_geometry
from systems.household_generation import generate_households
from systems.navigation import find_building_at

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


w = generate_initial_world()
build_world_geometry("default", w)

r = generate_households(w, "default", count=3, members=3)
check("three households were made", r["made"] == 3, str(r["made"]))

for h in r["households"]:
    hh = w["households"][h["household_id"]]
    b = next(b for b in w["buildings"] if b["id"] == h["building_id"])
    check(f"{h['name']} ({h['kind']}): three members", len(hh["members"]) == 3)
    check(f"{h['name']}: owns its house and lives there", b["owner_household_id"] == hh["id"] and hh["home_id"] == b["id"])
    firsts = [w["characters"][m]["first_name"] for m in hh["members"]]
    check(f"{h['name']}: nobody shares a first name {firsts}", len(set(firsts)) == len(firsts))
    for m in hh["members"]:
        c = w["characters"][m]
        inside, _ = find_building_at(w, c["x"], c["y"])
        check(f"  {c['name']} ({c['age']}) stands inside their house", inside and inside["id"] == b["id"] and c.get("building_id") == b["id"])
        check(f"  {c['name']} has a house key and a schedule",
              any(i.get("home_id") == hh["id"] for i in c["inventory"]) and c.get("schedule"))
        rels = c.get("relationships", {})
        check(f"  {c['name']} is kin to everyone they live with",
              all((rels.get(o) or {}).get("kinship") for o in hh["members"] if o != m))
        for o in hh["members"]:
            if (rels.get(o) or {}).get("kinship") == "parent":
                check(f"  {c['name']} is at least 18 years older than their child",
                      c["age"] - w["characters"][o]["age"] >= 18)
            if (rels.get(o) or {}).get("kinship") == "spouse":
                check(f"  {c['name']}'s spouse carries the spouse label", "spouse" in rels[o].get("labels", []))
    beds = [p for p in w["props"] if p.get("building_id") == b["id"]
            and any(a.get("interaction") == "sleep" for a in p.get("anchors", []))]
    check(f"{h['name']}: a bed for everyone", len(beds) >= 3, str(len(beds)))
    check(f"{h['name']}: the house is off the road", not (b["y"] <= w["road_y"] + 1 < b["y"] + 21))

rects = [(b["id"], b["x"], b["y"]) for b in w["buildings"]]
overlaps = [(a[0], o[0]) for i, a in enumerate(rects) for o in rects[i + 1:]
            if a[1] < o[1] + 20 and o[1] < a[1] + 20 and a[2] < o[2] + 20 and o[2] < a[2] + 20]
check("no two buildings overlap", not overlaps, str(overlaps))

r2 = generate_households(w, "default", count=40, members=3)
check("a full map stops making houses and says so", r2["out_of_room"] and r2["made"] < 40, str(r2["made"]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
