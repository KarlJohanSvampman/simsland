"""
sim_loop.py — main simulation tick

Systems are bucketed by how often they need to run:

  EVERY TICK   — body needs, activities, movement, reactions, item knowledge
  FAST (÷5)    — perception, attention
  MEDIUM (÷10-20) — memory, market, cooking, relationships
  SLOW (÷30-60)   — health events, news, traffic, job market
  VERY SLOW (÷300) — elections, factions, hierarchy, migration
  WEEKLY       — schedule generation

Event-driven systems subscribe to core.event_bus and only fire
when something actually happened (see core/event_bus.py).
"""

from datetime import datetime
import time

from core.tick_schedule import every, CADENCE
from core.event_bus     import emit, flush as flush_events

# -- Per-tick (always) -------------------------------------------
from brain.agent_loop   import update_agent
from systems.reactions  import process_reaction_queue
from systems.item_knowledge import update_item_knowledge

# -- Fast (÷5) ---------------------------------------------------
from brain.perception   import perceive
from brain.attention    import update_attention

# -- Medium (÷10-20) ---------------------------------------------
from brain.memory       import decay_memories
from brain.beliefs      import polarization_drift, compute_alignment
from brain.relationships import first_impression, update_relationship_state
from systems.cooking_process import update_cooking_process
from systems.market     import update_market, produce, consume_households
from systems.deliveries import update_deliveries
from systems.service_worker_runtime import update_service_workers
from systems.household_monitoring   import update_household_monitoring

# -- Slow (÷30-60) -----------------------------------------------
from systems.traffic    import update_ambient_traffic
from systems.media      import generate_news
from systems.emergency  import trigger_incident, auto_report_incidents, dispatch, resolve
from systems.law        import maybe_arrest_from_incidents, process_trials, process_jail
from systems.health     import trigger_health_event, process_health
from systems.jobs       import generate_job_listings, maybe_fire, apply_for_job, process_interview
from systems.postal_service     import update_postal_service
from systems.service_vehicles   import update_service_vehicles
from systems.appliance_degradation import update_appliance_degradation
from systems.messaging  import deliver_messages

# -- Very slow (÷300) --------------------------------------------
from systems.crisis     import check_crises, process_crises
from systems.politics   import process_pending_effects, check_election
from systems.influence  import apply_public_figure_influence, apply_social_influence
from systems.hierarchy  import update_hierarchy
from systems.eviction   import process_evictions
from systems.migration  import process_migration
from systems.faction_ai import apply_faction_influence

# -- Weekly ------------------------------------------------------
from systems.scheduling import generate_week_schedule, adjust_for_household
from systems.story      import update_story_arc
from systems.events     import maybe_generate_shared_event


# =========================================================
# CALENDAR
# =========================================================

def advance_calendar(world):
    now = datetime.now()
    world["calendar"] = {
        "year":      now.year,
        "month":     now.month,
        "day":       now.day,
        "hour":      now.hour,
        "minute":    now.minute,
        "second":    now.second,
        "weekday":   now.strftime("%A"),
        "timestamp": time.time(),
    }


def _is_monday_midnight(world):
    cal = world.get("calendar", {})
    return cal.get("weekday") == "Monday" and cal.get("hour") == 0


# =========================================================
# DIRTY TRACKING
# Marks which entities changed this tick so the broadcaster
# sends only deltas instead of the full world every tick.
# =========================================================

def _mark_dirty(world, char_ids=(), prop_ids=()):
    dirty = world.setdefault("_dirty", {"chars": set(), "props": set()})
    dirty["chars"].update(char_ids)
    dirty["props"].update(prop_ids)


def collect_dirty(world) -> dict:
    """
    Return dirty entities and reset tracking.
    Called by main.py after tick() to build the WS delta payload.
    """
    dirty = world.pop("_dirty", {"chars": set(), "props": set()})

    chars = {
        cid: world["characters"][cid]
        for cid in dirty["chars"]
        if cid in world["characters"]
    }

    props_raw = world.get("props", {})
    props_map = props_raw if isinstance(props_raw, dict) else {p["id"]: p for p in props_raw}
    props = {
        pid: props_map[pid]
        for pid in dirty["props"]
        if pid in props_map
    }

    return {"chars": chars, "props": props}


# =========================================================
# SPATIAL RELATIONSHIP FILTER
# Replaces the every-tick O(N^2) loop with a proximity gate:
# only update relationships for characters within ~8 tiles.
# =========================================================

_RELATIONSHIP_RADIUS = 8


def _update_nearby_relationships(characters, world):
    n = len(characters)
    for i in range(n):
        c = characters[i]
        for j in range(i + 1, n):
            o = characters[j]
            if (abs(c.get("x", 0) - o.get("x", 0)) +
                    abs(c.get("y", 0) - o.get("y", 0))) <= _RELATIONSHIP_RADIUS:
                first_impression(c, o)
                update_relationship_state(c, o)
                first_impression(o, c)
                update_relationship_state(o, c)


# =========================================================
# MAIN TICK
# =========================================================

def tick(world):
    world["tick"] += 1
    t = world["tick"]

    advance_calendar(world)

    characters = list(world.get("characters", {}).values())

    # -- Weekly: regenerate schedules --------------------------
    if _is_monday_midnight(world):
        for c in characters:
            c["schedule"] = generate_week_schedule(c, world)
            adjust_for_household(c, world)

    # -- Fast: perception + attention (÷5) ---------------------
    if every(world, CADENCE["perception"]):
        for c in characters:
            perceive(c, world)

    if every(world, CADENCE["attention"], offset=1):
        for c in characters:
            update_attention(c, world)

    # -- Per-tick: agent brain + reactions ---------------------
    dirty_char_ids = set()
    for c in characters:
        update_item_knowledge(c, world)
        process_reaction_queue(c, t)
        update_agent(c, world)
        dirty_char_ids.add(c["id"])

    _mark_dirty(world, char_ids=dirty_char_ids)

    # -- Medium: memory / beliefs / relationships (÷15) --------
    if every(world, CADENCE["memory_decay"], offset=2):
        for c in characters:
            decay_memories(c)

    if every(world, CADENCE["polarization"], offset=3):
        for c in characters:
            polarization_drift(c)
            compute_alignment(c)

    if every(world, CADENCE["relationships"], offset=4):
        _update_nearby_relationships(characters, world)

    # -- Medium: household systems (÷10) -----------------------
    if every(world, CADENCE["cooking"], offset=5):
        for c in characters:
            hh = world.get("households", {}).get(c.get("household_id"))
            if hh:
                update_cooking_process(c, hh, world)

    if every(world, CADENCE["deliveries"], offset=6):
        deliver_messages(world)
        update_deliveries(world)

    if every(world, CADENCE["service_workers"], offset=7):
        update_service_workers(world)

    if every(world, CADENCE["household_monitoring"], offset=8):
        update_household_monitoring(world)

    # -- Medium: market (÷20) ----------------------------------
    if every(world, CADENCE["market"], offset=9):
        update_market(world)
        produce(world)
        consume_households(world)

    # -- Slow: health, incidents, law (÷30-60) -----------------
    if every(world, CADENCE["health"], offset=10):
        for c in characters:
            trigger_health_event(c, world)
            process_health(c, world)

    if every(world, CADENCE["job_market"], offset=11):
        generate_job_listings(world)
        for c in characters:
            maybe_fire(c, world)
            apply_for_job(c, world)
            process_interview(c, world)

    if every(world, CADENCE["traffic"], offset=12):
        update_ambient_traffic(world)

    if every(world, CADENCE["postal"], offset=13):
        update_postal_service(world)

    if every(world, CADENCE["appliance_degradation"], offset=14):
        update_appliance_degradation(world)

    if every(world, CADENCE["service_workers"], offset=15):
        update_service_vehicles(world)

    if every(world, CADENCE["arrests"], offset=16):
        trigger_incident(world, None)
        auto_report_incidents(world)
        dispatch(world)
        resolve(world)
        maybe_arrest_from_incidents(world)

    if every(world, CADENCE["trials"], offset=17):
        for c in characters:
            process_jail(c, world)
        process_trials(world)

    if every(world, CADENCE["news"], offset=18):
        generate_news(world)
        maybe_generate_shared_event(world)

    # -- Very slow: big world systems (÷300) -------------------
    if every(world, CADENCE["crisis"], offset=19):
        check_crises(world)
        process_crises(world)

    if every(world, CADENCE["election"], offset=20):
        check_election(world)
        process_pending_effects(world)

    if every(world, CADENCE["faction"], offset=21):
        apply_faction_influence(world)
        apply_public_figure_influence(world)
        apply_social_influence(world)

    if every(world, CADENCE["hierarchy"], offset=22):
        update_hierarchy(world)

    if every(world, CADENCE["migration"], offset=23):
        process_migration(world)

    if every(world, CADENCE["evictions"], offset=24):
        process_evictions(world)

    # Story arcs are lightweight — keep per-tick
    for c in characters:
        update_story_arc(c)

    # -- Flush event bus ---------------------------------------
    flush_events(world)
