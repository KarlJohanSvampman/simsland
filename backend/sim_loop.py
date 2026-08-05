"""
sim_loop.py — main simulation tick

Systems are bucketed by how often they need to run:

  EVERY TICK    — body needs, activities, movement, reactions, item knowledge
  FAST  (÷5)   — perception, attention
  MEDIUM(÷10-20)— memory, market, cooking, relationships
  SLOW  (÷30-60)— traffic, postal, appliance degradation, news
                  jail release check (process_jail, because it needs a tick poll)
  VERY SLOW(÷300)— elections, factions, hierarchy
  WEEKLY        — schedule generation

EVENT-DRIVEN (no longer polled — fire only when something actually happened):
  health events         ← health_threshold_crossed  (emitted by body.py)
  incident pipeline     ← incident_created → call_created → resolved → arrested
  job changes           ← character_fired, interview_scheduled
  evictions             ← bills_overdue  (emitted by _check_households below)
  migration             ← household_wants_to_move (emitted by check_migration_desires)

See core/event_handlers.py for all subscriptions.
"""

from datetime import datetime
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import core.event_handlers  # noqa: F401 — registers all subscriptions on import

from core.tick_schedule import every, CADENCE, TICK_RATE_SECONDS
from core.event_bus     import flush as flush_events

# Kill switch for the event bus flush — in case a newly-live handler misbehaves.
EVENT_BUS_ENABLED = os.getenv("EVENT_BUS_ENABLED", "1") != "0"

# -- Per-tick (always) -------------------------------------------
from brain.agent_loop   import update_agent
from systems.reactions  import process_reaction_queue
from systems.item_knowledge import update_item_knowledge

# -- Fast (÷5) ---------------------------------------------------
from brain.perception   import perceive
from brain.attention    import update_attention
from systems.excuses    import check_visible_lies_for_observer, check_witnessed_hostility_for_observer

# -- Medium (÷10-20) ---------------------------------------------
from brain.memory       import decay_memories
from brain.beliefs      import polarization_drift, compute_alignment
from brain.relationships import first_impression, update_relationship_state
from systems.cooking_process import update_cooking_process
from systems.task_process import update_household_processes
from systems.market     import update_market, produce, consume_households
from systems.stock_market  import update_stocks, init_stocks
from systems.investments   import update_investment_behavior
from systems.deliveries import update_deliveries
from systems.service_worker_runtime import update_service_workers
from systems.household_monitoring   import update_household_monitoring

# -- Slow (÷30-60) — still periodic ─────────────────────────────
from systems.traffic    import update_ambient_traffic
from systems.media      import generate_news
from brain.conversations import cleanup_conversations
from systems.emergency  import trigger_incident, resolve, tick_fire_incidents   # resolve polls arrival ticks
from systems.law        import process_jail, process_trials, maybe_arrest_from_incidents
from systems.jobs       import generate_job_listings, tick_job_market, maybe_fire, process_interview, init_company_slots
from systems.postal_service     import update_postal_service
from systems.business_support   import process_business_inboxes
from systems.service_vehicles   import update_service_vehicles
from systems.transit            import update_bus
from systems.appliance_degradation import update_appliance_degradation
from systems.messaging  import deliver_messages
from systems.migration  import check_migration_desires
from systems.eviction   import check_household_for_eviction
from systems.services   import update_services

# -- Conflict / social drama ──────────────────────────────────────────────
from systems.grievances        import update_grievances
from systems.conflict_pipeline import process_conflicts
from systems.grapple         import process_grapples
from systems.social_contracts  import check_contract_violations
from systems.social_rules      import cleanup_expired_rule_exceptions
from systems.worries           import decay_worries
from systems.contagion       import tick_contagion_location, age_food_items
from systems.child_care      import tick_child_needs
from systems.bedroom_assignment import tick_bedroom_assignments
from systems.plants           import tick_plants
from systems.body_composition import tick_body_composition

# -- Very slow (÷300) ─────────────────────────────────────────────
from systems.crisis         import check_crises, process_crises
from systems.politics       import process_pending_effects, check_election
from systems.influence      import apply_public_figure_influence, apply_social_influence, resolve_exposure_influence, resolve_value_influence
from systems.socioeconomics import tick_socioeconomics
from systems.reputation     import tick_reputation
from systems.secrets        import tick_secrets
from systems.hierarchy  import update_hierarchy
from systems.faction_ai import apply_faction_influence, process_rival_tensions
from systems.intimacy   import tick_intimacy
from systems.envy       import tick_envy
from systems.trauma     import tick_trauma
from systems.exercise        import tick_exercise
from systems.impulse         import tick_impulse, sync_anger_from_grievances, add_anger_pressure
from systems.domestic_control import tick_domestic_control, tick_quid_pro_quo, check_victim_revenge, tick_emotional_control
from systems.religious_repression import tick_religious_repression
from systems.pregnancy import tick_pregnancy
from systems.harassment import tick_harassment, tick_harassment_daily
from systems.baby     import tick_baby_hourly, tick_baby_daily, tick_baby_weekly
from systems.nudity_perception import tick_nudity_perception
from systems.crushes import tick_crushes
from systems.incidental_speech import tick_incidental_speech, clear_departure_flags
from systems.conditioning import tick_conditioning_weekly

# -- Weekly ───────────────────────────────────────────────────────
from systems.scheduling import generate_week_schedule, adjust_for_household
from systems.lt_needs   import update_lt_needs, reset_weekly_counts, distribute_lt_needs
from systems.social_odor import apply_odor_social_pressure
from systems.phone      import update_phone_battery, maybe_set_phone_down, maybe_forget_phone
from systems.power      import charge_device
from systems.social_events import (
    check_event_completions, check_maybe_deadlines, generate_world_events
)
from systems.calendar_events import check_calendar_reminders
from systems.story      import update_story_arc
from systems.events     import maybe_generate_shared_event


# =========================================================
# AGENT THREAD POOL
# LLM calls are I/O-bound — threads release the GIL during network waits,
# giving real parallelism even under CPython.
# =========================================================

_AGENT_WORKERS = 8
_agent_pool = ThreadPoolExecutor(max_workers=_AGENT_WORKERS, thread_name_prefix="agent")


def _run_agent(c, world, t):
    """Run one character's agent tick. Called from a worker thread."""
    update_item_knowledge(c, world)
    process_reaction_queue(c, t)
    update_agent(c, world)
    return c["id"]


# =========================================================
# CALENDAR
# =========================================================

def advance_calendar(world):
    # Server-side time-scale control (see api/admin.py). This used to just
    # mirror datetime.now() every tick -- there was no simulated-time
    # concept to speed up. Now sim_time is its own accumulator, seeded from
    # real time so 1x behaves identically to before. The speedup itself
    # comes from main.py's loop() firing ticks more often in real time as
    # time_scale increases, not from multiplying the increment here --
    # each tick still only adds one nominal TICK_RATE_SECONDS.
    if "sim_time" not in world:
        world["sim_time"] = time.time()
    else:
        world["sim_time"] += TICK_RATE_SECONDS
    now = datetime.fromtimestamp(world["sim_time"])
    world["calendar"] = {
        "year":         now.year,
        "month":        now.month,
        "day":          now.day,
        "hour":         now.hour,
        "minute":       now.minute,
        "second":       now.second,
        "minute_of_day": now.hour * 60 + now.minute,
        "weekday":      now.strftime("%A"),
        "timestamp":    world["sim_time"],
    }


def _is_monday_midnight(world):
    cal = world.get("calendar", {})
    return cal.get("weekday") == "Monday" and cal.get("hour") == 0


# =========================================================
# DIRTY TRACKING
# =========================================================

def _mark_dirty(world, char_ids=(), prop_ids=()):
    dirty = world.setdefault("_dirty", {"chars": set(), "props": set()})
    dirty["chars"].update(char_ids)
    dirty["props"].update(prop_ids)


def collect_dirty(world) -> dict:
    dirty = world.pop("_dirty", {"chars": set(), "props": set()})
    chars = {cid: world["characters"][cid] for cid in dirty["chars"] if cid in world["characters"]}
    props_raw = world.get("props", {})
    props_map = props_raw if isinstance(props_raw, dict) else {p["id"]: p for p in props_raw}
    props = {pid: props_map[pid] for pid in dirty["props"] if pid in props_map}
    return {"chars": chars, "props": props}


# =========================================================
# SPATIAL RELATIONSHIP FILTER
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
                update_relationship_state(c, o["id"])
                first_impression(o, c)
                update_relationship_state(o, c["id"])


# =========================================================
# MAIN TICK
# =========================================================

def tick(world):
    world["tick"] += 1
    t = world["tick"]

    advance_calendar(world)
    characters = list(world.get("characters", {}).values())

    # -- Weekly ─────────────────────────────────────────────
    if _is_monday_midnight(world):
        for c in characters:
            c["schedule"] = generate_week_schedule(c, world)
            adjust_for_household(c, world)
            reset_weekly_counts(c)
            distribute_lt_needs(c, world=world)  # no-op if already distributed
        tick_exercise(world)
        tick_pregnancy(world)   # weekly fitness decay + streak tracking
        tick_baby_weekly(world)
        tick_conditioning_weekly(world)

    # -- Fast: perception + attention (÷5) ──────────────────
    if every(world, CADENCE["perception"]):
        for c in characters:
            perceive(c, world)
            # "Authority hears a conflicting account via observation" —
            # see systems/excuses.py::check_visible_lies_for_observer.
            check_visible_lies_for_observer(c, world)
            # Same shape, for witnessing a punch/kick/shove/... — see
            # systems/excuses.py::check_witnessed_hostility_for_observer.
            check_witnessed_hostility_for_observer(c, world)

    if every(world, CADENCE["attention"], offset=1):
        for c in characters:
            update_attention(c, world)

    # -- Per-tick: agent brain (parallel) ─────────────────
    # Service worker NPCs are driven by update_services, not LLM — skip them.
    # Each character's LLM call is I/O-bound; workers release the GIL while
    # waiting for the network, so this gives real throughput scaling.
    agent_chars = [
        c for c in characters
        if not c.get("is_service_worker")
        and c.get("alive") is not False
        and c.get("posture") != "incapacitated"
    ]
    futs = {_agent_pool.submit(_run_agent, c, world, t): c for c in agent_chars}
    dirty_char_ids = set()
    for fut in as_completed(futs):
        try:
            dirty_char_ids.add(fut.result())
        except Exception as exc:
            c = futs[fut]
            print(f"[sim_loop] agent error for {c.get('id')}: {exc}")
    _mark_dirty(world, char_ids=dirty_char_ids)

    # -- Medium: memory / beliefs / relationships (÷15) ─────
    if every(world, CADENCE["memory_decay"], offset=2):
        for c in characters:
            decay_memories(c)

    if every(world, CADENCE["polarization"], offset=3):
        for c in characters:
            polarization_drift(c)
            compute_alignment(c)

    if every(world, CADENCE["relationships"], offset=4):
        _update_nearby_relationships(characters, world)

    # Trust-gated influence resolution -- who each character is around the
    # most (perception.py's exposure_ticks) shapes whether they adopt that
    # person's beliefs/traits (trusted) or grow suspicious (distrusted).
    # See systems/influence.py.
    if every(world, CADENCE["influence_exposure"], offset=21):
        resolve_exposure_influence(world)

    # Daily trust/respect/exposure/value-similarity weighted influence on
    # personal values (systems/schema_defaults.py's VALUE_CATEGORIES) --
    # deliberately a separate, once-a-day cadence from the exposure
    # resolver above, per the "impact over time... sum it all up maybe on
    # a daily basis" ask. See systems/influence.py::resolve_value_influence.
    if every(world, CADENCE["value_influence"], offset=13):
        resolve_value_influence(world)

    # -- Medium: household systems (÷10) ────────────────────
    if every(world, CADENCE["cooking"], offset=5):
        for c in characters:
            hh = world.get("households", {}).get(c.get("household_id"))
            if hh:
                update_cooking_process(c, hh, world)

    # Household-scoped multi-stage processes (laundry, etc.) — ticks
    # forward for every household regardless of who's nearby, same
    # cadence tier as cooking. See systems/task_process.py.
    if every(world, CADENCE["cooking"], offset=33):
        update_household_processes(world)

    if every(world, CADENCE["deliveries"], offset=6):
        deliver_messages(world)
        update_deliveries(world)

    if every(world, CADENCE["service_workers"], offset=7):
        update_service_workers(world)

    if every(world, CADENCE["household_monitoring"], offset=8):
        update_household_monitoring(world)

    # -- Medium: market (÷20) ───────────────────────────────
    if every(world, CADENCE["market"], offset=9):
        update_market(world)
        update_stocks(world)
        produce(world)
        consume_households(world)

    # -- Slow: still-periodic systems (÷30-60) ──────────────

    # Job market — init slots once, refresh daily, process interviews each cycle
    if not world.get("company_slots"):
        init_company_slots(world)
    if not world.get("job_listings"):
        generate_job_listings(world)
    if every(world, CADENCE["job_market"], offset=10):
        tick_job_market(world)          # daily turnover + new listings
        for c in characters:
            maybe_fire(c, world)        # emits character_fired → apply_for_job
            process_interview(c, world) # polls interview.tick; emits character_hired

    if every(world, CADENCE["traffic"], offset=11):
        update_ambient_traffic(world)

    # Not every()-gated -- the 15-sim-minute bus schedule (see transit.py)
    # needs single-tick precision to catch the boundary reliably.
    update_bus(world)

    if every(world, CADENCE["postal"], offset=12):
        update_postal_service(world)

    if every(world, CADENCE["business_support"], offset=14):
        process_business_inboxes(world)

    if every(world, CADENCE["appliance_degradation"], offset=13):
        update_appliance_degradation(world)

    if every(world, CADENCE["service_workers"], offset=14):
        update_service_vehicles(world)

    if every(world, CADENCE["service_workers"], offset=18):
        update_services(world)

    # World-level random incidents (character-level ones emitted in agent_loop)
    if every(world, CADENCE["arrests"], offset=15):
        trigger_incident(world, None)  # world-level random only
        resolve(world)                 # poll responder arrival ticks
        maybe_arrest_from_incidents(world)

    if every(world, CADENCE["fires"], offset=16):
        tick_fire_incidents(world)

    # Jail release still needs tick poll
    if every(world, CADENCE["trials"], offset=16):
        for c in characters:
            process_jail(c, world)     # emits character_released
        process_trials(world)          # emits character_jailed / character_acquitted

    if every(world, CADENCE["news"], offset=17):
        generate_news(world)
        maybe_generate_shared_event(world)

    # Conversations threaded via action_router.py's apply_speech() aren't
    # tied to a scripted activity with its own end condition anymore, so
    # this is what retires them after a period of silence.
    if every(world, CADENCE["conversation_cleanup"], offset=19):
        cleanup_conversations(world)

    if every(world, CADENCE["job_market"], offset=20):
        for c in characters:
            update_investment_behavior(c, world)

    # Eviction / migration: emit events when thresholds crossed
    if every(world, CADENCE["evictions"], offset=18):
        for hh in world.get("households", {}).values():
            check_household_for_eviction(hh, world)  # emits bills_overdue

    if every(world, CADENCE["migration"], offset=19):
        check_migration_desires(world)               # emits household_wants_to_move

    # -- Conflict / social drama ────────────────────────────────────────
    if every(world, CADENCE["conflicts"], offset=24):
        process_conflicts(world)

    if every(world, CADENCE["grapples"], offset=35):
        process_grapples(world)

    if every(world, CADENCE["grievances"], offset=25):
        update_grievances(world)    # decay + emit confrontation_desired

    if every(world, CADENCE["contract_checks"], offset=26):
        check_contract_violations(world)  # emits contract_violated
        cleanup_expired_rule_exceptions(world)  # GC only, see social_rules.py
        decay_worries(world)  # passive suspicion decay, see worries.py

    # -- Daily stats drift ──────────────────────────────────
    if every(world, CADENCE["socioeconomics"], offset=19):
        try:
            from core.definitions import load_definitions
            _defs = load_definitions(world.get("sim_id", "default"))
            tick_socioeconomics(world, _defs)
        except Exception:
            pass
        tick_reputation(world)
        tick_secrets(world)
        tick_envy(world)
        tick_trauma(world)
        tick_domestic_control(world)
        tick_quid_pro_quo(world)
        tick_emotional_control(world)
        tick_religious_repression(world)
        tick_harassment_daily(world)
        tick_baby_daily(world)
        for _c in characters:
            sync_anger_from_grievances(_c, world)
            check_victim_revenge(_c, world)

    # -- Clear one-tick departure flags (must be first) ────
    clear_departure_flags(world)

    # -- Intimacy arousal decay (every tick) ───────────────
    tick_intimacy(world)

    # -- Impulse control pressure + boilover (every tick) ───
    tick_impulse(world)
    tick_harassment(world)
    tick_baby_hourly(world)
    tick_nudity_perception(world)
    tick_crushes(world)
    tick_incidental_speech(world)

    # -- Very slow (÷300) ───────────────────────────────────
    if every(world, CADENCE["crisis"], offset=20):
        check_crises(world)
        process_crises(world)

    if every(world, CADENCE["election"], offset=21):
        check_election(world)
        process_pending_effects(world)

    if every(world, CADENCE["faction"], offset=22):
        apply_faction_influence(world)
        apply_public_figure_influence(world)
        apply_social_influence(world)
        process_rival_tensions(world)

    if every(world, CADENCE["hierarchy"], offset=23):
        update_hierarchy(world)

    # -- Body / lt_needs systems ────────────────────────────
    if every(world, CADENCE["lt_needs"], offset=27):
        for c in characters:
            update_lt_needs(c, world)

    if every(world, CADENCE["social_odor"], offset=28):
        for c in characters:
            apply_odor_social_pressure(c, world)

    # -- Disease/contagion proximity sweep, grouped by building ────
    if every(world, CADENCE["contagion"], offset=36):
        groups = {}
        for c in characters:
            c["location_tile"] = f"{int(c.get('x', 0))},{int(c.get('y', 0))}"
            groups.setdefault(c.get("building_id"), []).append(c)
        for group in groups.values():
            if len(group) > 1:
                tick_contagion_location(group, world)

    # -- Child needs oversight + baseline accountability contract ──
    if every(world, CADENCE["child_care"], offset=37):
        tick_child_needs(world)

    # -- Age-based bedroom ownership ────────────────────────────────
    if every(world, CADENCE["bedroom_assignment"], offset=38):
        tick_bedroom_assignments(world)

    # -- Plant growth/moisture/weeds ─────────────────────────────────
    if every(world, CADENCE["plants"], offset=39):
        tick_plants(world)

    # -- Food freshness decay ─────────────────────────────────────────
    if every(world, CADENCE["food_aging"], offset=40):
        age_food_items(world)

    # -- Body weight/fitness-trait sync ────────────────────────────────
    if every(world, CADENCE["body_composition"], offset=41):
        tick_body_composition(world)

    # -- Battery drain + charging (phone, laptop, ...) (÷5) ───────────
    if every(world, CADENCE["phone_battery"], offset=29):
        for c in characters:
            act = c.get("activity") or {}
            if act.get("interaction") == "charge":
                charge_device(c, world)
            else:
                update_phone_battery(c)

    # -- Phone carry/drop/forget behavior ────────────────────────────
    if every(world, CADENCE["phone_behavior"], offset=30):
        for c in characters:
            maybe_set_phone_down(c, world)
            last_building = c.get("_last_building_id")
            current_building = c.get("building_id")
            if last_building is not None and current_building != last_building:
                maybe_forget_phone(c, world, last_building)
            c["_last_building_id"] = current_building

    # -- Individual wait activities (microwave, phone hold, ...) ────
    # c["character_wait"] is deliberately its own field, not folded into
    # c["activity"] — agent_loop.py returns early every tick whenever
    # c["activity"] is truthy (skips straight to execute_activity(), never
    # reaches the LLM decision call), so a character with something
    # sitting in c["activity"] can never be "free to do other things
    # meanwhile." The wait state has to live somewhere the LLM loop
    # doesn't treat as blocking.
    if every(world, CADENCE["character_wait"], offset=34):
        for c in characters:
            wait = c.get("character_wait")
            if wait and not wait.get("ready") and world["tick"] >= wait.get("ready_at_tick", 0):
                wait["ready"] = True
                from brain.cognition_scheduler import wake_character
                wake_character(c, world, "wait_ready")

    # -- Maybe-RSVP deadline nudges ──────────────────────────────
    if every(world, CADENCE["maybe_deadlines"], offset=31):
        check_maybe_deadlines(world)

    if every(world, CADENCE["calendar_events"], offset=32):
        check_calendar_reminders(world)

    # Story arcs are lightweight — keep per-tick
    for c in characters:
        update_story_arc(c)

    # Process events queued this tick (emitted from worker threads during
    # agent updates and from the systems above) — must run last, main-thread
    # only, after every emit() site for this tick has had a chance to fire.
    if EVENT_BUS_ENABLED:
        flush_events(world)
