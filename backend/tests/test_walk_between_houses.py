"""
Walking to another household's house ("I hurry toward Susan Moreau's house"), and walking between houses at all.

Live (2026-11-01, the 3-household world): every route from one starter_house to another failed --
  - systems/navigation.py::find_building_entrances() treated every door as a way out (bedroom doors included)
    and one exterior door came out inside-out, and
  - the doorstep just outside a front door is part of the building's plot, so it isn't in the outdoor walking graph:
    a route leaving through a door had nowhere to join the street.
And a house wasn't a target a move could resolve to (systems/room_targets.py::match_building).

Builds the real world offline: the real definitions (/data/simulations/default), the real buildings at their real
positions and the real procedural outdoor grid.

Run inside the backend container:   python tests/test_walk_between_houses.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def make_world():
    from core.definitions import load_definitions
    from systems.building_manager import build_world_geometry
    from world.world_tiles import generate_world_tiles, build_world_tile_lookup
    from systems.outdoor_navigation import build_outdoor_navigation

    world = {
        "tick": 1, "world_width": 100, "world_height": 100, "road_y": 10,
        "definitions": load_definitions("default"),
        "buildings": [
            {"id": "house_1", "x": 0, "y": 0, "rotation": 0, "template": "small_house",
             "address": "100 Placeholder Street", "owner_household_id": None},
            {"id": "starter_house_1", "x": 25, "y": 0, "rotation": 0, "template": "starter_house",
             "address": "102 Placeholder Street", "owner_household_id": "lind"},
            {"id": "starter_house_2", "x": 50, "y": 0, "rotation": 0, "template": "starter_house",
             "address": "104 Placeholder Street", "owner_household_id": "oka"},
            {"id": "starter_house_3", "x": 75, "y": 0, "rotation": 0, "template": "starter_house",
             "address": "106 Placeholder Street", "owner_household_id": "mor"},
        ],
        "props": [],
        "households": {
            "lind": {"id": "lind", "name": "The Lindqvist Household", "members": ["joseph"],
                     "home_id": "starter_house_1", "building_ids": ["starter_house_1"]},
            "oka": {"id": "oka", "name": "The Okafor Household", "members": ["kathleen", "robert"],
                    "home_id": "starter_house_2", "building_ids": ["starter_house_2"]},
            "mor": {"id": "mor", "name": "The Moreau Household", "members": ["susan"],
                    "home_id": "starter_house_3", "building_ids": ["starter_house_3"]},
        },
        "characters": {},
    }
    for cid, first, family, hid, bid, x, y in (
            ("joseph", "Joseph", "Lindqvist", "lind", "starter_house_1", 35, 10),
            ("kathleen", "Kathleen", "Okafor", "oka", "starter_house_2", 59, 4),
            ("robert", "Robert", "Okafor", "oka", "starter_house_2", 60, 8),
            ("susan", "Susan", "Moreau", "mor", "starter_house_3", 83, 5)):
        world["characters"][cid] = {"id": cid, "name": f"{first} {family}", "first_name": first,
                                    "family_name": family, "household_id": hid, "building_id": bid,
                                    "x": x, "y": y, "alive": True}
    build_world_geometry("default", world)
    generate_world_tiles(world)
    build_world_tile_lookup(world)
    build_outdoor_navigation(world)
    return world


world = make_world()
kathleen = world["characters"]["kathleen"]

# ---- navigation between houses -----------------------------------------------------------------------------------
from systems.navigation import find_building_entrances, find_building_at, plan_character_route
from systems.templates import resolve_floorplan

b3 = next(b for b in world["buildings"] if b["id"] == "starter_house_3")
entrances = find_building_entrances(b3, resolve_floorplan(world, b3))
check("a starter_house has exactly its two outside doors as entrances", len(entrances) == 2, str(entrances))
check("each entrance's inside is in the building and its outside isn't",
      all(find_building_at(world, *e["inside"])[0] is b3 and find_building_at(world, *e["outside"])[0] is None
          for e in entrances), str(entrances))
small = next(b for b in world["buildings"] if b["id"] == "house_1")
check("the small_house keeps its one door", len(find_building_entrances(small, resolve_floorplan(world, small))) == 1)
check("the yard/doorstep inside a plot is outdoors", find_building_at(world, 81, 11)[0] is None)
check("a floor tile is in the building", find_building_at(world, 85, 8)[0] is b3)


def route(c, x, y):
    c = dict(c)
    ok = plan_character_route(world, c, x, y)
    return ok, c.get("route") or []


ok, segs = route(kathleen, 56, 4)
check("within a house still works", ok and [s["type"] for s in segs] == ["indoor"])
ok, segs = route(kathleen, 81, 11)
check("from inside one house to the next house's front door", ok and [s["type"] for s in segs] == ["indoor", "outdoor"]
      and segs[-1]["tiles"][-1] == (81, 11), str([(s["type"], s["tiles"][-1]) for s in segs]))
check("... leaving over her own doorstep", ok and segs[1]["tiles"][0] == (56, 11), str(segs[1]["tiles"][:2]))
check("... in steps of one tile",
      ok and all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(segs[1]["tiles"], segs[1]["tiles"][1:])))
ok, segs = route(kathleen, 85, 8)
check("into another house", ok and [s["type"] for s in segs] == ["indoor", "outdoor", "indoor"]
      and segs[-1]["building_id"] == "starter_house_3")
ok, segs = route(world["characters"]["joseph"], 59, 4)
check("from the Lindqvists' to inside the Okafors'", ok and segs[-1]["tiles"][-1] == (59, 4))

# ---- naming a house ----------------------------------------------------------------------------------------------
from systems.room_targets import match_building, building_destination

H1, H2, H3 = "building:starter_house_1", "building:starter_house_2", "building:starter_house_3"
for desc, want in (
        ("Susan Moreau's house", H3),
        ("Susan's place", H3),
        ("over to the Moreaus", H3),
        ("the Moreau house", H3),
        ("the Lindqvist household", H1),
        ("106 Placeholder Street", H3),
        ("Susan Moreau", None),                     # the person, not the house
        ("my house", None),                         # she's already in it
        ("104 Placeholder Street", None),           # her own address -- already there
        ("the shop", None)):
    check(f"Kathleen: {desc!r} -> {want}", match_building(kathleen, world, desc) == want,
          str(match_building(kathleen, world, desc)))

visiting = dict(kathleen, building_id="starter_house_3", x=85, y=8)
check("at the Moreaus', 'home' is her own house", match_building(visiting, world, "time to go home") == H2)
check("... and 'Susan's home' is still Susan's", match_building(visiting, world, "Susan's home") is None)

doors_outside = {tuple(e["outside"]) for e in entrances}
x, y, inside = building_destination(world, kathleen, H3)
check("someone else's house: stand outside one of its doors, not walk in", (x, y) in doors_outside and not inside,
      str((x, y, inside, doors_outside)))
x, y, inside = building_destination(world, visiting, H2)
check("her own home: inside, in the living room", inside and find_building_at(world, x, y)[0]["id"] == "starter_house_2",
      str((x, y, inside)))

# ---- the whole decision: resolve -> validate -> walk -------------------------------------------------------------
from brain.action_resolver import resolve_target
from systems.action_validator import validate_target
from systems.action_router import _route_move

available = {"nearby_characters": [{"id": "robert", "name": "Robert Okafor"}], "interactable_props": []}
r = resolve_target(kathleen, world, "jog_to", "Susan Moreau's house", available)
check("'I hurry toward Susan Moreau's house' resolves to the Moreaus' house", r["id"] == H3, str(r))
r = resolve_target(kathleen, world, "move", "Robert Okafor", available)
check("a person nearby is still the person", r["id"] == "robert", str(r))
check("the validator accepts a house for a move", validate_target(world, {"type": "jog_to", "target": H3}, kathleen))
check("... not for anything else", not validate_target(world, {"type": "interact", "target": H3}, kathleen))

walker = dict(kathleen)
_route_move(walker, world, {"type": "jog_to", "target": H3}, mode="jog")
mt = walker.get("move_target") or {}
check("she sets off", walker.get("is_moving") is True and walker.get("animation_state") == "jog", str(mt))
check("... to the outside of the Moreaus' door", mt.get("target_type") == "building"
      and (mt.get("x"), mt.get("y")) in doors_outside
      and tuple(walker["route"][-1]["tiles"][-1]) == (mt.get("x"), mt.get("y")), str(mt))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
