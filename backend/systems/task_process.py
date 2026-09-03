"""
systems/task_process.py

Generalized multi-stage durative process engine, household-scoped (not
character-scoped like the older systems/cooking_process.py — a laundry
load can't live on the character who happened to start it, since anyone
in the household might return to empty/fold it). Mirrors systems/
services.py's hired-contract pattern: entries live in a flat
world["household_processes"] list, tick forward for every household every
cycle regardless of who's nearby (update_household_processes(), wired
into sim_loop.py at the same cadence as update_services()), and surface to
the LLM purely by being read into context every tick — there is no push/
notify/"remember to come back" mechanism anywhere in this codebase (see
systems/context_builder.py's household-process context), and this engine
deliberately doesn't add one.

Each process type (currently just "laundry") registers a pair of hooks —
on_begin(household, process, stage, world), called whenever a new stage
starts, and on_complete(household, process, world), called once when the
whole stage list is exhausted. Hooks are plain functions kept in a
module-level registry (_PROCESS_HOOKS), not stored on the process dict
itself, since the process dict is persisted to Redis/Postgres as JSON.

systems/cooking_process.py is NOT migrated to this engine this round — it
works fine as-is for a single cook seeing one recipe through, and
migrating it isn't required to ship laundry.
"""

from uuid import uuid4

_PROCESS_HOOKS = {}


def register_process_type(process_type, on_begin=None, on_complete=None):
    _PROCESS_HOOKS[process_type] = {"on_begin": on_begin, "on_complete": on_complete}


# =========================================================
# START PROCESS
# =========================================================

def start_process(household, world, process_type, template_id, stages, prop_id=None, participants=None, **extra):
    """stages is a resolved list snapshotted at start time (already
    primitive-expanded — see resolve_stages() below), so a mid-process
    edit to the chore/recipe template in definitions.json doesn't shift
    an in-flight process.

    participants defaults to just the character who triggered the initial
    hand-off. Recorded once, here, at start time — not tracked
    incrementally as stages advance, since only the very first "active"
    stage of a chore is currently wired to a real activities.py hand-off
    (see the module docstring below); nothing observes who's actually
    present for later stages, so incremental tracking would silently
    always equal this same initial list anyway. A caller resolving a
    multi-recipient chore proposal (systems/proposals.py) should pass the
    proposal's final accepted character-id list here.

    **extra: process types that aren't scoped to one prop (systems/
    chores.py's clean_floors/dust_and_wipe -- "wherever this zone is,"
    not "at this one sink/washer") stash whatever they need (e.g.
    zone_key) here instead of overloading prop_id.
    """
    process = {
        "id": str(uuid4()),
        "type": process_type,
        "template_id": template_id,
        "household_id": household["id"],
        "prop_id": prop_id,
        "participants": list(participants) if participants else [],
        "started_tick": world.get("tick", 0),
        "current_stage": 0,
        "stage_started_tick": world.get("tick", 0),
        "stages": stages,
        "completed": False,
        "waiting": False,
        **extra,
    }
    world.setdefault("household_processes", []).append(process)
    begin_stage(household, process, world)
    return process


# =========================================================
# BEGIN STAGE
# =========================================================

def begin_stage(household, process, world):
    stages = process["stages"]
    idx = process["current_stage"]

    if idx >= len(stages):
        finish_process(household, process, world)
        return

    stage = stages[idx]
    process["stage_started_tick"] = world.get("tick", 0)
    process["stage_name"] = stage.get("name") or stage.get("primitive")
    process["waiting"] = not stage.get("active", True)

    on_begin = _PROCESS_HOOKS.get(process["type"], {}).get("on_begin")
    if on_begin:
        on_begin(household, process, stage, world)


# =========================================================
# ADVANCE PROCESS — called once per household_processes entry per tick
# =========================================================

def advance_process(household, process, world):
    if process.get("completed"):
        return False

    stages = process["stages"]
    stage = stages[process["current_stage"]]

    elapsed = world.get("tick", 0) - process["stage_started_tick"]
    duration = stage.get("duration", 5) * 60

    if elapsed >= duration:
        process["current_stage"] += 1
        begin_stage(household, process, world)

    return True


# =========================================================
# FINISH PROCESS
# =========================================================

def finish_process(household, process, world):
    process["completed"] = True

    # If 2+ people participated, remember it so the household can be
    # offered a "make this recurring" proposal (see systems/proposals.py's
    # offer_recurring(), triggered by action_router.py's
    # _route_propose_recurring) — single slot, most-recent-wins, same
    # rationale as _pending_chore's hand-off cache: this is a rare,
    # deliberate follow-up prompt, not a queue of every past chore.
    if len(process.get("participants", [])) >= 2:
        household["_last_completed_chore"] = {
            "chore_id":     process["template_id"],
            "participants": list(process["participants"]),
        }

    # Stamps every participant's "did chore X today" marker, regardless of
    # process type -- the one thing systems/social_contracts.py's
    # "recurring_activity" checker needs to tell an honored recurring
    # chore commitment from a skipped one (see that file).
    cal = world.get("calendar", {})
    today = (cal.get("year"), cal.get("month"), cal.get("day"))
    chars = world.get("characters", {})
    for pid in process.get("participants", []):
        char = chars.get(pid)
        if char is not None:
            char.setdefault("_chore_done_today", {})[process["template_id"]] = today

    on_complete = _PROCESS_HOOKS.get(process["type"], {}).get("on_complete")
    if on_complete:
        on_complete(household, process, world)

    from systems.chores import maybe_inspire_witnesses
    maybe_inspire_witnesses(household, process, world)


# =========================================================
# RESOLVE STAGES — expand a chore/recipe template's stage list against
# stage_primitives, applying per-stage overrides
# =========================================================

def resolve_stages(world, stage_defs):
    primitives = (world.get("definitions") or {}).get("stage_primitives") or {}
    resolved = []
    for stage in stage_defs:
        prim = primitives.get(stage.get("primitive"), {})
        resolved.append({
            "primitive": stage.get("primitive"),
            "name":      stage.get("name") or prim.get("label") or stage.get("primitive"),
            "duration":  stage.get("duration", prim.get("default_duration", 5)),
            "active":    stage.get("active", prim.get("default_active", True)),
            "animation_state": prim.get("animation_state", "idle"),
            "inputs":    stage.get("inputs", {}),
            "outputs":   stage.get("outputs", {}),
        })
    return resolved


# =========================================================
# UPDATE ALL HOUSEHOLD PROCESSES — called each cadence tick from sim_loop
# =========================================================

def update_household_processes(world):
    processes = world.get("household_processes", [])
    households = world.get("households", {})

    for process in list(processes):
        if process.get("completed"):
            continue
        household = households.get(process["household_id"])
        if not household:
            process["completed"] = True   # orphaned — household gone
            continue
        advance_process(household, process, world)

    # Prune completed processes.
    world["household_processes"] = [
        p for p in processes if not p.get("completed")
    ]


# =========================================================
# LAUNDRY — the one process type built this round
# =========================================================
# Only the FIRST active stage (fill_washer) currently has a real
# activities.py hand-off (do_laundry_fill -> start_process(), mirroring
# cook_recipe's hand-off to systems/cooking_process.py) — every stage
# after that (empty_washer, fold_laundry, put_away) is timer-only today;
# their "active" flag doesn't yet gate on any character actually being
# present, since advance_process() is only ever called from the cadence
# sweep (update_household_processes()), not re-entered by a per-stage
# activities.py interaction. This is a known, deliberate simplification
# (see task_process.py's own module docstring) — treat "active" as "should
# animate someone if this hook has a character in scope," not "blocks
# progress until someone shows up." Unattended stages (wash_cycle,
# hang_dry) leave animation_state alone regardless — the character is free
# to walk away, matching the same deliberate behavior cooking's unattended
# stages already have.

def _laundry_on_begin(household, process, stage, world):
    if not stage.get("active", True):
        return   # unattended — nobody needs to be present, nothing to animate
    # Active-stage animation is set by the activities.py interaction that
    # calls advance_process() (it has the actual character `c` in scope,
    # which this hook does not) — nothing to do here for laundry today,
    # since every active laundry stage is a distinct activities.py
    # interaction rather than a single character sitting through this
    # hook's callback. This hook exists for process types (like a future
    # unattended-only chore) where on_begin alone needs to do something.


def _laundry_on_complete(household, process, world):
    from systems.household_storage import create_household_resource
    create_household_resource(
        household,
        "CLEAN_LAUNDRY",
        quantity=1,
        container="closet",
    )


register_process_type("laundry", on_begin=_laundry_on_begin, on_complete=_laundry_on_complete)


# =========================================================
# DISHES — machine (dishwasher) and manual (sink) variants. Same
# unattended-background-progression shape as laundry above; the manual
# variant's stages list is just longer (a wash/rinse/dry/put-away group
# repeated once per dirty dish, built by the activities.py hand-off
# before start_process() is ever called — see systems/chores.py).
# =========================================================

def _dishes_on_complete(household, process, world):
    from systems.household_storage import create_household_resource
    from systems.chores import clear_dirty_dishes, adjust_room_cleanliness, kitchen_zone_key

    create_household_resource(household, "CLEAN_DISHES", quantity=1, container="cabinet")
    clear_dirty_dishes(household)
    zone_key = kitchen_zone_key(world, household)
    if zone_key:
        adjust_room_cleanliness(world, zone_key, 20.0)


register_process_type("dishes_machine", on_complete=_dishes_on_complete)
register_process_type("dishes_manual", on_complete=_dishes_on_complete)


# =========================================================
# FLOORS / SURFACES — zone-scoped, not prop-scoped (see start_process()'s
# **extra -- these processes carry a "zone_key" instead of a prop_id).
# =========================================================

def _cleaning_on_complete(household, process, world):
    from systems.chores import adjust_room_cleanliness, CLEAN_CHORE_RESTORE

    zone_key = process.get("zone_key")
    if zone_key:
        adjust_room_cleanliness(world, zone_key, CLEAN_CHORE_RESTORE.get(process["template_id"], 30.0))


register_process_type("floors", on_complete=_cleaning_on_complete)
register_process_type("dusting", on_complete=_cleaning_on_complete)
