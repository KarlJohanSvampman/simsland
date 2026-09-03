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

Ripe fruit accumulates in the plant's own container (systems/
containers.py's generic "items"/"capacity" model -- add_to_container/
remove_from_container work on it unmodified) the moment the plant turns
"mature", rather than being granted straight to an inventory on demand.
The generic "collect"/"harvest" actions (action_router.py) pull fruit out
of that container into a hand or carried container. Going "overgrown"
clears the container -- unharvested fruit rots and falls off.
"""

import uuid

TICKS_PER_DAY = 24  # matches health.py's TICKS_PER_DAY convention

# days_to_grow is charged twice (sprout->growing, then growing->mature) --
# both middle stages grow at the same pace; only the first (seed->sprout)
# and last (mature->overgrown) legs have their own duration.
HIGH_WEED_THRESHOLD  = 70
WEED_GROWTH_PENALTY  = 0.35  # effective growth rate while heavily weeded

PLANT_CONTAINER_SLOTS = 4  # ad-hoc capacity for accumulated fruit -- not
                            # tied to a prop_template's storage field


def _props_iter(world):
    props = world.get("props", {})
    return props.values() if isinstance(props, dict) else props


def _add_prop(world, prop):
    props = world.setdefault("props", [])
    if isinstance(props, dict):
        props[prop["id"]] = prop
    else:
        props.append(prop)


def init_plant_state(prop, plant_template_id, tick, tmpl=None):
    prop["plant_template"] = plant_template_id
    prop["plant_state"] = {
        "stage":              "seed",
        "stage_started_tick": tick,
        "moisture":           100,
        "weed_level":         0,
    }
    prop["items"] = prop.get("items", [])
    prop["capacity"] = PLANT_CONTAINER_SLOTS
    # Single-item-type container (systems/containers.py::can_fit) -- this
    # plant's fruit slot only ever holds its own yield_item, never any
    # other food/item that a generic "put_in"-style action might target
    # at it later.
    yield_item = (tmpl or {}).get("yield_item")
    prop["accepted_templates"] = [yield_item] if yield_item else None


def plant_seed(world, plant_template_id, target_prop=None, x=None, y=None, household_id=None):
    """target_prop: an existing empty pot prop to plant into directly
    (its own household_id, already stamped at creation time -- see
    room_assignment.py/schema_defaults.py -- is left untouched). Otherwise
    (x, y) creates a brand-new immovable soil-grown plant prop at that
    tile -- these have no building_id (outdoors, no floorplan), so
    household_id is stamped directly here (see systems/chores.py::
    household_plant_props(), the only thing that reads it) rather than
    left unset. Returns the plant prop, or None if the template doesn't
    exist or the pot already has a plant."""
    tick = world.get("tick", 0)
    tmpl = world.get("definitions", {}).get("plant_templates", {}).get(plant_template_id)
    if not tmpl:
        return None

    if target_prop is not None:
        if target_prop.get("plant_template"):
            return None
        init_plant_state(target_prop, plant_template_id, tick, tmpl=tmpl)
        return target_prop

    if x is None or y is None:
        return None
    prop = {
        "id":        f"plant_{uuid.uuid4().hex[:6]}",
        "template":  plant_template_id,
        "x": x, "y": y,
        "carryable": False,
        "household_id": household_id,
    }
    init_plant_state(prop, plant_template_id, tick, tmpl=tmpl)
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


def _fruit_plant(prop, tmpl, world):
    """Called once, exactly on the growing -> mature transition (see
    tick_plants below): mints the template's yield and drops it into the
    plant's own container. Reuses systems/containers.py's generic
    add_to_container/systems/personal_items.py's make_item_stack --
    same "mint from template" helper procurement.py already uses."""
    yield_item = tmpl.get("yield_item")
    if not yield_item:
        return
    from systems.personal_items import make_item_stack
    from systems.containers import add_to_container
    item = make_item_stack(yield_item, tmpl.get("yield_quantity", 1), world=world)
    add_to_container(prop, item)


def _clear_plant_container(prop):
    """Called once, exactly on the mature -> overgrown transition:
    unharvested fruit rots and falls off -- deleted, not moved anywhere."""
    prop["items"] = []


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
            _fruit_plant(prop, tmpl, world)
        elif stage == "mature" and days_in_stage >= tmpl.get("days_mature_before_overgrown", 4):
            state["stage"], state["stage_started_tick"] = "overgrown", tick
            _clear_plant_container(prop)
        elif stage == "overgrown":
            # Unharvested yield is already lost by reaching this stage --
            # cycle continues immediately rather than lingering "dead".
            state["stage"], state["stage_started_tick"] = "growing", tick
