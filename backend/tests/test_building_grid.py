"""
Walking buildings without going through walls (systems/building_grid.py, systems/navigation.py), and getting in and
out of them: stepping out from the tile just inside the door, back-yard tiles, doors authored on one side only.

Run:   python tests/test_building_grid.py
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


from systems import building_grid as G
from house_world import make_world
from systems.navigation import plan_character_route, resolve_floorplan, world_to_local, find_building_entrances

# a tiny plan: two rooms side by side, a wall between with a door in it (authored on the left tile only, the right
# tile has a leftover wall on that side), and a front door on the south
W = {"type": "wall"}
D = {"type": "door"}
tiles = {}
for x in range(4):
    for y in range(2):
        tiles[f"{x},{y}"] = {"floor": {"template": "wood"}, "walls": {}}
for x in range(4):
    tiles[f"{x},0"]["walls"]["north"] = W
    tiles[f"{x},1"]["walls"]["south"] = W
tiles["0,0"]["walls"]["west"] = W
tiles["0,1"]["walls"]["west"] = W
tiles["3,0"]["walls"]["east"] = W
tiles["3,1"]["walls"]["east"] = W
tiles["1,0"]["walls"]["east"] = W
tiles["2,0"]["walls"]["west"] = W
tiles["1,1"]["walls"]["east"] = D
tiles["2,1"]["walls"]["west"] = W                  # leftover
tiles["3,1"]["walls"]["south"] = D
fp = {"width": 5, "height": 4, "tiles": tiles}

check("a door on one side beats a leftover wall on the other", G.edge(tiles, (1, 1), (2, 1)) == "door")
check("a wall is a wall", G.edge(tiles, (1, 0), (2, 0)) == "wall")
p = G.path(fp, (0, 0), (3, 0))
check("walking from room to room goes through the door, not the wall", p and (2, 0) not in p[:1] and (1, 1) in [(0, 0)] + p
      and all(G.edge(tiles, a, b) not in ("wall", "window") for a, b in zip([(0, 0)] + p, p)), str(p))
g = G.analyse(fp)
check("the front door is the way out", g["entrances"] == [{"inside": (3, 1), "outside": (3, 2), "side": "south"}], str(g["entrances"]))
tiles["9,9"] = {"floor": None, "walls": {}}
fp2 = {"width": 5, "height": 4, "tiles": dict(tiles, **{"0,0": {"floor": None, "walls": tiles["0,0"]["walls"]}})}
check("a room without a floor, walled in, is still indoors", (0, 0) in G.analyse(fp2)["inside"])

# ---- the real houses ----------------------------------------------------------------------------------------------------
w = make_world()
c = w["characters"]["robert"]
for b in w["buildings"]:
    floorplan = resolve_floorplan(w, b)
    if not floorplan:
        continue
    e = find_building_entrances(b, floorplan)[0]
    c.update(x=e["inside"][0], y=e["inside"][1], building_id=b["id"], path_plans=[], route=[])
    check(f"{b['id']}: standing just inside the door, stepping out onto the doorstep works",
          plan_character_route(w, c, *e["outside"]), str(c["path_plans"][-1]))

b = next(b for b in w["buildings"] if b["id"] == "starter_house_1")
floorplan = resolve_floorplan(w, b)
c.update(x=31, y=4, building_id=b["id"], path_plans=[], route=[])
ok = plan_character_route(w, c, 28, 0)
tiles = floorplan["tiles"]
steps = [t for seg in c.get("route", []) for t in seg["tiles"]]
crossed = [(a, z) for a, z in zip(steps, steps[1:])
           if G.edge(tiles, tuple(world_to_local(b, *a)), tuple(world_to_local(b, *z))) in ("wall", "window")]
check("from inside to the back of the house: a way, and not through a wall", ok and not crossed, str((ok, crossed)))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
