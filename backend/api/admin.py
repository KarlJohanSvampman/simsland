"""
api/admin.py

Server-side admin controls -- currently just time-scale (see main.py's
loop(), sim_loop.py::advance_calendar(), systems/movement.py) and read-only
inspection of live per-character cognition-scheduler state. Deliberately
its own small router (not folded into api/debug.py, which is explicitly
"never touch the live simulation") so it's easy to extend with more admin
controls later without growing an unrelated file.

GET  /admin/state              -> current time_scale + simulated calendar
POST /admin/time_scale          -> set time_scale (clamped 1-10)
GET  /admin/cognition           -> world-level cognition-scheduler histogram
GET  /admin/cognition/{char_id} -> one character's live cognition state
POST /admin/reset_characters    -> wipe all characters/households (keeps
                                    the hand-placed map/buildings/roads)
POST /admin/fix_malnutrition    -> one-off correction for characters caught
                                    by the pre-fix item_templates nutrition
                                    miscalibration bug (see systems/
                                    nutrition.py's fix commit) -- resets
                                    weight_kg to a healthy BMI and clears
                                    the malnutrition disease/traits
POST /admin/purge_garbage_intentions -> one-off cleanup for the pre-fix
                                    store_intention() bug (see brain/
                                    llm_brain.py's _match_intention_type
                                    fix commit) -- removes any
                                    active_intentions entry whose "type"
                                    is really a whole sentence, not a
                                    real intention type
POST /admin/clear_stale_anchor_occupancy -> one-off cleanup for prop
                                    anchors left permanently
                                    "occupied_by" a character that no
                                    longer exists (see reset_characters'
                                    matching fix) -- e.g. a sink nobody
                                    can ever drink from again
POST /admin/set_body_need           -> force one character's body need
                                    (hunger/hydration/bladder/energy/...)
                                    to a value, for live-testing reactive
                                    behavior without waiting for it to
                                    occur naturally
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db import load_world, save_world, world_lock

router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_SIM_ID = "default"


@router.get("/state")
def get_state(sim_id: str = DEFAULT_SIM_ID):
    world = load_world(sim_id)
    return {
        "time_scale": world.get("time_scale", 1),
        "calendar":   world.get("calendar", {}),
    }


@router.post("/time_scale")
def set_time_scale(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    value = max(1, min(10, int(payload.get("value", 1))))
    with world_lock():
        world = load_world(sim_id)
        world["time_scale"] = value
        save_world(sim_id, world)
    return {"time_scale": value}


@router.post("/reset_characters")
def reset_characters(sim_id: str = DEFAULT_SIM_ID):
    """Wipes all characters and households -- the map/buildings/roads/props
    are hand-placed via the World Editor and aren't code-regenerable, so
    this deliberately leaves them untouched, only unassigning each
    building's owner_household_id since the households that owned them no
    longer exist.

    Also drops any placed_items/world_objects owned by a character this
    wipes -- a live symptom of NOT doing this: phones a character dropped
    (systems/phone.py::maybe_set_phone_down) kept sitting on the ground
    forever after that character was gone, since nothing else ever
    resolves an orphaned owner_id. Furniture-like placed_items with no
    owner_id (newspapers set down mid-read, dishware, ...) are untouched --
    only entries actually tied to a character being deleted here.

    Also clears events/incidents/calls/responders/conflicts/social_events
    -- every character is being removed here, so every entry in these
    world-level history logs is now unresolvable (a live symptom: the
    event timeline fell back to showing raw character ids once the
    characters they named were gone)."""
    with world_lock():
        world = load_world(sim_id)
        removed_ids = set(world["characters"].keys())
        world["characters"] = {}
        world["households"] = {}
        for building in world.get("buildings", []):
            building["owner_household_id"] = None

        placed_items = world.get("placed_items", {})
        if isinstance(placed_items, dict):
            for item_id in [k for k, v in placed_items.items() if v.get("owner_id") in removed_ids]:
                del placed_items[item_id]
        world_objects = world.get("world_objects", {})
        if isinstance(world_objects, dict):
            for obj_id in [k for k, v in world_objects.items() if v.get("owner_id") in removed_ids]:
                del world_objects[obj_id]

        # Live bug report: every character being wiped left several
        # world-level history logs full of entries that can now only ever
        # reference deleted characters -- confirmed live via the event
        # timeline, which fell back to showing raw ids ("char_9bf93fea &
        # char_93362e96") once api/events.py::_character_name() could no
        # longer look either one up. Since a reset removes EVERY character
        # (not a subset), every entry in these logs is orphaned, not just
        # some of them -- clearing them outright is simpler and more
        # correct than filtering, and matches this route's existing
        # placed_items/world_objects cleanup above in spirit.
        world["events"]      = []
        world["incidents"]   = []
        world["calls"]       = []
        world["responders"]  = []
        world["conflicts"]   = {}
        world["social_events"] = {}

        # Confirmed live bug: every prop anchor (systems/occupancy.py)
        # reserved by a character this wipe removes stayed permanently
        # "occupied_by" that now-nonexistent id forever after -- nobody
        # new could ever use that anchor again (find_nearest_anchor()
        # finds it, but begin_interaction()'s occupancy check always
        # fails since the occupant never matches and never releases).
        # A household's only sink getting stuck this way silently broke
        # every future resident's ability to ever mechanically drink.
        for prop in world.get("props", []):
            for anchor in prop.get("anchors", []) or []:
                if anchor.get("occupied_by"):
                    anchor["occupied_by"] = None

        save_world(sim_id, world)

    # Live bug report: a connected client's local character cache is only
    # ever updated incrementally (main.py::_build_delta merges changed
    # characters in, it never expresses "this id was removed" -- there's
    # no such message in the delta protocol) -- so wiping every character
    # here left every already-open browser tab still holding the deleted
    # population in memory, rendering them as stale "ghost" models for a
    # few seconds any time something (e.g. clicking a character in the
    # list, which recenters the camera) happened to trigger a real full
    # resnapshot before the ghosts got cleared. Forcing needs_full here
    # means the very next broadcast tick sends every connected client a
    # complete, correct snapshot instead of waiting on an unrelated
    # viewport move to eventually do it.
    try:
        from main import _clients
        for client in _clients:
            client["needs_full"] = True
    except Exception:
        pass

    return {"ok": True}


@router.post("/fix_malnutrition")
def fix_malnutrition(sim_id: str = DEFAULT_SIM_ID):
    """Item nutrition values were miscalibrated far below what
    nutrition.py's daily settlement AND body_composition.py's calorie-
    balance tick both need to keep weight stable (a few realistic meals a
    day summed to well under 1.0 "day's worth" / under
    BASELINE_DAILY_BURN), so every character was losing weight and body
    fat every single day regardless of how fed they felt -- confirmed
    live via characters pinned at nutrition.py's WEIGHT_MIN_KG floor with
    "malnutrition" while their actual hunger stat sat in the 30-40%
    range, nowhere near starving. The item data is fixed going forward;
    this is a one-off correction for characters already run down by the
    bug before that fix landed."""
    from systems.nutrition import compute_bmi, get_weight_band, _sync_weight_band_trait, _sync_weight_band_disease
    from systems.body_composition import BODY_FAT_DEFAULT, _sync_dynamic_trait

    fixed = []
    with world_lock():
        world = load_world(sim_id)
        for char_id, c in world.get("characters", {}).items():
            band = get_weight_band(compute_bmi(c))
            bc = c.get("body_composition")
            underweight = bc is not None and bc.get("body_fat_level", BODY_FAT_DEFAULT) <= 0.15
            if band not in ("thin", "skinny") and not underweight:
                continue

            height_cm = c.get("body_features", {}).get("height_cm", 170)
            height_m = max(0.5, height_cm / 100.0)
            c["weight_kg"] = round(22.0 * height_m ** 2, 1)
            c.get("body", {})["nutrients_today"] = 0.0
            new_band = get_weight_band(compute_bmi(c))
            _sync_weight_band_trait(c, new_band)
            _sync_weight_band_disease(c, new_band)

            if bc is not None:
                bc["body_fat_level"] = BODY_FAT_DEFAULT
                bc["calories_in_today"] = 0.0
                bc["calories_burned_today"] = 0.0
                _sync_dynamic_trait(c, "obese", False)
                _sync_dynamic_trait(c, "underweight", False)

            fixed.append(char_id)
        save_world(sim_id, world)

    return {"ok": True, "fixed_character_ids": fixed}


@router.post("/purge_garbage_intentions")
def purge_garbage_intentions(sim_id: str = DEFAULT_SIM_ID):
    """store_intention() (brain/agent_loop.py) used to fall back to the
    LLM's raw, free-text "then" phrase as an intention's own "type" field
    whenever it didn't cleanly match a real activity -- every real
    intention type in this codebase is a plain identifier (snake_case,
    optionally "expectation:"-prefixed) with no spaces, so a type
    containing a space is unambiguously one of these leftover sentence
    entries. They never resolved to anything and, worse, could silently
    evict genuinely important intentions (drink, an expectation, ...)
    once the (now also fixed) list filled up. One-off live cleanup."""
    purged = {}
    with world_lock():
        world = load_world(sim_id)
        for char_id, c in world.get("characters", {}).items():
            intentions = c.get("active_intentions", [])
            kept = [i for i in intentions if " " not in str(i.get("type", ""))]
            if len(kept) != len(intentions):
                purged[char_id] = len(intentions) - len(kept)
                c["active_intentions"] = kept
        save_world(sim_id, world)

    return {"ok": True, "purged_counts": purged}


@router.post("/clear_stale_anchor_occupancy")
def clear_stale_anchor_occupancy(sim_id: str = DEFAULT_SIM_ID):
    """One-off cleanup for anchors reserved by a character that no
    longer exists (e.g. from before a reset_characters call made before
    this route's own matching fix landed) -- see reset_characters'
    docstring for the full mechanism."""
    cleared = []
    with world_lock():
        world = load_world(sim_id)
        char_ids = set(world.get("characters", {}).keys())
        for prop in world.get("props", []):
            for anchor in prop.get("anchors", []) or []:
                occupant = anchor.get("occupied_by")
                if occupant and occupant not in char_ids:
                    anchor["occupied_by"] = None
                    cleared.append({"prop_id": prop.get("id"), "anchor": anchor.get("name"), "was": occupant})
        save_world(sim_id, world)

    return {"ok": True, "cleared": cleared}


@router.post("/release_stuck_anchor")
def release_stuck_anchor(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    """One-off correction for the pre-fix interrupt_activity() gap (see
    systems/occupancy.py) -- a character whose activity was interrupted
    (not naturally completed) kept their prop anchor "occupied_by"
    forever even after wandering off elsewhere, permanently blocking
    anyone else queued for it. Releases whatever c["occupying"] points
    to for one character and clears their (already-stale) activity."""
    char_id = payload.get("character_id")
    with world_lock():
        world = load_world(sim_id)
        c = world.get("characters", {}).get(char_id)
        if not c:
            return {"ok": False, "error": "character not found"}
        from systems.occupancy import interrupt_activity
        occupying_before = c.get("occupying")
        interrupt_activity(c, world)
        save_world(sim_id, world)
    return {"ok": True, "released": occupying_before}


@router.post("/set_body_need")
def set_body_need(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    """Live-testing helper: force one character's body need to a value
    without waiting for it to occur naturally. payload: {"character_id",
    "need", "value"}."""
    char_id = payload.get("character_id")
    need = payload.get("need")
    value = payload.get("value")
    with world_lock():
        world = load_world(sim_id)
        c = world.get("characters", {}).get(char_id)
        if not c:
            return {"ok": False, "error": "character not found"}
        c.setdefault("body", {})[need] = value
        save_world(sim_id, world)
    return {"ok": True, "character_id": char_id, "need": need, "value": value}


@router.get("/pending_agents")
def get_pending_agents():
    """Live-debug introspection into sim_loop.py's in-process
    _pending_agent_ids/_pending_agent_since state (not persisted world
    data -- this reads the actual running process's module state)."""
    import sim_loop
    import time
    now = time.time()
    return {
        "pending_ids": sorted(sim_loop._pending_agent_ids),
        "pending_since_ago_seconds": {
            cid: round(now - since, 1) for cid, since in sim_loop._pending_agent_since.items()
        },
        "generations": dict(sim_loop._agent_generation),
        "stale_pending_threshold": sim_loop.STALE_PENDING_SECONDS,
    }


@router.get("/cognition")
def get_cognition_histogram(sim_id: str = DEFAULT_SIM_ID):
    world = load_world(sim_id)
    tick = world.get("tick", 0)
    characters = world.get("characters", {})

    wake_reason_counts: dict = {}
    idle_streak_total = 0
    due_now = 0
    n = 0
    for c in characters.values():
        cog = c.get("cognition")
        if cog is None:
            continue
        n += 1
        reason = cog.get("wake_reason")
        if reason:
            wake_reason_counts[reason] = wake_reason_counts.get(reason, 0) + 1
        idle_streak_total += cog.get("idle_streak", 0)
        if tick >= cog.get("next_think_tick", 0):
            due_now += 1

    # Instantaneous snapshot above (what's pending right now) + Round 10's
    # rolling in-process counters below (what's actually been happening —
    # think()s/tick, wake-reason histogram of fired thinks, prompt size,
    # resolver accept/ambiguous/fail rates, describe/recall usage) — see
    # brain/cognition_scheduler.py's get_stats(). The rolling counters are
    # process-lifetime, not filtered by sim_id (this deployment only ever
    # runs one sim per process today).
    from brain.cognition_scheduler import get_stats
    return {
        "tick": tick,
        "character_count": n,
        "pending_wake_reasons": wake_reason_counts,
        "due_now": due_now,
        "mean_idle_streak": round(idle_streak_total / n, 2) if n else 0,
        "rolling": get_stats(),
    }


@router.get("/cognition/{char_id}")
def get_cognition_for_char(char_id: str, sim_id: str = DEFAULT_SIM_ID):
    world = load_world(sim_id)
    c = world.get("characters", {}).get(char_id)
    if not c:
        return JSONResponse({"error": f"character '{char_id}' not found"}, status_code=404)
    return {
        "tick": world.get("tick", 0),
        "cognition": c.get("cognition", {}),
    }
