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

# world["tick"] advances by exactly 1 per nominal game-second (see
# sim_loop.py::advance_calendar()) -- this used to be 24, copied from
# health.py's own (also wrong) TICKS_PER_DAY, making a plant's whole
# growth/moisture/weed cycle run roughly 3600x too fast. Corrected here.
TICKS_PER_DAY = 86400

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
        "last_decay_tick":    tick,
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
        arm_plant(target_prop, world)
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
    arm_plant(prop, world)
    return prop


def water_plant(prop, world=None):
    state = prop.get("plant_state")
    if not state:
        return False
    if world is not None:
        tick_plant(prop, world)          # its own clock up to now first: the elapsed days must not land on the watering
    state["moisture"] = 100
    state["_water_warned"] = False
    if world is not None:
        arm_plant(prop, world)
    return True


def pull_weed(prop, world=None):
    state = prop.get("plant_state")
    if not state:
        return False
    if world is not None:
        tick_plant(prop, world)
    state["weed_level"] = 0
    if world is not None:
        arm_plant(prop, world)
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
    """Every plant at once (older callers, tests, a world loaded from an older save) -- each then times itself. The sim
    runs each plant on its own timer (_on_plant_timer): growth, moisture and weeds are integrated over the elapsed
    time anyway, so a plant only has to be looked at when something about it changes."""
    for prop in list(_props_iter(world)):
        if prop.get("plant_state"):
            tick_plant(prop, world)
            arm_plant(prop, world)


def tick_plant(prop, world):
    """Bring one plant up to now: moisture and weeds over the elapsed days, the dry warning, the next growth stage."""
    tick = world.get("tick", 0)
    plant_templates = world.get("definitions", {}).get("plant_templates", {})
    state = prop.get("plant_state")
    if not state:
        return
    tmpl = plant_templates.get(prop.get("plant_template"))
    if not tmpl:
        return

    # moisture/weed decay used to apply a flat "per day" amount on
    # EVERY call to tick_plants() regardless of how much simulated
    # time had actually passed since the last call (CADENCE["plants"]
    # fires every 30 real ticks -- 30 seconds -- not once a day), so
    # a plant dried out and weeded over in minutes no matter what
    # TICKS_PER_DAY was set to. Scaled by real elapsed simulated
    # days since the last decay tick instead; last_decay_tick is
    # stamped at planting time (init_plant_state) so the very first
    # tick after planting doesn't see a huge bogus elapsed window.
    elapsed_days = max(0, (tick - state.get("last_decay_tick", tick)) / TICKS_PER_DAY)
    state["moisture"] = max(0, state["moisture"] - tmpl.get("moisture_decay_per_day", 10) * elapsed_days)
    state["weed_level"] = min(100, state["weed_level"] + tmpl.get("weed_growth_per_day", 5) * elapsed_days)
    state["last_decay_tick"] = tick

    # Real reactive wake for the household's own plant, once, when it
    # crosses a real "needs water soon" threshold -- confirmed gap:
    # moisture already decayed for real, but nothing ever surfaced it
    # to anyone before growth silently paused at 0 (plant_needs_water/
    # garden_dry, ChatGPT-authored household situation spec).
    # water_plant() clears the flag so this can re-arm on the next
    # real dry-out, not just once ever.
    if state["moisture"] <= 20 and not state.get("_water_warned"):
        state["_water_warned"] = True
        household = world.get("households", {}).get(prop.get("household_id"))
        if household:
            from systems.household_monitoring import choose_responsible_member
            chars = world.get("characters", {})
            members = [chars[mid] for mid in household.get("members", []) if mid in chars]
            responsible = choose_responsible_member(members, world) if members else None
            if responsible:
                from brain.cognition_scheduler import wake_character
                wake_character(responsible, world, "plant_needs_water", {
                    "plant_id": prop["id"],
                    "plant_name": tmpl.get("name", prop.get("plant_template", "a plant")),
                    "moisture": state["moisture"],
                })

    # Growth pauses entirely while bone dry.
    if state["moisture"] <= 0:
        return

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


# ── each plant on its own timer ───────────────────────────────────────────────────────────────────────────────────────
# Moisture, weeds and growth are integrated over elapsed time (tick_plant), so a plant only needs looking at when
# something about it changes: moisture crossing the dry warning (20), the watering cut-off, a household member's own
# tolerance (their cleanliness_threshold) or 0; weeds reaching HIGH_WEED_THRESHOLD; the next growth stage. While it
# needs attention (thirsty or weedy past someone's tolerance, or produce waiting) it is looked at on the old 30-second
# cadence -- the household's chores (systems/chores.py::maybe_tend_plants) nag, plan or harvest as before.

ATTENTION_RECHECK_SECONDS = 30


def _household_members(world, prop):
    hh = (world.get("households") or {}).get(prop.get("household_id")) or {}
    chars = world.get("characters") or {}
    return [chars[m] for m in hh.get("members", []) if m in chars]


def arm_plant(prop, world):
    from core import scheduler
    from core.clock import now_ts
    from core.tick_schedule import TICK_RATE_SECONDS
    state = prop.get("plant_state")
    tmpl = world.get("definitions", {}).get("plant_templates", {}).get(prop.get("plant_template"))
    owner = f"plant:{prop.get('id')}"
    if not state or not tmpl:
        scheduler.cancel(world, owner, "next")
        return
    from systems.chores import PLANT_WATER_MOISTURE_CUTOFF
    members = _household_members(world, prop)
    m, w = state.get("moisture", 100), state.get("weed_level", 0)
    per_tick_m = tmpl.get("moisture_decay_per_day", 10) / TICKS_PER_DAY
    per_tick_w = tmpl.get("weed_growth_per_day", 5) / TICKS_PER_DAY
    waits = []
    thresholds = {20, PLANT_WATER_MOISTURE_CUTOFF, 0} | {c.get("cleanliness_threshold", 40) for c in members}
    for thr in thresholds:
        if m > thr and per_tick_m > 0:
            waits.append((m - thr) / per_tick_m + 1)
    if w < HIGH_WEED_THRESHOLD and per_tick_w > 0:
        waits.append((HIGH_WEED_THRESHOLD - w) / per_tick_w + 1)
    if m > 0:
        need = {"seed": tmpl.get("days_to_sprout", 2), "sprout": tmpl.get("days_to_grow", 3),
                "growing": tmpl.get("days_to_grow", 3), "mature": tmpl.get("days_mature_before_overgrown", 4),
                "overgrown": 0}.get(state.get("stage"))
        if need is not None:
            factor = WEED_GROWTH_PENALTY if w >= HIGH_WEED_THRESHOLD else 1.0
            done = (world.get("tick", 0) - state.get("stage_started_tick", 0)) * factor
            waits.append(max(1.0, (need * TICKS_PER_DAY - done) / factor))
    attention = prop.get("items") or w >= HIGH_WEED_THRESHOLD or \
        any(m < min(PLANT_WATER_MOISTURE_CUTOFF, c.get("cleanliness_threshold", 40)) for c in members)
    if attention:
        waits.append(ATTENTION_RECHECK_SECONDS / TICK_RATE_SECONDS)
    if waits:
        scheduler.schedule_at(world, owner, "next", now_ts(world) + min(waits) * TICK_RATE_SECONDS)


def _on_plant_timer(world, entry):
    pid = entry["owner"].split(":", 1)[1]
    prop = next((p for p in _props_iter(world) if p.get("id") == pid), None)
    if not prop or not prop.get("plant_state"):
        return
    tick_plant(prop, world)
    from systems.chores import maybe_tend_plants
    for c in _household_members(world, prop):
        if c.get("alive", True) and not c.get("off_grid"):
            maybe_tend_plants(c, world)
    arm_plant(prop, world)


def _on_world_loaded(world, entry=None):
    tick_plants(world)


from core import scheduler as _scheduler      # noqa: E402
_scheduler.register("plant", _on_plant_timer)
