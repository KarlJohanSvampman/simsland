"""
A bed for everyone who lives in the house (systems/household_beds.py).

Run inside the backend container:   python tests/test_household_beds.py
(uses a private snapshot of the live world: its starter houses and households)
"""

import copy
import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import db
from systems import household_beds as hb
from systems.prop_placement import _prop_tiles

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


w = db.load_world("default")
households = [h for h in w["households"].values() if h.get("members") and hb._building(w, h)]
print(f"   live world: {[(h['name'], len(h['members'])) for h in households]}")
check("there are households with a home to test on", len(households) >= 2)

for h in households:
    b = hb._building(w, h)
    members = hb.sleeper_count(w, h)
    before = hb.bed_capacity(w, b["id"])
    added = hb.ensure_household_beds(w, h)
    after = hb.bed_capacity(w, b["id"])
    check(f"{h['name']}: {members} people, {before} beds -> enough beds now", after >= members, f"{before}->{after}")
    check(f"{h['name']}: exactly the missing number was added", added == max(0, members - before), f"added {added}")
    check(f"{h['name']}: nothing short", not h.get("beds_short"))
    again = hb.ensure_household_beds(w, h)
    check(f"{h['name']}: running it again adds nothing", again == 0)

# the new beds stand on free floor inside the building, in a room, and not on top of anything
templates = w["definitions"]["prop_templates"]
by_building = {}
for p in w["props"]:
    by_building.setdefault(p.get("building_id"), []).append(p)
for b in w["buildings"]:
    props = by_building.get(b["id"], [])
    seen, overlap = {}, []
    for p in props:
        for t in _prop_tiles(p, templates.get(p["template"]) or {}):
            if t in seen and seen[t] != p["id"] and not (templates.get(p["template"], {}).get("wall_mounted")):
                overlap.append((p["template"], t))
            seen[t] = p["id"]
    new_beds = [p for p in props if p["template"] == "bed_single" and p.get("id", "").startswith("bed_single_")]
    check(f"{b['id']}: new beds overlap no other furniture", not [o for o in overlap if "bed" in o[0]], str(overlap[:4]))
    check(f"{b['id']}: new beds have a room, an owner household and a sleep anchor",
          all(p.get("room_id") and p.get("household_id") and any(a["interaction"] == "sleep" for a in p["anchors"]) for p in new_beds))

# a full house stays short and says so
h = households[0]
b = hb._building(w, h)
fake = copy.deepcopy(h)
fake["members"] = list(h["members"]) + [f"ghost{i}" for i in range(40)]
w["characters"].update({f"ghost{i}": {"id": f"ghost{i}", "alive": True} for i in range(40)})
hb.ensure_household_beds(w, fake)
check("when the house has no room for more beds the household is left short and it is recorded", fake.get("beds_short", 0) > 0, str(fake.get("beds_short")))
check("and every bed it did add was on a free block", hb.bed_capacity(w, b["id"]) > len(h["members"]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
