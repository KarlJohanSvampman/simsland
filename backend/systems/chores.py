"""
systems/chores.py

Room/zone cleanliness -- the driving mechanism behind the cleaning chores
(laundry_load, wash_dishes_machine/manual, clean_floors, dust_and_wipe --
all run on systems/task_process.py's shared multi-stage engine).

Cleanliness is tracked per ZONE, not per literal navigation room: a zone
is prop.get("room_id") when the building actually has real room
subdivision, else the building_id itself (today's reality for most
households -- see systems/navigation.py's NAV_CACHE fix and the Floorplan
Designer wiki guide for how to actually add rooms). This is honest about
what exists today while staying forward-compatible: the moment a
household gets real rooms, the exact same code starts tracking per-room
automatically, no further changes needed here.
"""

import random

CLEANLINESS_MAX = 100.0
CLEANLINESS_MIN = 0.0
PASSIVE_DECAY_PER_TICK = 0.01   # ambient living slowly dirties a zone

# How much a completed chore raises its zone's cleanliness by.
CLEAN_CHORE_RESTORE = {
    "clean_floors":         45.0,
    "dust_and_wipe":        35.0,
    "wash_dishes_machine":  20.0,
    "wash_dishes_manual":   20.0,
    "laundry_load":         10.0,
}

# Zones containing a prop whose template/category matches one of these
# keywords get tackled first when a character has several below-threshold
# zones to pick from -- matches the user's own stated priority (bathroom
# and kitchen before anything else).
_PRIORITY_ZONE_KEYWORDS = {
    "bathroom": 3, "toilet": 3, "shower": 3, "bathtub": 3, "tub": 3,
    "kitchen": 3, "sink": 2, "stove": 2, "fridge": 2,
}

# Keyword match against a prop's template/category -- what dust_and_wipe
# actually wipes down (tables, cabinets, benches, shelves, sinks,
# toilets, bathtubs, showers, windows).
_SURFACE_KEYWORDS = (
    "table", "cabinet", "shelf", "bench", "counter", "vanity",
    "sink", "toilet", "shower", "tub", "window", "desk", "dresser",
)
MAX_SURFACES_PER_WIPE = 6
MAX_DISHES_PER_WASH = 8

# Tools clean_floors' combined sweep/vacuum/scrub needs -- the user's
# own explicit ask: scrubbing needs a mop + a water-filled bucket,
# vacuuming needs a vacuum cleaner AND a power outlet in the zone
# (systems/electrical.py). Sweeping itself isn't gated on anything
# (never asked for).
MOP_TEMPLATE_ID = "mop"
BUCKET_TEMPLATE_ID = "bucket"
VACUUM_CLEANER_TEMPLATE_ID = "vacuum_cleaner"


# =========================================================
# ZONE RESOLUTION
# =========================================================

def zone_key_for_prop(prop):
    return prop.get("room_id") or prop.get("building_id")


def zone_key_for_character(c):
    return c.get("room_id") or c.get("building_id")


def _household_building_id(world, household):
    return household.get("home_id") if household else None


def kitchen_zone_key(world, household):
    """The zone a household's kitchen appliances sit in -- used to credit
    a finished dishwashing chore against the right zone. Falls back to
    the household's home building generally if no fridge/sink is found
    (e.g. a household with no kitchen props placed yet)."""
    building_id = _household_building_id(world, household)
    if not building_id:
        return None
    for prop in world.get("props", []):
        if prop.get("building_id") != building_id:
            continue
        tmpl = (prop.get("template") or "").lower()
        if "fridge" in tmpl or "kitchen_sink" in tmpl or "stove" in tmpl or "dishwasher" in tmpl:
            return zone_key_for_prop(prop)
    return building_id


# =========================================================
# CLEANLINESS VALUE
# =========================================================

def get_room_cleanliness(world, zone_key):
    if not zone_key:
        return CLEANLINESS_MAX
    return world.setdefault("room_cleanliness", {}).get(zone_key, CLEANLINESS_MAX)


def adjust_room_cleanliness(world, zone_key, delta):
    if not zone_key:
        return
    store = world.setdefault("room_cleanliness", {})
    current = store.get(zone_key, CLEANLINESS_MAX)
    store[zone_key] = max(CLEANLINESS_MIN, min(CLEANLINESS_MAX, current + delta))


def tick_room_cleanliness_decay(world):
    """Passive ambient dirtying, called on a slow cadence. Zones nobody's
    ever touched stay implicitly at CLEANLINESS_MAX (get_room_cleanliness's
    default) -- no need to pre-seed every building's zones up front."""
    store = world.get("room_cleanliness")
    if not store:
        return
    for zone_key in list(store.keys()):
        store[zone_key] = max(CLEANLINESS_MIN, store[zone_key] - PASSIVE_DECAY_PER_TICK)


# =========================================================
# ZONE PRIORITY (bathroom/kitchen first)
# =========================================================

def zone_priority_weight(world, zone_key):
    best = 0
    for prop in world.get("props", []):
        if zone_key_for_prop(prop) != zone_key:
            continue
        haystack = f"{prop.get('category', '')} {prop.get('template', '')}".lower()
        for keyword, weight in _PRIORITY_ZONE_KEYWORDS.items():
            if keyword in haystack:
                best = max(best, weight)
    return best


def worst_zone_below_threshold(world, c):
    """Every zone in this character's own building that's below their
    cleanliness_threshold, worst-scoring first (priority-weighted, then
    dirtiest). Returns None if nothing qualifies."""
    threshold = c.get("cleanliness_threshold", 40)
    building_id = c.get("building_id")
    if not building_id:
        return None

    zones = set()
    for prop in world.get("props", []):
        if prop.get("building_id") != building_id:
            continue
        zk = zone_key_for_prop(prop)
        if zk:
            zones.add(zk)
    if not zones:
        zones.add(building_id)

    candidates = []
    for zk in zones:
        level = get_room_cleanliness(world, zk)
        if level < threshold:
            candidates.append((zk, level, zone_priority_weight(world, zk)))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[2], t[1]))
    return candidates[0][0]


# =========================================================
# ZONE -> CHORE MAPPING
# =========================================================

def has_dishwasher(world, household):
    building_id = _household_building_id(world, household)
    if not building_id:
        return False
    return any(
        p.get("building_id") == building_id and p.get("template") == "dishwasher"
        for p in world.get("props", [])
    )


def chore_activity_for_zone(world, c, zone_key):
    """Which activity_type should this character start to clean this
    zone? Dishes are judged household-wide (dirty_dishes isn't zone-
    scoped); dust_and_wipe needs no tools at all and is always available.
    clean_floors additionally requires its tools (see clean_floors_ready
    below) -- a household without them just never gets offered it,
    falling back to dust_and_wipe instead."""
    household = world.get("households", {}).get(c.get("household_id"))
    if household and dirty_dish_count(household) > 0:
        return "load_dishwasher" if has_dishwasher(world, household) else "wash_dishes"
    if clean_floors_ready(c, world, zone_key):
        return random.choice(("clean_floors", "dust_and_wipe"))
    return "dust_and_wipe"


def find_mop(c, world):
    return _find_item_of_template(c, world, MOP_TEMPLATE_ID)


def find_bucket(c, world):
    return _find_item_of_template(c, world, BUCKET_TEMPLATE_ID)


def find_vacuum_cleaner(c, world):
    return _find_item_of_template(c, world, VACUUM_CLEANER_TEMPLATE_ID)


def clean_floors_ready(c, world, zone_key):
    """Everything clean_floors' combined sweep/vacuum/scrub needs is on
    hand -- mop + a water-filled bucket (brought along, per the user's
    own framing -- no literal live position/distance tracking during the
    chore, same simplification every other multi-stage chore in this
    engine already makes) for scrubbing, a vacuum cleaner + a power
    outlet actually present in the zone for vacuuming."""
    mop, _ = find_mop(c, world)
    if not mop:
        return False
    bucket, _ = find_bucket(c, world)
    from systems.containers import water_uses_remaining
    if not bucket or water_uses_remaining(bucket) <= 0:
        return False
    vacuum, _ = find_vacuum_cleaner(c, world)
    if not vacuum:
        return False
    from systems.electrical import zone_has_power_outlet
    if not zone_has_power_outlet(world, zone_key):
        return False
    return True


# =========================================================
# DIRTY DISHES (household-scoped, a count, not per-instance items --
# see chore_templates["wash_dishes_manual"]'s _per_item_note)
# =========================================================

def dirty_dish_count(household):
    return household.get("dirty_dishes", 0) if household else 0


def add_dirty_dishes(household, amount=1):
    if household is None:
        return
    household["dirty_dishes"] = household.get("dirty_dishes", 0) + amount


def clear_dirty_dishes(household):
    if household is None:
        return
    household["dirty_dishes"] = 0


def dish_count_for_wash(household):
    return max(1, min(MAX_DISHES_PER_WASH, dirty_dish_count(household) or 1))


# =========================================================
# SURFACES (dust_and_wipe's per-item target count)
# =========================================================

def surface_count_in_zone(world, zone_key):
    count = 0
    for prop in world.get("props", []):
        if zone_key_for_prop(prop) != zone_key:
            continue
        haystack = f"{prop.get('template', '')}".lower()
        if any(keyword in haystack for keyword in _SURFACE_KEYWORDS):
            count += 1
    return min(MAX_SURFACES_PER_WIPE, count) if count else 1


# =========================================================
# THE DRIVING MECHANISM -- called on a slow cadence (see sim_loop.py)
# per character, not every tick: add_intention() already de-duplicates
# same-type entries, so re-running this while a zone stays dirty is
# harmless, but nagging specifically gets its own once-a-day cooldown
# below so a persistent mess doesn't pile up a fresh grievance every
# cadence hit.
# =========================================================

# Traits that push toward speaking up (nag) vs. just handling it quietly
# (self-clean). Everyone else is a coin flip.
_NAG_LEANING_TRAITS = {"impatient", "stubborn"}
_SELF_CLEAN_LEANING_TRAITS = {"passive", "diplomatic", "calm", "patient", "forgiving"}
NAG_COOLDOWN_TICKS = 86400  # ~1 sim day, matches this codebase's usual day-key cadence


def _wants_to_nag(c):
    tr = set(c.get("traits", [])) | set(c.get("personality_traits", []))
    if tr & _NAG_LEANING_TRAITS:
        return random.random() < 0.7
    if tr & _SELF_CLEAN_LEANING_TRAITS:
        return random.random() < 0.2
    return random.random() < 0.45


def _find_someone_to_blame(world, c):
    """No real per-action mess attribution exists (cleanliness is a
    decaying zone value, not tied to who specifically dirtied it) -- so
    "who's responsible" is a household-mate roll, same honesty-light
    spirit as a real nag not always being perfectly justified. Returns
    None if there's nobody else to blame (e.g. living alone)."""
    household_id = c.get("household_id")
    if not household_id:
        return None
    mates = [
        other for other in world.get("characters", {}).values()
        if other.get("household_id") == household_id
        and other.get("id") != c.get("id")
        and other.get("alive", True)
    ]
    return random.choice(mates) if mates else None


def maybe_react_to_mess(c, world):
    """Called from sim_loop.py on a slow per-character cadence. Finds the
    worst zone this character can see that's below their own
    cleanliness_threshold and either nags about it (feeds the dormant
    "left_mess" grievance -- see grievances.py -- into the real
    grievance -> confrontation_desired -> conflict_pipeline.py negotiation
    -> social_contracts.py pipeline) or just goes and does the matching
    chore themselves."""
    zone_key = worst_zone_below_threshold(world, c)
    if not zone_key:
        return

    if _wants_to_nag(c):
        last = c.get("_last_mess_nag", {})
        tick = world.get("tick", 0)
        if tick - last.get(zone_key, -NAG_COOLDOWN_TICKS) < NAG_COOLDOWN_TICKS:
            return
        target = _find_someone_to_blame(world, c)
        if target:
            from systems.grievances import add_grievance
            add_grievance(c, target["id"], "left_mess", world, details={"zone_key": zone_key})
            c.setdefault("_last_mess_nag", {})[zone_key] = tick
            return
        # Nobody to blame (lives alone, etc.) -- fall through to self-clean.

    from brain.intentions import add_intention
    add_intention(c, {
        "type":     "clean_zone",
        "category": "chores",
        "priority": 45,
        "reason":   "mess",
        "zone_key": zone_key,
    })


# =========================================================
# INSPIRATION -- watching a housemate actually clean up rubs off on you.
# Two effects, both reusing existing engines rather than a new one:
# a slow personality-drift toward "organized" (systems/peer_influence.py's
# real trait-adoption accumulator -- ~15 reinforcements before it can
# actually promote, so this is a many-tick-later payoff, not instant),
# plus a short-lived immediate nudge (a temporary intention) since the
# trait accumulator alone is too slow to read as "inspired to get to it
# soon" the way the user described.
# =========================================================

INSPIRATION_NUDGE_PRIORITY = 30


def maybe_inspire_witnesses(household, process, world):
    participants = process.get("participants") or []
    if not participants:
        return
    source = world.get("characters", {}).get(participants[0])
    if not source:
        return

    for other in world.get("characters", {}).values():
        if other.get("id") in participants:
            continue
        if other.get("household_id") != household.get("id"):
            continue
        if other.get("building_id") != source.get("building_id"):
            continue   # not actually home to notice
        if other.get("alive") is False:
            continue

        from systems.peer_influence import record_positive_exposure
        record_positive_exposure(other, source, "organized", world)

        # Short-term "seeing that just now makes me want to do mine too"
        # nudge -- low priority (below the real driving reaction at 45),
        # so it's easy to override but still real: a below-threshold zone
        # this witness has been putting off gets a small push.
        zone_key = worst_zone_below_threshold(world, other)
        if zone_key:
            from brain.intentions import add_intention
            add_intention(other, {
                "type":     "clean_zone",
                "category": "chores",
                "priority": INSPIRATION_NUDGE_PRIORITY,
                "reason":   f"watching {source.get('name', 'them')} clean up made you want to tidy too",
                "zone_key": zone_key,
            })


# =========================================================
# PLANT CARE -- watering, weeding, harvesting. Raw plant-state mechanics
# (water_plant/pull_weed, growth/moisture/weed ticking) live in systems/
# plants.py; this module owns the same "driving mechanism" role for
# plants that it already does for room cleanliness -- deciding WHEN a
# character bothers, and WHICH real plant props get acted on when they
# do. "A household's plants" means every living plant prop
# (plant_state present) whose household_id matches -- potted plants get
# this via the ordinary building-ownership backfill (schema_defaults.py/
# room_assignment.py) since they sit inside an owned building; outdoor
# soil-grown plants have no building_id (no floorplan out there), so
# plants.py::plant_seed() stamps it directly at planting time. No real
# "garden room"/greenhouse floorplan concept exists in this codebase
# (confirmed via grep) -- indoor vs. outdoor is just the pot/soil,
# carryable/not-carryable distinction plants.py already has; both are
# tended identically here.
# =========================================================

WATERING_CAN_TEMPLATE_ID = "watering_can"
WATERING_CAN_CAPACITY = 10          # one full fill waters up to 10 plants
PLANT_WATER_MOISTURE_CUTOFF = 90    # top up anything not near-full once actually watering
MAX_PLANTS_PER_WEEDING = 8
MAX_PLANTS_PER_HARVEST = 8


def household_plant_props(world, household_id):
    if not household_id:
        return []
    return [
        p for p in world.get("props", [])
        if p.get("plant_state") and p.get("household_id") == household_id
    ]


def _find_item_of_template(c, world, template_id):
    """Character's own inventory/held_stack first, then any household
    storage prop (e.g. the "garden" prop's outdoor_gear storage) in the
    home building. Returns (item, source_container_or_None) -- source is
    None when the item is directly on the character (nothing to write
    back into). Shared search shape for every "does anyone in this
    household own a <tool>" chore-gating check below."""
    for item in list(c.get("inventory", [])) + list(c.get("held_stack", [])):
        if item.get("template_id") == template_id:
            return item, None

    household = world.get("households", {}).get(c.get("household_id"))
    building_id = household.get("home_id") if household else None
    if not building_id:
        return None, None

    from systems.containers import ensure_prop_storage
    for prop in world.get("props", []):
        if prop.get("building_id") != building_id:
            continue
        storage = ensure_prop_storage(prop, world)
        if not storage:
            continue
        for item in storage.get("items", []):
            if item.get("template_id") == template_id:
                return item, storage
    return None, None


def find_watering_can(c, world):
    return _find_item_of_template(c, world, WATERING_CAN_TEMPLATE_ID)


def plants_needing_water(world, household_id, cap=WATERING_CAN_CAPACITY):
    plants = household_plant_props(world, household_id)
    thirsty = [
        p for p in plants
        if p.get("plant_state", {}).get("moisture", 100) < PLANT_WATER_MOISTURE_CUTOFF
    ]
    thirsty.sort(key=lambda p: p["plant_state"]["moisture"])
    return thirsty[:max(0, cap)]


def plants_needing_weeding(world, household_id, cap=MAX_PLANTS_PER_WEEDING):
    from systems.plants import HIGH_WEED_THRESHOLD
    plants = household_plant_props(world, household_id)
    weedy = [
        p for p in plants
        if p.get("plant_state", {}).get("weed_level", 0) >= HIGH_WEED_THRESHOLD
    ]
    weedy.sort(key=lambda p: -p["plant_state"]["weed_level"])
    return weedy[:cap]


def plants_ready_to_harvest(world, household_id, cap=MAX_PLANTS_PER_HARVEST):
    plants = household_plant_props(world, household_id)
    ready = [p for p in plants if p.get("items")]
    return ready[:cap]


def maybe_tend_plants(c, world):
    """Called from sim_loop.py on the same cadence as tick_plants. Mirrors
    maybe_react_to_mess's nag-vs-self-handle shape exactly, reusing the
    SAME cleanliness_threshold trait field as the "how much do I tolerate
    before I react" tolerance -- a deliberate reuse (both represent the
    same underlying personality axis) rather than a second trait-derived
    number. Checked worst-first: thirsty plants outrank weedy ones, which
    outrank ripe-but-unpicked ones. Ripe produce sitting unpicked isn't
    anyone's fault to nag about, so harvesting always just gets a direct
    intention, no blame/grievance path."""
    household_id = c.get("household_id")
    if not household_id:
        return
    if not household_plant_props(world, household_id):
        return

    threshold = c.get("cleanliness_threshold", 40)
    tick = world.get("tick", 0)

    thirsty = plants_needing_water(world, household_id)
    if thirsty and thirsty[0]["plant_state"]["moisture"] < threshold:
        if _wants_to_nag(c):
            last = c.get("_last_plant_nag", {})
            if tick - last.get("water_plants", -NAG_COOLDOWN_TICKS) < NAG_COOLDOWN_TICKS:
                return
            target = _find_someone_to_blame(world, c)
            if target:
                from systems.grievances import add_grievance
                add_grievance(c, target["id"], "neglected_plants", world,
                               details={"chore": "water_plants"})
                c.setdefault("_last_plant_nag", {})["water_plants"] = tick
                return
        can, _source = find_watering_can(c, world)
        if can:
            from brain.intentions import add_intention
            add_intention(c, {
                "type":     "water_plants",
                "category": "chores",
                "priority": 45,
                "reason":   "the plants need watering",
            })
        return

    weedy = plants_needing_weeding(world, household_id)
    if weedy:
        if _wants_to_nag(c):
            last = c.get("_last_plant_nag", {})
            if tick - last.get("weed_plants", -NAG_COOLDOWN_TICKS) < NAG_COOLDOWN_TICKS:
                return
            target = _find_someone_to_blame(world, c)
            if target:
                from systems.grievances import add_grievance
                add_grievance(c, target["id"], "neglected_plants", world,
                               details={"chore": "weed_plants"})
                c.setdefault("_last_plant_nag", {})["weed_plants"] = tick
                return
        from brain.intentions import add_intention
        add_intention(c, {
            "type":     "weed_plants",
            "category": "chores",
            "priority": 40,
            "reason":   "weeds are taking over the plants",
        })
        return

    ready = plants_ready_to_harvest(world, household_id)
    if ready:
        from brain.intentions import add_intention
        add_intention(c, {
            "type":     "harvest_plants",
            "category": "chores",
            "priority": 35,
            "reason":   "there's ripe produce ready to pick",
        })
