# =========================================================
# HOBBY REQUIREMENTS
# Defines what each hobby needs: a main prop (by tags),
# consumable/durable items (by resource_type), and behaviour
# flags for examine, put-away, and interruption.
#
# Items:
#   type            — resource_type string
#   min_uses        — minimum uses_remaining to proceed
#   uses_per_session — how many uses are consumed on completion
#   examine         — whether to examine this item pre-hobby
#                     (shows condition / low-uses warning)
#
# Prop state "folded" means the prop needs setup before use.
# =========================================================

HOBBY_REQUIREMENTS = {

    "paint": {
        "main_prop_tags":  ["easel", "art_station"],
        "examine_prop":    True,
        "items": [
            {"type": "PAINT_SET",  "min_uses": 1,  "uses_per_session": 1, "examine": True},
            {"type": "CANVAS",     "min_uses": 1,  "uses_per_session": 1, "examine": False},
            {"type": "ART_BRUSH",  "min_uses": 3,  "uses_per_session": 1, "examine": True},
        ],
        "activity":      "paint",
        "category":      "creative",
        "put_away":      True,
        "interruptible": True,
    },

    "play_guitar": {
        "main_prop_tags":  ["guitar_stand", "instrument_stand", "armchair", "sofa"],
        "examine_prop":    False,
        "items": [
            {"type": "GUITAR",      "min_uses": 1,  "uses_per_session": 1, "examine": True},
            {"type": "GUITAR_PICK", "min_uses": 1,  "uses_per_session": 2, "examine": False},
        ],
        "activity":      "practice_skill",
        "category":      "creative",
        "put_away":      True,
        "interruptible": True,
    },

    "knit": {
        "main_prop_tags":  ["armchair", "sofa", "chair"],
        "examine_prop":    False,
        "items": [
            {"type": "YARN",             "min_uses": 5,  "uses_per_session": 3, "examine": False},
            {"type": "KNITTING_NEEDLES", "min_uses": 1,  "uses_per_session": 0, "examine": True},
        ],
        "activity":      "practice_skill",
        "category":      "craft",
        "put_away":      True,
        "interruptible": True,
    },

    "read_book": {
        "main_prop_tags":  ["armchair", "sofa", "chair", "bed"],
        "examine_prop":    False,
        "items": [
            {"type": "BOOK", "min_uses": 1, "uses_per_session": 1, "examine": False},
        ],
        "activity":      "read_book",
        "category":      "leisure",
        "put_away":      True,
        "interruptible": True,
    },

    "play_video_games": {
        "main_prop_tags":  ["sofa", "gaming_chair", "armchair"],
        "examine_prop":    False,
        "items": [
            {"type": "GAME_CONTROLLER", "min_uses": 1, "uses_per_session": 0, "examine": False},
        ],
        "activity":      "watch_tv",
        "category":      "leisure",
        "put_away":      True,
        "interruptible": True,
    },
}

# Maps activity types the LLM might pick → hobby key
# None means no hobby requirements (proceed directly)
ACTIVITY_TO_HOBBY = {
    "paint":          "paint",
    "play_guitar":    "play_guitar",
    "knit":           "knit",
    "read_book":      "read_book",
    "play_video_games": "play_video_games",
}
