"""
The live 3-household world (2026-11-01), rebuilt offline for tests: the real definitions (/data/simulations/default), the
real buildings at their real positions, the real procedural outdoor grid, and a few of its characters.
"""


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
