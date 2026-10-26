"""
systems/vision.py -- how far a character can see, as one of four levels.

    Vision.NORMAL       sees a face from `normal_m` metres (the recognition distance)
    Vision.EXCEPTIONAL  sees a face from `exceptional_m` metres
    Vision.IMPAIRED     sees a face from `impaired_m` metres (short-sighted, or old eyes without their glasses)
    Vision.BLIND        sees nothing (no one is generated blind: it is a state for accidents and disease, kept for them)

A character's `vision` is their NATURAL level, without glasses. Wearing glasses lifts an impaired character to normal
(`effective_level`). From their forties on, a good share of grown-ups are impaired by nature (`random_vision`) and most of
those own glasses; whoever has none (or has taken them off to sleep or shower) sees at the impaired range.

Two distances per level, both from the settings: the RECOGNITION range is where a face can still be told (that is the old "visible
people": they are recognised, named, remembered); out to `detect_factor` times as far (twice, by default) a person can still be made
out AT ALL, with less and less detail the further it is -- first a figure (a man, a child, walking, standing), then just a shape
(`detail_tier`). Those are the glimpsed people (brain/perception.py::perceive_glimpsed), who are never named.

Settings are world["settings"]["vision"], set from the admin (GET/POST /admin/vision) in metres; `tile_meters` says how long a tile is.
Indoors and at night the ranges are shortened by the same factors the old visual range used.
"""

import math

DEFAULTS = {
    "tile_meters": 1.0,
    "normal_m": 20.0,          # placeholders until the real distances are chosen (the settings screen sets them)
    "exceptional_m": 40.0,
    "impaired_m": 6.0,
    "detect_factor": 2.0,
}
LIMITS = {"tile_meters": (0.1, 10.0), "normal_m": (0.0, 500.0), "exceptional_m": (0.0, 1000.0), "impaired_m": (0.0, 500.0),
          "detect_factor": (1.0, 10.0)}

INDOOR_FACTOR = 8 / 14              # what the old range was indoors against outdoors
NIGHT_FACTOR_INDOORS, NIGHT_FACTOR_OUTDOORS = 0.55, 0.35


class Vision:
    NORMAL = "normal"
    EXCEPTIONAL = "exceptional"
    IMPAIRED = "impaired"
    BLIND = "blind"
    ALL = (NORMAL, EXCEPTIONAL, IMPAIRED, BLIND)
    GENERATED = (NORMAL, EXCEPTIONAL, IMPAIRED)       # blind is never rolled at generation


# ---- settings ---------------------------------------------------------------------------------------------------------------------

def settings(world):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in ((world.get("settings") or {}).get("vision") or {}).items() if k in DEFAULTS})
    return s


def set_settings(world, patch):
    """Validate and store. Returns the settings now in force; raises ValueError naming the bad field."""
    clean = {}
    for key, value in (patch or {}).items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown vision setting '{key}'")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        lo, hi = LIMITS[key]
        if not (lo <= v <= hi):
            raise ValueError(f"{key} must be between {lo} and {hi}")
        clean[key] = v
    world.setdefault("settings", {}).setdefault("vision", {}).update(clean)
    return settings(world)


# ---- a character's level ----------------------------------------------------------------------------------------------------------

def natural_level(c):
    v = c.get("vision")
    if v in Vision.ALL:
        return v
    traits = c.get("physical_traits") or []          # characters from before this existed
    if "poor_eyesight" in traits:
        return Vision.IMPAIRED
    if "keen_eyesight" in traits:
        return Vision.EXCEPTIONAL
    return Vision.NORMAL


def wears_glasses(c):
    if not (c.get("glasses") or {}).get("owned"):
        return False
    return (c.get("activity") or {}).get("type") not in ("sleep", "nap", "take_shower", "take_bath")


def effective_level(c):
    level = natural_level(c)
    if level == Vision.IMPAIRED and wears_glasses(c):
        return Vision.NORMAL
    return level


# ---- ranges -------------------------------------------------------------------------------------------------------------------------

def _is_night(world):
    hour = (world.get("calendar") or {}).get("hour", 12)
    return hour < 6 or hour >= 21


def recognize_meters(c, world):
    """Metres at which this character can still tell a face (before indoor and night shortening)."""
    level = effective_level(c)
    if level == Vision.BLIND:
        return 0.0
    return float(settings(world)[f"{level}_m"])


def recognize_tiles(c, world):
    s = settings(world)
    tiles = recognize_meters(c, world) / s["tile_meters"]
    indoors = bool(c.get("building_id"))
    if indoors:
        tiles *= INDOOR_FACTOR
    if _is_night(world):
        tiles *= NIGHT_FACTOR_INDOORS if indoors else NIGHT_FACTOR_OUTDOORS
    return tiles


def detect_tiles(c, world):
    return recognize_tiles(c, world) * settings(world)["detect_factor"]


def distance_tiles(a, b):
    return math.hypot(a.get("x", 0) - b.get("x", 0), a.get("y", 0) - b.get("y", 0))


def detail_tier(distance, recognize, detect):
    """'recognized' out to the recognition range; beyond it 'figure' for the nearer half of the way to the detection range and
    'silhouette' for the farther half; None past the detection range."""
    if detect <= 0 or distance > detect:
        return None
    if distance <= recognize:
        return "recognized"
    middle = recognize + (detect - recognize) / 2.0
    return "figure" if distance <= middle else "silhouette"


# ---- who has what ---------------------------------------------------------------------------------------------------------------------

# the share of people impaired by nature, by age (decent odds of needing glasses to read from forty on)
IMPAIRED_BY_AGE = ((13, 0.06), (40, 0.10), (50, 0.40), (60, 0.62), (200, 0.80))
EXCEPTIONAL_CHANCE = 0.04
GLASSES_OWNED_CHANCE = 0.85


def random_vision(age, physical_traits=(), rng=None):
    import random as _random
    rng = rng or _random
    traits = set(physical_traits or ())
    if "poor_eyesight" in traits:
        return Vision.IMPAIRED
    if "keen_eyesight" in traits:
        return Vision.EXCEPTIONAL
    age = age if age is not None else 30
    chance = next(p for limit, p in IMPAIRED_BY_AGE if age < limit)
    r = rng.random()
    if r < chance:
        return Vision.IMPAIRED
    return Vision.EXCEPTIONAL if r > 1 - EXCEPTIONAL_CHANCE else Vision.NORMAL


def random_glasses(level, rng=None):
    import random as _random
    rng = rng or _random
    return {"owned": level == Vision.IMPAIRED and rng.random() < GLASSES_OWNED_CHANCE}


def ensure_vision(c, rng=None):
    """Give a character from before this existed a level and glasses. Returns True if anything was added."""
    if c.get("vision") in Vision.ALL and "glasses" in c:
        return False
    c["vision"] = c.get("vision") if c.get("vision") in Vision.ALL else random_vision(c.get("age"), c.get("physical_traits"), rng)
    c.setdefault("glasses", random_glasses(c["vision"], rng))
    return True
