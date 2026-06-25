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

        # =====================================================
        # DEFINITIONS / TEMPLATES
        # =====================================================
        "definitions": {

            # -------------------------------------------------
            # PROP TEMPLATES
            # -------------------------------------------------
            "prop_templates": {

                "modern_sofa": {

                    "name": "Modern Sofa",

                    "category": "seating",

                    "model": "/resources/props/sofa_modern_a.glb",

                    "footprint": [
                        {"dx": 0, "dy": 0},
                        {"dx": 1, "dy": 0},
                        {"dx": 2, "dy": 0}
                    ],

                    "interactions": [
                        "sit",
                        "lie"
                    ],

                    "anchors": [
                        {
                            "name": "anchor_seat_left",
                            "interaction": "sit"
                        },
                        {
                            "name": "anchor_seat_right",
                            "interaction": "sit"
                        },
                        {
                            "name": "anchor_lie",
                            "interaction": "lie"
                        }
                    ]
                },

                "basic_door": {

                    "name": "Basic Door",

                    "category": "doors",

                    "model": "/resources/props/basic_door.glb",

                    "footprint": [
                        {"dx": 0, "dy": 0}
                    ],

                    "interactions": [
                        "open_door"
                    ],

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
                    "walkable": True
                },

                "road": {
                    "walkable": True
                },

                "wall": {
                    "walkable": False
                },

                "water": {
                    "walkable": False
                }
            }
        },

        # =====================================================
        # TILES
        # =====================================================
        "tiles": {},

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
                # NEEDS
                # ---------------------------------------------
                "needs": {

                    "energy": 0.8,
                    "hunger": 0.5,
                    "social": 0.7,
                    "fun": 0.6,
                    "hygiene": 0.9
                },

                # ---------------------------------------------
                # TRAITS
                # ---------------------------------------------
                "traits": [
                    "lazy",
                    "friendly"
                ],

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

                "look_target": None
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

    return world