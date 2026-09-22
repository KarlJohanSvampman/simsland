"""
systems/weather.py — outdoor weather + seasonal temperature.

Confirmed dead-on-arrival before this: world["weather"] was read by
brain/perception.py's room-summary narration ("Outside it is {weather}.")
but never once SET anywhere in the codebase -- always None, so that line
never fired. Meanwhile data/item_templates.py already had a real "warmth"
stat on every outerwear item (jacket_hoodie 0.6, jacket_winter 0.95, ...)
with zero consumers. Both real, both unused -- this module is the missing
piece connecting them.

world["weather"] = {
    "condition":        "clear"|"cloudy"|"rain"|"storm"|"snow"|"fog",
    "temperature_c":    float,  # current outdoor temperature
    "season":           "winter"|"spring"|"summer"|"fall",
    "label":            "cold and clear, 3°C"  # perception.py surfaces this
    "next_change_tick": int,    # condition won't re-roll before this tick
}

Only characters actually outdoors (c.get("building_id") falsy) are
affected -- there's no HVAC/indoor-climate simulation yet, so indoors is
simply always treated as comfortable and exposure recovers there. See
apply_weather_to_characters().
"""

import math
import random

TICKS_PER_GAME_MINUTE = 60
TICKS_PER_GAME_HOUR = TICKS_PER_GAME_MINUTE * 60

SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall", 10: "fall", 11: "fall",
}

# (avg_low_c, avg_high_c) for a typical day in this season -- avg_high is
# the mid-afternoon peak, avg_low is just before dawn. temperature_c is
# interpolated between them by hour-of-day (see _day_curve_temp_c), then
# nudged by the current condition and a little jitter.
_SEASON_TEMP_RANGE_C = {
    "winter": (-4, 4),
    "spring": (6, 16),
    "summer": (17, 29),
    "fall":   (4, 14),
}

_CONDITION_WEIGHTS = {
    "winter": {"clear": 30, "cloudy": 30, "snow": 25, "fog": 10, "storm": 5},
    "spring": {"clear": 35, "cloudy": 25, "rain": 25, "fog": 10, "storm": 5},
    "summer": {"clear": 50, "cloudy": 20, "rain": 15, "storm": 10, "fog": 5},
    "fall":   {"clear": 25, "cloudy": 30, "rain": 30, "fog": 10, "storm": 5},
}

_CONDITION_TEMP_MODIFIER_C = {
    "clear": 1.0, "cloudy": -0.5, "rain": -2.0, "storm": -3.5, "snow": -3.0, "fog": -1.0,
}

_CONDITION_LABEL = {
    "clear": "clear", "cloudy": "cloudy", "rain": "rainy",
    "storm": "stormy", "snow": "snowy", "fog": "foggy",
}


def _season(world):
    month = world.get("calendar", {}).get("month", 6)
    return SEASON_BY_MONTH.get(month, "summer")


def _pick_condition(season):
    weights = _CONDITION_WEIGHTS[season]
    conditions = list(weights.keys())
    return random.choices(conditions, weights=[weights[cond] for cond in conditions], k=1)[0]


def _day_curve_temp_c(world, season):
    """Smooth low->high->low curve across the day, peaking mid-afternoon
    (~15:00) and bottoming out just before dawn (~03:00) -- a cosine
    shifted so hour=15 sits at its max rather than a plain sin(hour)."""
    cal = world.get("calendar", {})
    hour = cal.get("hour", 12) + cal.get("minute", 0) / 60.0
    low, high = _SEASON_TEMP_RANGE_C[season]
    mid = (low + high) / 2
    amp = (high - low) / 2
    phase = (hour - 15) / 24.0 * 2 * math.pi
    return mid + amp * math.cos(phase)


def _weather_label(weather):
    temp = weather.get("temperature_c", 15)
    cond = _CONDITION_LABEL.get(weather.get("condition"), "clear")
    if temp <= -2:
        feel = "freezing"
    elif temp <= 8:
        feel = "cold"
    elif temp <= 17:
        feel = "cool"
    elif temp <= 26:
        feel = "mild"
    elif temp <= 32:
        feel = "warm"
    else:
        feel = "hot"
    return f"{feel} and {cond}, {round(temp)}°C"


def generate_weather_tick(world):
    """Cadence-driven (CADENCE["weather"], see sim_loop.py). The condition
    only re-rolls once its own persistence window (next_change_tick) has
    elapsed -- weather shouldn't flicker every cadence call -- but
    temperature_c is recomputed every call from the day/night curve, so it
    still drifts smoothly hour to hour even while the condition itself is
    being held."""
    tick = world.get("tick", 0)
    weather = world.setdefault("weather", {})
    season = _season(world)

    if "condition" not in weather or tick >= weather.get("next_change_tick", 0):
        weather["condition"] = _pick_condition(season)
        # Hold this condition for 2-8 game-hours before reconsidering.
        weather["next_change_tick"] = tick + random.randint(
            2 * TICKS_PER_GAME_HOUR, 8 * TICKS_PER_GAME_HOUR
        )

    condition = weather["condition"]
    base = _day_curve_temp_c(world, season)
    modifier = _CONDITION_TEMP_MODIFIER_C.get(condition, 0)
    jitter = random.uniform(-0.5, 0.5)
    weather["temperature_c"] = round(base + modifier + jitter, 1)
    weather["season"] = season
    weather["label"] = _weather_label(weather)


# =========================================================
# CLOTHING INSULATION
# =========================================================

def clothing_insulation(c):
    """Sum of worn items' "warmth" rating (data/item_templates.py) -- a
    real per-item stat that already existed on every outerwear template
    with zero consumers before this module. Items with no explicit
    "warmth" (most non-outerwear clothing) still contribute a small
    baseline per covered slot -- an ordinary shirt+pants outfit isn't
    literally worth 0 insulation, it's just nowhere near a proper coat.
    0.0 = naked. ~0.3-0.6 = ordinary daily clothes. 1.0+ = bundled up in
    real cold-weather gear."""
    from data.item_templates import get_template
    total = 0.0
    for item in (c.get("worn") or {}).values():
        if not item:
            continue
        tpl = get_template(item.get("template_id")) or {}
        total += tpl.get("warmth", 0.1)
    return total


# =========================================================
# APPLY TO CHARACTERS
# =========================================================

# Comfortable range assumes ordinary indoor conditions; outdoors, real
# clothing (clothing_insulation) shifts how much cold a character can
# tolerate before this starts costing them -- it never helps against heat
# (bundling up in a winter coat on a hot day doesn't cool you down).
_COMFORTABLE_RANGE_C = (16, 27)
_INSULATION_COLD_TOLERANCE_C_PER_POINT = 10  # each point of insulation buys ~10°C of cold tolerance

_EXPOSURE_RISE_PER_TICK = 0.4    # at CADENCE["weather"] cadence, scaled by how far outside tolerance
_EXPOSURE_DECAY_PER_TICK = 2.0   # recovery once sheltered/comfortable again

_EXPOSURE_SICKNESS_THRESHOLD = 80
_EXPOSURE_SICKNESS_CHANCE_PER_TICK = 0.02


def apply_weather_to_characters(world):
    weather = world.get("weather") or {}
    outdoor_temp = weather.get("temperature_c")
    if outdoor_temp is None:
        return

    for c in world.get("characters", {}).values():
        body = c.setdefault("body", {})
        outdoors = not c.get("building_id")

        if not outdoors:
            body["cold_exposure"] = max(0, body.get("cold_exposure", 0) - _EXPOSURE_DECAY_PER_TICK)
            body["heat_exposure"] = max(0, body.get("heat_exposure", 0) - _EXPOSURE_DECAY_PER_TICK)
            continue

        low, high = _COMFORTABLE_RANGE_C
        insulation = clothing_insulation(c)
        effective_low = low - insulation * _INSULATION_COLD_TOLERANCE_C_PER_POINT

        if outdoor_temp < effective_low:
            deficit = effective_low - outdoor_temp
            body["cold_exposure"] = min(100, body.get("cold_exposure", 0)
                                        + _EXPOSURE_RISE_PER_TICK * (1 + deficit / 10))
        else:
            body["cold_exposure"] = max(0, body.get("cold_exposure", 0) - _EXPOSURE_DECAY_PER_TICK)

        if outdoor_temp > high:
            excess = outdoor_temp - high
            body["heat_exposure"] = min(100, body.get("heat_exposure", 0)
                                        + _EXPOSURE_RISE_PER_TICK * (1 + excess / 10))
        else:
            body["heat_exposure"] = max(0, body.get("heat_exposure", 0) - _EXPOSURE_DECAY_PER_TICK)

        _apply_exposure_consequences(c, world)


def _apply_exposure_consequences(c, world):
    body = c.get("body", {})
    cold = body.get("cold_exposure", 0)
    heat = body.get("heat_exposure", 0)
    worst = max(cold, heat)
    if worst < 40:
        return

    # Gentle stress drift proportional to how bad it is, same shape as
    # systems/lt_needs.py's _apply_lt_frustration.
    c["stress"] = min(100, c.get("stress", 0) + (worst - 40) * 0.01)

    if worst >= _EXPOSURE_SICKNESS_THRESHOLD:
        if random.random() < _EXPOSURE_SICKNESS_CHANCE_PER_TICK:
            body["sickness"] = min(100, body.get("sickness", 0) + random.uniform(5, 15))

        from systems.reactions import trigger_reaction
        trigger_reaction(c, world, "shivering" if cold >= heat else "sweating")
