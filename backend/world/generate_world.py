import random
from systems.stock_market import init_stocks
from systems.market import init_market_catalog
from systems.personal_items import make_smartphone, make_house_key, make_wallet
import time
from datetime import datetime


def generate_initial_world():

    now = datetime.now()

    world = {

        # =====================================================
        # GLOBAL SIMULATION
        # =====================================================
        "tick": 0,

        "calendar": {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
            "timestamp": time.time()
        },

        "grid": {
            "width": 100,
            "height": 100
        },

        # world_tiles.py::generate_road_gateways() falls back to
        # world["grid"]["width"/"height"] (then a hardcoded 100) when these
        # are unset, but generate_world_tiles() itself defaults to 300 --
        # leaving them unset meant the 300x300 tile field's road-edge
        # gateways only ever landed at x/y==0/99, nowhere near where most
        # of the map actually renders. Setting them explicitly keeps both
        # functions consistent at the same 100x100 field.
        "world_width": 100,
        "world_height": 100,

        # Shared by world_tiles.py::generate_world_tiles() (carves the
        # through-road tile row) and this function's bus-stop placement
        # below -- one source of truth for where the road sits.
        "road_y": 10,

        # =====================================================
        # DEFINITIONS / TEMPLATES
        # =====================================================
        "definitions": {

            # -------------------------------------------------
            # PROP TEMPLATES
            # -------------------------------------------------
            "prop_templates": {

                # ---- SEATING ----
                "modern_sofa": {
                    "name": "Modern Sofa",
                    "category": "furniture",
                    "base_price": 1200.0,
                    "requires_assembly": True,
                    "model": "/resources/props/sofa_modern_a.glb",
                    "footprint": [{"dx": 0, "dy": 0}, {"dx": 1, "dy": 0}, {"dx": 2, "dy": 0}],
                    "interactions": ["sit", "lie"],
                    "anchors": [
                        {"name": "anchor_seat_left",  "interaction": "sit"},
                        {"name": "anchor_seat_right", "interaction": "sit"},
                        {"name": "anchor_lie",        "interaction": "lie"},
                    ]
                },

                "armchair": {
                    "name": "Armchair",
                    "category": "furniture",
                    "base_price": 450.0,
                    "requires_assembly": True,
                    "model": "/resources/props/armchair.glb",
                    "footprint": [{"dx": 0, "dy": 0}],
                    "interactions": ["sit"],
                    "anchors": [{"name": "anchor_seat", "interaction": "sit"}]
                },

                # ---- BEDS ----
                "bed_single": {
                    "name": "Single Bed",
                    "category": "furniture",
                    "base_price": 450.0,
                    "requires_assembly": True,
                    "model": "/resources/props/bed_single.glb",
                    "footprint": [{"dx": 0, "dy": 0}, {"dx": 0, "dy": 1}, {"dx": 1, "dy": 0}, {"dx": 1, "dy": 1}],
                    "interactions": ["sleep", "lie"],
                    "anchors": [{"name": "anchor_sleep", "interaction": "sleep"}]
                },

                "bed_double": {
                    "name": "Double Bed",
                    "category": "furniture",
                    "base_price": 850.0,
                    "requires_assembly": True,
                    "model": "/resources/props/bed_double.glb",
                    "footprint": [{"dx": 0, "dy": 0}, {"dx": 1, "dy": 0}, {"dx": 0, "dy": 1}, {"dx": 1, "dy": 1}],
                    "interactions": ["sleep", "lie"],
                    "anchors": [
                        {"name": "anchor_sleep_left",  "interaction": "sleep"},
                        {"name": "anchor_sleep_right", "interaction": "sleep"},
                    ]
                },

                # ---- TABLES / STORAGE ----
                "coffee_table": {
                    "name": "Coffee Table",
                    "category": "furniture",
                    "base_price": 280.0,
                    "requires_assembly": True,
                    "model": "/resources/props/coffee_table.glb",
                    "footprint": [{"dx": 0, "dy": 0}, {"dx": 1, "dy": 0}],
                    "interactions": ["place_item", "pick_up_item"],
                    "anchors": [{"name": "anchor_surface", "interaction": "place_item"}]
                },

                "bookshelf": {
                    "name": "Bookshelf",
                    "category": "furniture",
                    "base_price": 200.0,
                    "requires_assembly": True,
                    "model": "/resources/props/bookshelf.glb",
                    "footprint": [{"dx": 0, "dy": 0}],
                    "interactions": ["browse", "place_item"],
                    "anchors": [{"name": "anchor_browse", "interaction": "browse"}]
                },

                "desk": {
                    "name": "Desk",
                    "category": "furniture",
                    "base_price": 320.0,
                    "requires_assembly": True,
                    "model": "/resources/props/desk.glb",
                    "footprint": [{"dx": 0, "dy": 0}, {"dx": 1, "dy": 0}],
                    "interactions": ["work", "use_computer"],
                    "anchors": [{"name": "anchor_sit", "interaction": "work"}]
                },

                # ---- APPLIANCES ----
                "television": {
                    "name": "Television",
                    "category": "appliances",
                    "base_price": 600.0,
                    "requires_assembly": False,
                    "model": "/resources/props/television.glb",
                    "footprint": [{"dx": 0, "dy": 0}, {"dx": 1, "dy": 0}],
                    "interactions": ["watch_tv"],
                    "anchors": [
                        {"name": "anchor_watch_left",  "interaction": "watch_tv"},
                        {"name": "anchor_watch_right", "interaction": "watch_tv"},
                    ]
                },

                "microwave": {
                    "name": "Microwave",
                    "category": "appliances",
                    "base_price": 120.0,
                    "requires_assembly": False,
                    "model": "/resources/props/microwave.glb",
                    "footprint": [{"dx": 0, "dy": 0}],
                    "interactions": ["use_microwave"],
                    "anchors": [{"name": "anchor_use", "interaction": "use_microwave"}]
                },

                "fridge": {
                    "name": "Fridge",
                    "category": "appliances",
                    "base_price": 700.0,
                    "requires_assembly": False,
                    "model": "/resources/props/fridge.glb",
                    "footprint": [{"dx": 0, "dy": 0}],
                    "interactions": ["get_food", "store_food"],
                    "anchors": [{"name": "anchor_use", "interaction": "get_food"}]
                },

                "washing_machine": {
                    "name": "Washing Machine",
                    "category": "appliances",
                    "base_price": 550.0,
                    "requires_assembly": False,
                    "model": "/resources/props/washing_machine.glb",
                    "footprint": [{"dx": 0, "dy": 0}],
                    "interactions": ["do_laundry"],
                    "anchors": [{"name": "anchor_use", "interaction": "do_laundry"}]
                },

                # ---- DOORS ----
                "basic_door": {
                    "name": "Basic Door",
                    "category": "doors",
                    "model": "/resources/props/basic_door.glb",
                    "footprint": [{"dx": 0, "dy": 0}],
                    "interactions": ["open_door"],
                    "is_door": True
                }
            },

            # -------------------------------------------------
            # INTERACTION TEMPLATES
            # -------------------------------------------------
            "interaction_templates": {

                "sit": {

                    "full_body": True,

                    "animations": {

                        "start": [
                            "sit_down_01",
                            "sit_down_02"
                        ],

                        "loop": [
                            "sit_idle_01",
                            "sit_idle_02"
                        ],

                        "stop": [
                            "stand_up_01"
                        ]
                    }
                },

                "lie": {

                    "full_body": True,

                    "animations": {

                        "start": [
                            "lie_down_01"
                        ],

                        "loop": [
                            "sleep_idle_01"
                        ],

                        "stop": [
                            "wake_up_01"
                        ]
                    }
                },

                "open_door": {

                    "full_body": False,

                    "animations": {

                        "start": [
                            "open_door_push",
                            "open_door_pull"
                        ],

                        "loop": [],

                        "stop": []
                    }
                },

                "talk": {

                    "full_body": False,

                    "animations": {

                        "loop": [
                            "talk_01",
                            "talk_02",
                            "talk_03"
                        ]
                    }
                }
            },

            # -------------------------------------------------
            # CHARACTER TEMPLATES
            # -------------------------------------------------
            "character_templates": {

                "adult_base": {

                    "model": "/resources/characters/base.glb",

                    "default_animations": {
                        "idle": "idle",
                        "walk": "walk",
                        "run": "run"
                    },

                    "voice": "default",

                    "allowed_interactions": [
                        "sit",
                        "lie",
                        "talk",
                        "open_door"
                    ]
                }
            },

            # -------------------------------------------------
            # TILE TYPES
            # -------------------------------------------------
            "tile_types": {

                "grass": {
                    "walkable": True,
                    "interior": False,
                    "floor":    False
                },

                "road": {
                    "walkable": True,
                    "interior": False,
                    "floor":    False
                },

                "wall": {
                    "walkable": False,
                    "interior": False,
                    "floor":    False
                },

                "water": {
                    "walkable": False,
                    "interior": False,
                    "floor":    False
                },

                "floor": {
                    "walkable": True,
                    "interior": True,
                    "floor":    True
                }
            }
        },

        # =====================================================
        # TILES
        # =====================================================
        "tiles": {},

        # =====================================================
        # WALLS  (keyed by wall_id — see systems/walls.py)
        # load_bearing=True walls cannot be removed
        # =====================================================
        "walls": {
            "wall_house_1_6_0_v": {
                "id":           "wall_house_1_6_0_v",
                "building_id":  "house_1",
                "x":            6,
                "y":            0,
                "orientation":  "v",
                "load_bearing": True,
                "material":     "paint_white_matt",
                "walkable":     False,
                "interior":     True,
            },
            "wall_house_1_6_3_v": {
                "id":           "wall_house_1_6_3_v",
                "building_id":  "house_1",
                "x":            6,
                "y":            3,
                "orientation":  "v",
                "load_bearing": False,
                "material":     "paint_white_matt",
                "walkable":     False,
                "interior":     True,
            },
        },

        # =====================================================
        # CHARACTERS
        # =====================================================
        "characters": {

            "c1": {

                "id": "c1",

                "template": "adult_base",

                "name": "Alex",

                "x": 2,
                "y": 2,

                "rotation": 0,

                "facing": "south",

                # ---------------------------------------------
                # BODY (physical simulation — 0-100)
                # Long-term need weights live in c["lt_needs"]
                # ---------------------------------------------
                "body": {
                    "hunger":             20,
                    "hydration":          80,
                    "bladder":            10,
                    "bowels":              5,
                    "fatigue":            20,
                    "sleep_debt":          0,
                    "hygiene":            85,
                    "odor":                5,
                    "mouth_hygiene":      90,
                    "recent_intake":      30,
                    "stomach_discomfort":  0,
                    "sickness":            0,
                },

                # ---------------------------------------------
                # LONG-TERM NEEDS
                # ---------------------------------------------
                "lt_needs": {},

                # ---------------------------------------------
                # TRAITS
                # ---------------------------------------------
                "traits": [
                    "lazy",
                    "friendly"
                ],

                # ---------------------------------------------
                # HOBBIES
                # List of hobby_template IDs this character practices.
                # Populated by assign_hobbies() on world generation.
                # ---------------------------------------------
                "hobbies": [],

                # ---------------------------------------------
                # AI
                # ---------------------------------------------
                "goal": {
                    "type": "rest"
                },

                "plan": None,

                "task_queue": [],

                "current_task": None,

                # ---------------------------------------------
                # ACTIVITY SYSTEM
                # ---------------------------------------------
                "activity": None,

                "secondary_activity": None,

                # ---------------------------------------------
                # RESERVATIONS
                # ---------------------------------------------
                "reservations": [],

                # ---------------------------------------------
                # NAVIGATION
                # ---------------------------------------------
                "path": [],

                "destination": None,

                # ---------------------------------------------
                # ANIMATION STATE
                # ---------------------------------------------
                "animation_state": {
                    "base": "idle",
                    "upper": None
                },

                # ---------------------------------------------
                # SOCIAL
                # ---------------------------------------------
                "last_utterance": "",

                "conversation_target": None,

                "look_target": None,

                # ---------------------------------------------
                # PERSONAL INVENTORY
                # ---------------------------------------------
                "inventory": []
            }
        },

        # =====================================================
        # PROP INSTANCES
        # =====================================================
        "props": [

            {
                "id": "prop_sofa_1",

                "template": "modern_sofa",

                "x": 5,
                "y": 5,

                "rotation": 0,

                # runtime state only
                "state": {

                    "reserved_by": [],
                    "dirty": False
                }
            }
        ],

        # =====================================================
        # BUILDINGS
        # =====================================================
        "buildings": [

            {
                "id": "house_1",

                "template": "small_house",

                "x": 0,
                "y": 0,

                "rotation": 0,

                "rooms": [

                    {
                        "id": "living_room",

                        "type": "living_room",

                        "bounds": {
                            "x1": 0,
                            "y1": 0,
                            "x2": 6,
                            "y2": 6
                        }
                    }
                ],

                "doors": [

                    {
                        "id": "door_1",

                        "template": "basic_door",

                        "x": 6,
                        "y": 3,

                        "rotation": 0,

                        "state": "closed",

                        "locked": False,

                        "home_id": "house_1",

                        "busy": False,

                        "reserved_by": None,

                        "connects": [
                            "living_room"
                        ]
                    }
                ]
            }
        ]
    }

    init_stocks(world)
    init_market_catalog(world)

    # Seed personal inventories
    c1 = world["characters"]["c1"]
    c1["inventory"] = [
        make_house_key(home_id="house_1", building_id="house_1", owner_id="c1"),
        make_wallet(cash=100.0, owner_id="c1"),
    ]

    # Assign birthdays and starting hobbies to all characters
    from systems.calendar_events import assign_birthday
    from systems.hobbies import assign_hobbies
    for c in world["characters"].values():
        if not c.get("birthday"):
            assign_birthday(c, world)
        if not c.get("hobbies"):
            assign_hobbies(c, world)

    # Seed faction instances from criminal company templates
    from systems.faction_ai import seed_factions_from_companies
    try:
        seed_factions_from_companies(world, _defs_for_families)
    except Exception as e:
        print("[generate_world] faction seed error:", e)

    # Seed family trees for adult characters (probabilistic — ~60% get one)
    from systems.family import generate_family_for_character
    from core.definitions import load_definitions as _ld
    try:
        _defs_for_families = _ld(world.get("sim_id", "default"))
    except Exception:
        _defs_for_families = {}
    for c in list(world["characters"].values()):
        if c.get("age", 0) >= 18 and not c.get("family_id") and random.random() < 0.60:
            try:
                generate_family_for_character(c, world, _defs_for_families, depth=1)
            except Exception:
                pass

    # Social events — seed initial world events
    from systems.social_events import generate_world_events
    world["social_events"] = {}
    generate_world_events(world)

    # Household + garage/car/bus-stop -- generate_initial_world() never
    # created a household before (household_manager.create_household() is
    # otherwise only ever called from the World Editor's admin API), so a
    # freshly generated world had house_1/c1 with no household to own
    # anything. Create one here so "a car belonging to the household" has
    # a household to belong to.
    from systems.household_manager import (
        create_household,
        assign_building_to_household,
        add_member_to_household,
    )
    from systems.vehicles import spawn_household_car, spawn_bus_stop

    world.setdefault("households", {})
    house_1 = world["buildings"][0]
    household = create_household(world, "The " + c1["name"] + " Household")
    assign_building_to_household(world, house_1, household)
    add_member_to_household(world, c1, household)

    spawn_household_car(world, household, house_1)
    spawn_bus_stop(world, world["road_y"])

    return world
