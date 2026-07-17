"""
systems/plants.py

Potted and soil-grown plants: a slow growth cycle (seed -> sprout ->
growing -> mature -> overgrown -> growing again, a perennial loop, not a
one-and-done), plus moisture (restored by watering) and weeds (cleared by
weeding) as the two neglect signals. No death mechanic this round --
overgrowth (losing the unharvested yield) is already the "neglect has a
consequence" outcome; kept simple on purpose.

Plant instances live as regular props in world["props"], distinguished by
a "plant_template" field (a key into definitions.json's plant_templates)
and a "plant_state" dict: {stage, stage_started_tick, moisture, weed_level}.
Potted plants are carryable (carryable: true, like any other movable
prop); soil-grown plants are not (carryable: false) and sit on a
"soil"-type tile.
"""

import uuid

TICKS_PER_DAY = 24  # matches health.py's TICKS_PER_DAY convention

# days_to_grow is charged twice (sprout->growing, then growing->mature) --
# both middle stages grow at the same pace; only the first (seed->sprout)
# and last (mature->overgrown) legs have their own duration.
HIGH_WEED_THRESHOLD  = 70
WEED_GROWTH_PENALTY  = 0.35  # effective growth rate while heavily weeded


def _props_iter(world):
    props = world.get("props", {})
    return props.values() if isinstance(props, dict) else props


def _add_prop(world, prop):
    props = world.setdefault("props", [])
    if isinstance(props, dict):
        props[prop["id"]] = prop
    else:
        props.append(prop)


def init_plant_state(prop, plant_template_id, tick):
    prop["plant_template"] = plant_template_id
    prop["plant_state"] = {
        "stage":              "seed",
        "stage_started_tick": tick,
        "moisture":           100,
        "weed_level":         0,
    }


def plant_seed(world, plant_template_id, target_prop=None, x=None, y=None):
    """target_prop: an existing empty pot prop to plant into directly.
    Otherwise (x, y) creates a brand-new immovable soil-grown plant prop
    at that tile. Returns the plant prop, or None if the template doesn't
    exist or the pot already has a plant."""
    tick = world.get("tick", 0)
    tmpl = world.get("definitions", {}).get("plant_templates", {}).get(plant_template_id)
    if not tmpl:
        return None

    if target_prop is not None:
        if target_prop.get("plant_template"):
            return None
        init_plant_state(target_prop, plant_template_id, tick)
        return target_prop

    if x is None or y is None:
        return None
    prop = {
        "id":        f"plant_{uuid.uuid4().hex[:6]}",
        "template":  plant_template_id,
        "x": x, "y": y,
        "carryable": False,
    }
    init_plant_state(prop, plant_template_id, tick)
    _add_prop(world, prop)
    return prop


def water_plant(prop):
    state = prop.get("plant_state")
    if not state:
        return False
    state["moisture"] = 100
    return True


def pull_weed(prop):
    state = prop.get("plant_state")
    if not state:
        return False
    state["weed_level"] = 0
    return True


def harvest_plant(char, prop, world):
    """Only when mature. Adds the template's yield straight to the
    harvester's inventory (see systems/personal_items.py::make_item_stack)
    -- generalizing this into a "collect"-into-hand-or-carried-container
    mechanic is explicitly deferred to a later round."""
    state = prop.get("plant_state")
    if not state or state.get("stage") != "mature":
        return False
    tmpl = world.get("definitions", {}).get("plant_templates", {}).get(
        prop.get("plant_template"), {})
    yield_item = tmpl.get("yield_item")
    if yield_item:
        from systems.personal_items import make_item_stack, add_item
        item = make_item_stack(yield_item, tmpl.get("yield_quantity", 1), world=world)
        add_item(char, item)
    state["stage"] = "growing"
    state["stage_started_tick"] = world.get("tick", 0)
    return True


def tick_plants(world):
    """Cadence-driven (see CADENCE["plants"]). Advances growth stage,
    decays moisture, grows weeds, cycles mature -> overgrown -> growing."""
    tick = world.get("tick", 0)
    plant_templates = world.get("definitions", {}).get("plant_templates", {})

    for prop in _props_iter(world):
        state = prop.get("plant_state")
        if not state:
            continue
        tmpl = plant_templates.get(prop.get("plant_template"))
        if not tmpl:
            continue

        state["moisture"] = max(0, state["moisture"] - tmpl.get("moisture_decay_per_day", 10))
        state["weed_level"] = min(100, state["weed_level"] + tmpl.get("weed_growth_per_day", 5))

        # Growth pauses entirely while bone dry.
        if state["moisture"] <= 0:
            continue

        days_in_stage = (tick - state["stage_started_tick"]) / TICKS_PER_DAY
        if state["weed_level"] >= HIGH_WEED_THRESHOLD:
            days_in_stage *= WEED_GROWTH_PENALTY

        stage = state["stage"]
        if stage == "seed" and days_in_stage >= tmpl.get("days_to_sprout", 2):
            state["stage"], state["stage_started_tick"] = "sprout", tick
        elif stage == "sprout" and days_in_stage >= tmpl.get("days_to_grow", 3):
            state["stage"], state["stage_started_tick"] = "growing", tick
        elif stage == "growing" and days_in_stage >= tmpl.get("days_to_grow", 3):
            state["stage"], state["stage_started_tick"] = "mature", tick
        elif stage == "mature" and days_in_stage >= tmpl.get("days_mature_before_overgrown", 4):
            state["stage"], state["stage_started_tick"] = "overgrown", tick
        elif stage == "overgrown":
            # Unharvested yield is already lost by reaching this stage --
            # cycle continues immediately rather than lingering "dead".
            state["stage"], state["stage_started_tick"] = "growing", tick
