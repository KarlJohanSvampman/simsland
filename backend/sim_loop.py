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
import random
import time

import core.event_handlers  # noqa: F401 — registers all subscriptions on import
from core import tick_profile as _prof

from core.tick_schedule import every, CADENCE, TICK_RATE_SECONDS
from core.event_bus     import flush as flush_events

# Kill switch for the event bus flush — in case a newly-live handler misbehaves.
EVENT_BUS_ENABLED = os.getenv("EVENT_BUS_ENABLED", "1") != "0"

# -- Per-tick (always) -------------------------------------------
from brain.agent_loop   import update_agent
from brain.intentions   import set_current_tick
from systems.reactions  import process_reaction_queue
from systems.item_knowledge import update_item_knowledge

# -- Fast (÷5) ---------------------------------------------------
from brain.perception   import perceive
from brain.attention    import update_attention
from systems.excuses    import check_visible_lies_for_observer, check_witnessed_hostility_for_observer

# -- Medium (÷10-20) ---------------------------------------------
from brain.memory       import decay_memories
from brain.opinions     import polarize_opinions, compute_political_lean
from brain.relationships import first_impression, update_relationship_state, ensure_relationship
from systems.contact_designation import accumulate_hours, evaluate_weekly_designations
from systems.peer_influence import resolve_cognitive_adoption
from systems.trait_budget import recompute_budget_on_birthday
from systems.cooking_process import update_cooking_process
from systems.reading_process import update_reading_process
from systems.task_process import update_household_processes
from systems.market     import update_market, produce, consume_households
from systems.stock_market  import update_stocks, init_stocks
from systems.investments   import update_investment_behavior
from systems.deliveries import update_deliveries
from systems.service_worker_runtime import update_service_workers
from systems.household_monitoring   import update_household_monitoring
from systems.caretaker_negotiation  import tick_caretaker_negotiation
from systems.childcare_arrangement  import tick_babysitting_requests

# -- Slow (÷30-60) — still periodic ─────────────────────────────
from systems.traffic    import update_ambient_traffic
from systems.media      import generate_news
from brain.conversations import cleanup_conversations
from systems.emergency  import trigger_incident, resolve, tick_fire_incidents, auto_report_incidents   # resolve polls arrival ticks
from systems.health     import apply_severity_consequences
from systems.law        import process_jail, process_trials, maybe_arrest_from_incidents, process_prison_reporting
from systems.jobs       import generate_job_listings, tick_job_market, maybe_fire, advance_job_application, init_company_slots
from systems.driver_license import advance_driver_license, maybe_practice_with_companion
from systems.postal_service     import update_postal_service
from systems.newspaper_delivery import update_newspaper_delivery
from systems.business_support   import process_business_inboxes
from systems.service_vehicles   import update_service_vehicles
from systems.rideshare          import update_rideshare_vehicles
from systems.transit            import update_bus
from systems.appliance_degradation import update_appliance_degradation
from systems.messaging  import deliver_messages
from systems.migration  import check_migration_desires
from systems.eviction   import check_household_for_eviction
from systems.services   import update_services
from systems.economy    import apply_expenses
from systems.government_debt import assess_monthly_tax, apply_debt_consequences
from systems.government_budget import tick_government_budget
from systems.credit     import tick_monthly_card_cycle
from systems.personal_items import recall_overdue_loans
from systems.validation    import tick_popularity_decay
from systems.social_media  import tick_post_engagement
from systems.convenience_store import update_convenience_store_staffing

# -- Conflict / social drama ──────────────────────────────────────────────
from systems.grievances        import update_grievances
from systems.conflict_pipeline import process_conflicts
from systems.grapple         import process_grapples
from systems.social_contracts  import check_contract_violations
from systems.social_rules      import cleanup_expired_rule_exceptions
from systems.worries           import decay_worries
from systems.persona_expectations import tick_persona_expectations
from systems.libido import tick_libido
from systems.intimate_item_discovery import tick_discovery_checks
from systems.stories import decay_stories
from systems.workplace_reputation import decay_workplace_views
from systems.life_comparison import tick_life_comparison
from systems.sports_leagues import tick_sports_leagues
from systems.sports import schedule_game_day_events, kickoff_scheduled_games, apply_game_day_outcomes
from systems.sports_broadcast import update_game_broadcast
from systems.crime import (
    maybe_recruit_into_crime, tick_criminal_career_progression, tick_gang_wars,
    tick_pi_assignments, maybe_offer_corruption, tick_corruption_risk,
)
from systems.darknet import generate_darknet_listings
from systems.psychosis import tick_psychosis
from systems.body import decay_stress
from systems.diary import maybe_write_diary
from systems.sociopathy import (
    is_sociopath, maybe_introduce_false_identity,
    maybe_discover_persona_mismatch, maybe_plant_drama,
)
from systems.behavior_patterns import aggregate_daily_observations
from systems.contagion       import tick_contagion_location, age_food_items
from systems.child_care      import tick_child_needs
from systems.child_welfare   import tick_child_welfare
from systems.child_disclosure import tick_child_disclosure
from systems.dependent_tracking import tick_dependent_checks
from systems.bedroom_assignment import tick_bedroom_assignments
from systems.plants           import tick_plants
from systems.body_composition import tick_body_composition

# -- Very slow (÷300) ─────────────────────────────────────────────
from systems.crisis         import check_crises, process_crises
from systems.politics       import process_pending_effects, check_election, schedule_upcoming_legislation, resolve_legislation_votes
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
from brain.perception import cleanup_ambient_sounds
from systems.conditioning import tick_conditioning_weekly

# -- Weekly ───────────────────────────────────────────────────────
from systems.scheduling import generate_week_schedule, adjust_for_household
from systems.lt_needs   import update_lt_needs, reset_weekly_counts, distribute_lt_needs, generate_lt_need_intentions
from systems.social     import generate_social_intentions as generate_socialize_intention
from systems.social     import interrupt_socializing_with_unavailable_targets
from systems.social_odor import apply_odor_social_pressure
from systems.phone      import update_phone_battery, maybe_set_phone_down, maybe_forget_phone
from systems.power      import charge_device
from systems.calendar_events import check_calendar_reminders
from systems.reminders import check_reminders
from systems.contract_clauses import tick_contract_clauses, tick_pending_payouts
from systems.insurance import tick_insurance_renewals
from systems.story      import update_story_arc
from systems.events     import maybe_generate_shared_event


# =========================================================
# CHARACTER UPDATES
# Each character's update_agent() runs on the tick thread, in turn. Nothing in it waits for
# a model any more: a decision is REQUESTED (brain/cognition_actor.py) and arrives later as a
# `decision_ready` event. The old design ran every character's whole update on a thread pool
# and abandoned (discarded) whatever hadn't finished within a 3-second budget -- every slow
# model call cost the world lock 3 seconds and lost the decision.
# =========================================================

# Kept only so older introspection (api/admin.py) keeps importing; always empty now.
_pending_agent_ids = set()
_pending_agent_since = {}
_agent_generation = {}
AGENT_WAIT_BUDGET_SECONDS = None
STALE_PENDING_SECONDS = 180.0


def _run_agent(c, world, t):
    """Run one character's agent tick. Called from a worker thread."""
    _prof.mark("agent:item_knowledge")
    update_item_knowledge(c, world)
    _prof.mark("agent:reaction_queue")
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
    # cal["hour"] stays 0 for a full 3600 ticks (the entire first hour of
    # Monday, since one tick == one nominal game-second -- see
    # advance_calendar()) -- a bare weekday+hour check used to fire every
    # single one of those ticks, re-running weekly resets (schedule
    # regen, apply_expenses, ...) thousands of times per week instead of
    # once. Stamp the (year, month, day) it last fired on and only allow
    # one hit per calendar day, same guard shape as the monthly check
    # below. Stored as a string, not a tuple, so the Postgres JSON
    # round-trip (tuples -> lists) can't silently break the comparison.
    cal = world.get("calendar", {})
    if not (cal.get("weekday") == "Monday" and cal.get("hour") == 0):
        return False
    stamp = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}"
    if world.get("_last_weekly_stamp") == stamp:
        return False
    world["_last_weekly_stamp"] = stamp
    return True


def _is_month_start_midnight(world):
    # Same one-shot-per-period guard as _is_monday_midnight above, and for
    # the same reason: day==1/hour==0 alone stays true for 3600 ticks.
    cal = world.get("calendar", {})
    if not (cal.get("day") == 1 and cal.get("hour") == 0):
        return False
    stamp = f"{cal.get('year')}-{cal.get('month')}"
    if world.get("_last_monthly_stamp") == stamp:
        return False
    world["_last_monthly_stamp"] = stamp
    return True


def _is_hour_boundary(world):
    """Same one-shot-per-period stamp guard as _is_monday_midnight above,
    but for real hour boundaries -- cal["minute"] stays 0 for a full 60
    ticks (see advance_calendar()), so a bare minute==0 check would fire
    60 times an hour without this. Note this is real calendar-boundary
    detection, NOT the same thing as home_presence.py's
    HOME_PRESENCE_TICKS_PER_HOUR sampling (a tick-count divisor that
    happens to equal an hour but isn't boundary-aware) -- see that
    module's own docstring for the distinction; systems/
    household_summary.py's hourly rollup needs a real boundary, not a
    sample."""
    cal = world.get("calendar", {})
    if cal.get("minute") != 0:
        return False
    stamp = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}-{cal.get('hour')}"
    if world.get("_last_hourly_stamp") == stamp:
        return False
    world["_last_hourly_stamp"] = stamp
    return True


def _is_new_calendar_day(world, tag):
    """Same one-shot-per-period guard as _is_monday_midnight/
    _is_month_start_midnight above, but for blocks that are meant to run
    once per real day at WHATEVER moment their every()-gated cadence next
    fires, not a specific hour. CADENCE["daily_finance"]/["value_influence"]
    are both 24 (24 TICKS -- ~24 real seconds -- not 24 hours, despite
    their own "daily"/"once/sim-day" naming) -- confirmed live the same
    bug shape already found and fixed in jobs.py::maybe_fire,
    body_composition.py::tick_body_composition, and
    contagion.py::age_food_items: several of the functions gated on
    these blocks (systems/influence.py::resolve_value_influence,
    systems/mental_health_effects.py::tick_depression_effects, ...)
    apply a real per-call step/accumulator with no gate of their own,
    assuming their caller only invokes them once a day. Rather than
    patching every downstream function individually, gate the whole
    block once here -- they were always meant to run together as one
    daily batch anyway (see the single `if every(...)` wrapping all of
    them in tick())."""
    cal = world.get("calendar", {})
    stamp = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}"
    key = f"_last_{tag}_day"
    if world.get(key) == stamp:
        return False
    world[key] = stamp
    return True


# =========================================================
# DIRTY TRACKING
# =========================================================

# Confirmed live bug, likely the single biggest contributor to this whole
# session's "nothing updates without a manual refresh" reports: this used
# to store each bucket as a real Python set(), which is NOT JSON-
# serializable -- fine as long as _mark_dirty() was only ever called (and
# _dirty popped via collect_dirty()) from WITHIN _run_tick_and_persist()'s
# own single load->tick->save span, entirely in memory. But every OTHER
# world_lock()-protected write (api/middleware_bridge.py's /execute --
# literally how EVERY middleware-driven character's decision is applied
# -- and every api/admin.py endpoint) does its own separate load_world()/
# save_world() round-trip through Postgres, which json.dumps()'s world
# wholesale -- a set anywhere in it would crash that save outright, so
# none of those call sites could ever safely call this at all. The result:
# a middleware character's every action, movement, and state change was
# invisible to every connected client's WebSocket feed -- not stale, not
# delayed, NEVER delivered -- until an unrelated dirty-marking event
# elsewhere happened to also touch them, or the client's camera moved
# enough to force a full resync from the DB. Lists are JSON-safe and work
# identically here: collect_dirty() only ever iterates these, never relies
# on set semantics, and a duplicate id costs one harmless redundant dict
# lookup.
_DIRTY_DEFAULT = {"chars": [], "props": [], "placed_items": [], "world_objects": []}


def _mark_dirty(world, char_ids=(), prop_ids=(), placed_item_ids=(), world_object_ids=()):
    dirty = world.setdefault("_dirty", dict(_DIRTY_DEFAULT))
    dirty["chars"].extend(char_ids)
    dirty["props"].extend(prop_ids)
    dirty["placed_items"].extend(placed_item_ids)
    dirty["world_objects"].extend(world_object_ids)


def collect_dirty(world) -> dict:
    dirty = world.pop("_dirty", dict(_DIRTY_DEFAULT))
    chars = {cid: world["characters"][cid] for cid in dirty["chars"] if cid in world["characters"]}
    props_raw = world.get("props", {})
    props_map = props_raw if isinstance(props_raw, dict) else {p["id"]: p for p in props_raw}
    props = {pid: props_map[pid] for pid in dirty["props"] if pid in props_map}
    placed_items_map = world.get("placed_items", {})
    placed_items = {iid: placed_items_map[iid] for iid in dirty["placed_items"] if iid in placed_items_map}
    # world_objects has no stable id->entry map (it's a plain list, unlike
    # placed_items) -- objects are matched by their own "id" field, which
    # producers (e.g. service_worker_runtime.py) must stamp themselves.
    world_objects_by_id = {o["id"]: o for o in world.get("world_objects", []) if o.get("id")}
    world_objects = {oid: world_objects_by_id[oid] for oid in dirty["world_objects"] if oid in world_objects_by_id}
    return {"chars": chars, "props": props, "placed_items": placed_items, "world_objects": world_objects}


# =========================================================
# SPATIAL RELATIONSHIP FILTER
# =========================================================

_RELATIONSHIP_RADIUS = 8

# Simulated hours of co-presence credited each time this sweep fires for a
# nearby pair -- this cadence fires every CADENCE["relationships"] ticks,
# and 1 tick == TICK_RATE_SECONDS simulated seconds (advance_calendar()),
# so a pair that's nearby every single firing across a full week logs
# exactly 168 hours. Feeds systems/contact_designation.py's weekly
# promote/demote pass, not rel["state"] (that stays purely stat-driven).
_HOURS_PER_RELATIONSHIP_SWEEP = (CADENCE["relationships"] * TICK_RATE_SECONDS) / 3600.0


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
                accumulate_hours(ensure_relationship(c, o["id"]), _HOURS_PER_RELATIONSHIP_SWEEP)
                first_impression(o, c)
                update_relationship_state(o, c["id"])
                accumulate_hours(ensure_relationship(o, c["id"]), _HOURS_PER_RELATIONSHIP_SWEEP)


# =========================================================
# MAIN TICK
# =========================================================

def tick(world):
    """One simulation tick (profiled per section -- see core/tick_profile.py)."""
    _prof.begin_tick()
    try:
        return _tick_impl(world)
    finally:
        _prof.end_tick()


def _tick_impl(world):
    world["tick"] += 1
    t = world["tick"]
    set_current_tick(t)
    _prof.mark("tick_head")
    from core import event_log as _event_log
    _event_log.set_tick(t)

    advance_calendar(world)
    # The clock announces hour/day/week/month boundaries (handled at flush, below) and the
    # scheduler runs whatever timers are due; neither polls anything.
    _prof.mark("clock_and_scheduler")
    from core import clock as _clock, scheduler as _scheduler
    _clock.advance(world)
    _scheduler.install(world)
    _scheduler.fire_due(world)
    _prof.mark("tick_head")
    # Workplace NPCs (systems/workplace_npc.py) are real characters (they
    # live in world["characters"], hold relationships, accrue workplace_
    # reputation/dependency) but deliberately have no body/needs/x/y at
    # all -- by design, per their own docstring, "never physically
    # rendered or walked". Every one of the ~30 population-wide sweeps
    # below (schedules, life comparison, socioeconomics, ...) assumes a
    # full character shape and crashes on one of these bare dicts, so
    # they're excluded at this single source point rather than needing a
    # guard added to every sweep individually. Systems that DO need to
    # reach them (workplace_reputation decay, career_ladder, contract
    # clauses) find them via world["companies"]/workplace_contact_ids,
    # never through this generic list.
    characters = [
        c for c in world.get("characters", {}).values()
        if not c.get("is_workplace_npc")
    ]

    # Confirmed live bug: schedule generation only ever runs for whoever is
    # already in world["characters"] at the one Monday-midnight tick per week
    # (see _is_monday_midnight's one-shot guard below) -- anyone added or
    # restored between two Mondays (a character brought back into the sim,
    # a new NPC, ...) got no schedule at all and stayed that way for up to a
    # full week: no work/sleep blocks, no schedule-derived expectation
    # windows, no "it's bedtime" wake regardless of how late it got. Self-
    # heals every tick instead of waiting for the next weekly reset.
    for c in characters:
        if "schedule" not in c:
            c["schedule"] = generate_week_schedule(c, world)
            adjust_for_household(c, world)

    # Weekly / hourly / daily / monthly work, popularity decay, post engagement and the
    # orphaned-prop sweep are no longer checked for here: the clock emits time.week/hour/day/
    # month and the scheduler fires the recurring jobs -- see systems/calendar_handlers.py.

    _prof.mark("section:fast_perception_attention")
    # -- Fast: perception + attention (÷5) ──────────────────


    _prof.mark("section:per_tick_movement")
    # -- Per-tick: movement (main thread, always, before any dispatch) ──
    # Confirmed live bug (player report: a character mid-walk to the
    # kitchen frozen in place for well over a minute, moving only in
    # occasional bursts): position interpolation (systems/movement.py,
    # pure CPU-bound math -- no LLM/network call involved at all) used to
    # only run from INSIDE brain/agent_loop.py's update_agent(), which
    # itself only runs when a character's turn comes up on the per-
    # character worker-thread pool below -- sharing the GIL with however
    # many OTHER characters are mid-LLM-call that same tick, and entirely
    # skipped for a tick where that character's own dispatch gets
    # abandoned past AGENT_WAIT_BUDGET_SECONDS (worse: once abandoned, a
    # character is excluded from being resubmitted AT ALL until their
    # original stuck thread finishes, up to STALE_PENDING_SECONDS later --
    # see agent_chars below). A character who was otherwise doing nothing
    # computationally expensive still had their walk stall for reasons
    # entirely unrelated to their own state. Applying it here instead --
    # unconditionally, for every is_moving character, before any per-
    # character dispatch even begins -- means movement can never be
    # delayed by another character's unrelated LLM latency or by the
    # dispatch/abandon bookkeeping below. agent_loop.py's update_agent()
    # no longer calls this itself (see its own matching comments) --
    # is_moving/position are already this tick's final values by the time
    # it runs.
    from systems.movement import update_character_movement
    dirty_char_ids = set()
    for c in characters:
        if c.get("is_moving"):
            try:
                update_character_movement(c, world)
                dirty_char_ids.add(c["id"])
            except Exception as exc:
                print(f"[sim_loop] movement error for {c.get('id')}: {exc}")

    _prof.mark("section:per_tick_conversation_floor")
    # -- Per-tick: conversation floor (who has the ball, notice/ignore timers) --
    try:
        from systems.conversation_floor import tick as _floor_tick
        _floor_tick(world)
    except Exception as exc:
        print(f"[sim_loop] conversation floor error: {exc}")

    _prof.mark("section:per_tick_agent_brain")
    # -- Per-tick: character updates (sequential; decisions are requested, not awaited) --
    # Service worker NPCs are driven by update_services, not LLM -- skip them.
    agent_chars = [
        c for c in characters
        if not c.get("is_service_worker")
        and not c.get("is_workplace_npc")
        and c.get("alive") is not False
        and c.get("posture") != "incapacitated"
    ]
    for c in agent_chars:
        try:
            _run_agent(c, world, t)
            dirty_char_ids.add(c["id"])
        except Exception as exc:
            import traceback as _tb
            print(f"[sim_loop] agent error for {c.get('id')}: {exc!r}\n{_tb.format_exc()[-600:]}")

    _mark_dirty(world, char_ids=dirty_char_ids)

    _prof.mark("section:medium_memory_beliefs_relationships")
    # -- Medium: memory / beliefs / relationships (÷15) ─────



    # Trust-gated influence resolution -- who each character is around the
    # most (perception.py's exposure_ticks) shapes whether they adopt that
    # person's beliefs/traits (trusted) or grow suspicious (distrusted).
    # See systems/influence.py.

    # Daily trust/respect/exposure/value-similarity weighted influence on
    # personal values (systems/schema_defaults.py's VALUE_CATEGORIES) --
    # deliberately a separate, once-a-day cadence from the exposure
    # resolver above, per the "impact over time... sum it all up maybe on
    # a daily basis" ask. See systems/influence.py::resolve_value_influence.
    _prof.mark("every:value_influence")
    if every(world, CADENCE["value_influence"], offset=13) and _is_new_calendar_day(world, "value_influence"):
        resolve_value_influence(world)

    _prof.mark("section:medium_household_systems")
    # -- Medium: household systems (÷10) ────────────────────


    # Psychosis (see systems/psychosis.py) -- a temporary state any
    # character can enter from stress/sleep-deprivation/intoxication;
    # schizophrenia raises the baseline rate rather than getting a
    # separate mechanic.

    # Sports: move attendees into their game-day mode once kickoff arrives,
    # and narrate periodic score updates for anyone currently watching
    # on-grid. Same fine-grained cadence as reading (a game window is much
    # longer than a news pick, but attendees shouldn't wait up to a full
    # day to actually leave for kickoff).

    # Household-scoped multi-stage processes (laundry, etc.) — ticks
    # forward for every household regardless of who's nearby, same
    # cadence tier as cooking. See systems/task_process.py.






    _prof.mark("section:medium_market")
    # -- Medium: market (÷20) ───────────────────────────────

    _prof.mark("section:slow_still_periodic_systems")
    # -- Slow: still-periodic systems (÷30-60) ──────────────

    # Job market — init slots once, refresh daily, process interviews each cycle
    if not world.get("company_slots"):
        init_company_slots(world)
    if not world.get("job_listings"):
        generate_job_listings(world)


    # Not every()-gated -- the 15-sim-minute bus schedule (see transit.py)
    # needs single-tick precision to catch the boundary reliably.
    update_bus(world)








    # World-level random incidents (character-level ones emitted in agent_loop)
    _prof.mark("every:arrests")
    if every(world, CADENCE["arrests"], offset=15):
        trigger_incident(world, None)  # world-level random only
        # Live bug report: auto_report_incidents() only ran reactively, off
        # the "incident_created" event -- a lone unreported incident (e.g.
        # a medical emergency with nobody else around to generate a fresh
        # incident elsewhere) could sit unreported indefinitely since
        # nothing ever re-rolled its 911-report chance. Confirmed live: a
        # medical_emergency incident stayed reported=False for tens of
        # thousands of ticks. Also polling it here on the same cadence
        # resolve() already uses gives every unreported incident a repeat
        # chance regardless of what else is happening in the world.
        auto_report_incidents(world)
        resolve(world)                 # poll responder arrival ticks
        maybe_arrest_from_incidents(world)
        # Incapacitated characters are deliberately excluded from
        # agent_chars above (same reason their LLM doesn't get called) --
        # but apply_severity_consequences() (posture recovery, and the
        # medical-emergency retry inside it) and offgrid.py::process_return()
        # (which is what actually cures a hospital patient -- clears
        # unconscious/bleeding/severe_trauma -- and brings anyone off_grid
        # back once their return_tick passes) only ever ran from INSIDE
        # that per-character agent tick. That's a deadlock for anyone sent
        # off_grid while incapacitated: they can never re-enter agent_chars
        # to get treated or come home, because getting treated/coming home
        # is the only thing that would ever clear "incapacitated" in the
        # first place. Confirmed live: two characters stayed off_grid,
        # unconscious, and stuck rendering at their pre-hospital position
        # on the map indefinitely. Sweeping every character here rescues
        # exactly those characters.
        #
        # Confirmed live bug (duplicate timeline events, e.g. the SAME
        # "had a routine cafe trip" appearing twice at the same tick): this
        # used to sweep EVERY alive character "unconditionally," not just
        # the incapacitated ones this block exists for. agent_chars (built
        # above, still in scope) already gets its own worker-thread
        # dispatch this same tick, and update_agent() calls these same two
        # functions itself, on the SAME shared `world`/`c` dict, from a
        # DIFFERENT thread -- a genuine TOCTOU race, not a stale-snapshot
        # one: both threads can read off_grid==True before either writes
        # it back False, so both run process_return()'s whole body
        # (including the world["events"].append) to completion. Restricting
        # this sweep to characters agent_chars actually excluded removes
        # the second caller entirely instead of trying to lock around it --
        # every character still gets covered exactly once, just by
        # whichever path was always the real one for them.
        #
        # "Excluded from agent_chars" is not enough on its own: a character
        # whose previous dispatch is still running (_pending_agent_ids) is
        # ALSO excluded from agent_chars, yet that thread is exactly who is
        # mid-process_return. process_return() can sit for a long time --
        # a returning worker blocks inside offgrid.py::_resolve_work_shift
        # on a work-shift narration LLM call (up to llm_gate's 90s) with
        # off_grid still True -- so sweeping pending characters re-ran the
        # whole return on THIS (the main tick) thread: a second narration
        # call, a duplicate world["events"] entry, and the entire tick
        # blocked for the length of the call. Confirmed via a faulthandler
        # dump: main thread in tick() -> process_return() ->
        # generate_hourly_work_beats() -> run_llm_call(), simultaneously
        # with an agent worker in the same chain for the same character.
        # Only characters with NO agent thread at all (incapacitated, never
        # dispatched) still need this sweep -- the deadlock it exists for.
        from systems.offgrid import process_return
        _has_agent_thread = {c["id"] for c in agent_chars}
        for c in characters:
            if c.get("alive") is not False and c["id"] not in _has_agent_thread:
                apply_severity_consequences(c, world)
                process_return(c, world)


    # Jail release still needs tick poll



    # Conversations threaded via action_router.py's apply_speech() aren't
    # tied to a scripted activity with its own end condition anymore, so
    # this is what retires them after a period of silence.


    # Weather + outdoor temperature exposure (systems/weather.py) --
    # world["weather"] was read by brain/perception.py's room-summary
    # narration but never actually set anywhere before this.

    # Social Projects (systems/social_projects.py) -- proposal expiry
    # (timeout defaults to declined, never auto-accepted) + SCHEDULED ->
    # ACTIVE transition once a project's planned_start_tick arrives.

    # Interrupt anyone currently "socializing" with a target who's since
    # fallen asleep or gone off-grid (systems/social.py) -- confirmed live
    # bug: a character could be left mid-conversation with someone asleep
    # for the rest of that activity's real duration.


    # Eviction / migration: emit events when thresholds crossed


    _prof.mark("section:conflict_social_drama")
    # -- Conflict / social drama ────────────────────────────────────────






    _prof.mark("section:daily_stats_drift")
    # -- Daily stats drift ──────────────────────────────────

    _prof.mark("section:police_rss_feed")
    # -- Police RSS feed (real-world-flavored news + crime/traffic stat
    # nudges, see systems/police_feed.py) -- try/except-wrapped the same
    # way the block above is; a network hiccup here must never take the
    # sim down. ─────────────────────────────────────────

    _prof.mark("section:clear_one_tick_departure_flags")
    # -- Clear one-tick departure flags (must be first) ────
    clear_departure_flags(world)

    _prof.mark("section:prune_expired_transient_ambient_sounds")
    # -- Prune expired transient ambient sounds (see brain/perception.py's
    # emit_ambient_sound/VOLUME_TIERS) ──────────────────────
    cleanup_ambient_sounds(world)

    _prof.mark("section:intimacy_arousal_decay")
    # -- Intimacy arousal decay (every tick) ───────────────
    tick_intimacy(world)

    _prof.mark("section:impulse_control_pressure_boilover")
    # -- Impulse control pressure + boilover (every tick) ───
    tick_impulse(world)
    tick_harassment(world)
    tick_baby_hourly(world)
    tick_nudity_perception(world)
    tick_crushes(world)
    tick_incidental_speech(world)

    _prof.mark("section:very_slow")
    # -- Very slow (÷300) ───────────────────────────────────




    _prof.mark("section:body_lt_needs_systems")
    # -- Body / lt_needs systems ────────────────────────────


    _prof.mark("section:disease_contagion_proximity_sweep_grouped_by")
    # -- Disease/contagion proximity sweep, grouped by building ────

    _prof.mark("section:child_needs_oversight_baseline_accountabilit")
    # -- Child needs oversight + baseline accountability contract ──

    _prof.mark("section:age_based_bedroom_ownership")
    # -- Age-based bedroom ownership ────────────────────────────────

    _prof.mark("section:plant_growth_moisture_weeds_character_reacti")
    # -- Plant growth/moisture/weeds + character reaction to neglect ──

    _prof.mark("section:food_freshness_decay")
    # -- Food freshness decay ─────────────────────────────────────────

    _prof.mark("section:mobile_data_consumption_entertainment_subscr")
    # -- Mobile data consumption + entertainment-subscription peer
    # desire (systems/telecom.py, systems/subscriptions.py) + the daily
    # home-presence rollover (systems/home_presence.py -- ONE owner of
    # the daily reset now that a second consumer, withdrawal_concern.py
    # below, also needs the rolling history) + depression's real
    # symptoms (systems/mental_health_effects.py) + noticing a
    # household member's sustained withdrawal (systems/
    # withdrawal_concern.py) ─────────────────────────────────────────
    _prof.mark("every:daily_finance")
    if every(world, CADENCE["daily_finance"], offset=45) and _is_new_calendar_day(world, "daily_finance"):
        from systems.telecom import tick_daily_data_usage
        from systems.subscriptions import maybe_grow_subscription_desire
        from systems.home_presence import roll_over_home_presence_day
        from systems.mental_health_effects import tick_depression_effects
        from systems.withdrawal_concern import maybe_notice_withdrawal
        from systems.absence_suspicion import maybe_notice_absence
        from systems.secret_keeping import maybe_generate_secret, tick_all_secrets
        from systems.confiding import resolve_confide_opportunities
        from systems.temporary_separation import maybe_return_from_separation
        from systems.crushes import maybe_form_crush
        from systems.detective_work import (
            maybe_send_unsettling_letter, check_personal_mail, maybe_report_missing_item,
            maybe_report_mysterious_appearance, maybe_notice_gambling_problem,
            tick_aggression_patterns,
        )
        tick_all_secrets(world)
        maybe_send_unsettling_letter(world)
        maybe_report_missing_item(world)
        maybe_report_mysterious_appearance(world)
        maybe_notice_gambling_problem(world)
        tick_aggression_patterns(world)
        for c in characters:
            if not c.get("alive", True):
                continue
            home_fraction = roll_over_home_presence_day(c)
            tick_daily_data_usage(c, world, home_fraction)
            tick_depression_effects(c, world)
            maybe_return_from_separation(c, world)
            check_personal_mail(c, world)
            if not c.get("off_grid"):
                maybe_grow_subscription_desire(c, world)
                maybe_notice_withdrawal(c, world)
                maybe_notice_absence(c, world)
                maybe_generate_secret(c, world)
                resolve_confide_opportunities(c, world)
                maybe_form_crush(c, world)

    _prof.mark("section:hourly_home_presence_sample")
    # -- Hourly home-presence sample (systems/home_presence.py) -- feeds
    # the mobile-data home-wifi discount above, and is general-purpose
    # for anything else that ever wants "how much of today has this
    # character spent home." ───────────────────────────────────────────

    _prof.mark("section:body_weight_fitness_trait_sync")
    # -- Body weight/fitness-trait sync ────────────────────────────────

    _prof.mark("section:autonomous_intercourse_scene_progression")
    # -- Autonomous intercourse-scene progression (systems/
    # intercourse_session.py) -- foreplay -> main -> afterglow -> reroll,
    # each session paced by its own next_action_tick, not this cadence's
    # interval itself. ─────────────────────────────────────────────────

    _prof.mark("section:detective_story_chapter_progression")
    # -- Detective-story chapter progression (systems/detective_work.py) --


    _prof.mark("section:claustrophobia_panic_sweep")
    # -- Claustrophobia/panic sweep (systems/claustrophobia.py) -- catches
    # ANY character stuck making no real position progress while trying to
    # get somewhere, not just a room-specific case; escalates panic, climbs
    # out a real window if one's found once panic's high enough. ─────────

    _prof.mark("section:battery_drain_charging")
    # -- Battery drain + charging (phone, laptop, ...) (÷5) ───────────

    _prof.mark("section:phone_carry_drop_forget_behavior")
    # -- Phone carry/drop/forget behavior ────────────────────────────

    _prof.mark("section:individual_wait_activities")
    # -- Individual wait activities (microwave, phone hold, ...) ────
    # c["character_wait"] is deliberately its own field, not folded into
    # c["activity"] — agent_loop.py returns early every tick whenever
    # c["activity"] is truthy (skips straight to execute_activity(), never
    # reaches the LLM decision call), so a character with something
    # sitting in c["activity"] can never be "free to do other things
    # meanwhile." The wait state has to live somewhere the LLM loop
    # doesn't treat as blocking.


    # Story arcs are lightweight — keep per-tick
    for c in characters:
        update_story_arc(c)

    # Process events queued this tick (emitted from worker threads during
    # agent updates and from the systems above) — must run last, main-thread
    # only, after every emit() site for this tick has had a chance to fire.
    if EVENT_BUS_ENABLED:
        flush_events(world)


# ── Scheduled jobs: the cadence-gated blocks that used to run inside tick() ──────────
# Each fires on its own recurring timer (core/scheduler.py) instead of being polled for
# by every tick; behaviour is otherwise the block's own code, unchanged.

from core import scheduler  # noqa: E402


def _job_perception(world, entry):
    """Scheduled job `perception` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        perceive(c, world)
        # "Authority hears a conflicting account via observation" —
        # see systems/excuses.py::check_visible_lies_for_observer.
        check_visible_lies_for_observer(c, world)
        # Same shape, for witnessing a punch/kick/shove/... — see
        # systems/excuses.py::check_witnessed_hostility_for_observer.
        check_witnessed_hostility_for_observer(c, world)


def _job_attention(world, entry):
    """Scheduled job `attention` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        update_attention(c, world)


def _job_memory_decay(world, entry):
    """Scheduled job `memory_decay` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        decay_memories(c)


def _job_polarization(world, entry):
    """Scheduled job `polarization` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        polarize_opinions(c)
        compute_political_lean(c)


def _job_relationships(world, entry):
    """Scheduled job `relationships` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    _update_nearby_relationships(characters, world)


def _job_influence_exposure(world, entry):
    """Scheduled job `influence_exposure` (was an every() block in tick()); see core/scheduler.py."""
    resolve_exposure_influence(world)


def _job_cooking(world, entry):
    """Scheduled job `cooking` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        hh = world.get("households", {}).get(c.get("household_id"))
        if hh:
            update_cooking_process(c, hh, world)


def _job_reading(world, entry):
    """Scheduled job `reading` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        update_reading_process(c, world)


def _job_health(world, entry):
    """Scheduled job `health` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        tick_psychosis(c, world)
        decay_stress(c, world)


def _job_reading_2(world, entry):
    """Scheduled job `reading#2` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    kickoff_scheduled_games(world)
    for c in characters:
        update_game_broadcast(c, world)


def _job_cooking_2(world, entry):
    """Scheduled job `cooking#2` (was an every() block in tick()); see core/scheduler.py."""
    update_household_processes(world)


def _job_deliveries(world, entry):
    """Scheduled job `deliveries` (was an every() block in tick()); see core/scheduler.py."""
    deliver_messages(world)
    update_deliveries(world)


def _job_service_workers(world, entry):
    """Scheduled job `service_workers` (was an every() block in tick()); see core/scheduler.py."""
    update_service_workers(world)


def _job_service_workers_2(world, entry):
    """Scheduled job `service_workers#2` (was an every() block in tick()); see core/scheduler.py."""
    update_convenience_store_staffing(world)


def _job_household_monitoring(world, entry):
    """Scheduled job `household_monitoring` (was an every() block in tick()); see core/scheduler.py."""
    update_household_monitoring(world)
    tick_caretaker_negotiation(world)
    tick_babysitting_requests(world)


def _job_mentality_compilation(world, entry):
    """Scheduled job `mentality_compilation` (was an every() block in tick()); see core/scheduler.py."""
    from systems.mentality import tick_mentality_compilation
    tick_mentality_compilation(world)


def _job_market(world, entry):
    """Scheduled job `market` (was an every() block in tick()); see core/scheduler.py."""
    update_market(world)
    update_stocks(world)
    produce(world)
    consume_households(world)


def _job_job_market(world, entry):
    """Scheduled job `job_market` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    tick_job_market(world)          # daily turnover + new listings
    for c in characters:
        maybe_fire(c, world)              # emits character_fired → apply_for_job
        advance_job_application(c, world) # polls job_application's stage_deadline_tick; emits character_hired
        advance_driver_license(c, world)       # same real multi-stage-pipeline shape as job_application
        maybe_practice_with_companion(c, world)


def _job_traffic(world, entry):
    """Scheduled job `traffic` (was an every() block in tick()); see core/scheduler.py."""
    update_ambient_traffic(world)


def _job_postal(world, entry):
    """Scheduled job `postal` (was an every() block in tick()); see core/scheduler.py."""
    update_postal_service(world)


def _job_postal_2(world, entry):
    """Scheduled job `postal#2` (was an every() block in tick()); see core/scheduler.py."""
    update_newspaper_delivery(world)


def _job_business_support(world, entry):
    """Scheduled job `business_support` (was an every() block in tick()); see core/scheduler.py."""
    process_business_inboxes(world)


def _job_appliance_degradation(world, entry):
    """Scheduled job `appliance_degradation` (was an every() block in tick()); see core/scheduler.py."""
    update_appliance_degradation(world)


def _job_service_workers_3(world, entry):
    """Scheduled job `service_workers#3` (was an every() block in tick()); see core/scheduler.py."""
    update_service_vehicles(world)


def _job_service_workers_4(world, entry):
    """Scheduled job `service_workers#4` (was an every() block in tick()); see core/scheduler.py."""
    update_rideshare_vehicles(world)


def _job_service_workers_5(world, entry):
    """Scheduled job `service_workers#5` (was an every() block in tick()); see core/scheduler.py."""
    update_services(world)


def _job_fires(world, entry):
    """Scheduled job `fires` (was an every() block in tick()); see core/scheduler.py."""
    tick_fire_incidents(world)


def _job_trials(world, entry):
    """Scheduled job `trials` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        process_jail(c, world)     # emits character_released
    process_trials(world)          # emits character_jailed / character_acquitted
    process_prison_reporting(world)  # mail-scheduled self-surrender + failure-to-appear
    from systems.offgrid import tick_long_stay_checkins
    tick_long_stay_checkins(world)  # periodic narration for long off-grid stays


def _job_news(world, entry):
    """Scheduled job `news` (was an every() block in tick()); see core/scheduler.py."""
    generate_news(world)
    maybe_generate_shared_event(world)


def _job_reading_3(world, entry):
    """Scheduled job `reading#3` (was an every() block in tick()); see core/scheduler.py."""
    from systems.scripted_conversations import tick_scripted_conversations
    tick_scripted_conversations(world)  # plays back a remote call/sms shared_event's script


def _job_conversation_cleanup(world, entry):
    """Scheduled job `conversation_cleanup` (was an every() block in tick()); see core/scheduler.py."""
    cleanup_conversations(world)


def _job_conversation_seating(world, entry):
    """Scheduled job `conversation_seating` (was an every() block in tick()); see core/scheduler.py."""
    from systems.conversation_seating import tick_conversation_seating
    tick_conversation_seating(world)


def _job_weather(world, entry):
    """Scheduled job `weather` (was an every() block in tick()); see core/scheduler.py."""
    from systems.weather import generate_weather_tick, apply_weather_to_characters
    generate_weather_tick(world)
    apply_weather_to_characters(world)


def _job_social_projects(world, entry):
    """Scheduled job `social_projects` (was an every() block in tick()); see core/scheduler.py."""
    from systems.social_projects import tick_social_projects
    tick_social_projects(world)
    # Confirmed real, pre-existing gap carried over from the retired
    # systems/social_events.py: check_hobby_sessions() (spawns/despawns
    # temporary NPC guests for an at-home hobby session) had zero
    # callers anywhere in this codebase, so it never actually ran.
    # Real, cheap fix while already touching this cadence block.
    from systems.hobbies import check_hobby_sessions
    check_hobby_sessions(world)


def _job_social_availability(world, entry):
    """Scheduled job `social_availability` (was an every() block in tick()); see core/scheduler.py."""
    interrupt_socializing_with_unavailable_targets(world)


def _job_job_market_2(world, entry):
    """Scheduled job `job_market#2` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        update_investment_behavior(c, world)


def _job_evictions(world, entry):
    """Scheduled job `evictions` (was an every() block in tick()); see core/scheduler.py."""
    for hh in world.get("households", {}).values():
        check_household_for_eviction(hh, world)  # emits bills_overdue


def _job_migration(world, entry):
    """Scheduled job `migration` (was an every() block in tick()); see core/scheduler.py."""
    check_migration_desires(world)               # emits household_wants_to_move


def _job_conflicts(world, entry):
    """Scheduled job `conflicts` (was an every() block in tick()); see core/scheduler.py."""
    process_conflicts(world)


def _job_grapples(world, entry):
    """Scheduled job `grapples` (was an every() block in tick()); see core/scheduler.py."""
    process_grapples(world)


def _job_grievances(world, entry):
    """Scheduled job `grievances` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    update_grievances(world)    # decay + emit confrontation_desired
    from systems.goodwill import update_goodwill
    update_goodwill(world)      # decay + stamp _bond_emitted, same cadence
    from systems.offense_rationalization import decay_guilt_paranoia
    for c in characters:
        if c.get("_guilt_paranoia"):
            decay_guilt_paranoia(c)


def _job_contract_checks(world, entry):
    """Scheduled job `contract_checks` (was an every() block in tick()); see core/scheduler.py."""
    check_contract_violations(world)  # emits contract_violated
    cleanup_expired_rule_exceptions(world)  # GC only, see social_rules.py
    decay_worries(world)  # passive suspicion decay, see worries.py


def _job_worry_poll(world, entry):
    """Scheduled job `worry_poll`: each character looks over what happened in the last hour and lets it
    refresh or start worries (systems/worry_cases.py)."""
    from systems.worry_cases import tick_worry_polls
    tick_worry_polls(world)


def _job_neighbours(world, entry):
    """Scheduled job `neighbours`: characters that haven't yet been given the ties of their street get them
    (systems/neighbours.py)."""
    from systems.neighbours import tick_seed_neighbours
    tick_seed_neighbours(world)


def _job_kids_play(world, entry):
    """Scheduled job `kids_play`: free children with a free friend nearby get the urge to play (systems/kids_play.py)."""
    from systems.kids_play import tick_kids_play
    tick_kids_play(world)


def _job_introductions(world, entry):
    """Scheduled job `introductions`: a friend in view of two strangers may introduce them (systems/introductions.py)."""
    from systems.introductions import tick_introductions
    tick_introductions(world)


def _job_rumors(world, entry):
    """Scheduled job `rumors`: someone who heard a remark about a third person and is now near them may tell them
    (systems/rumors.py)."""
    from systems.rumors import tick_rumors
    tick_rumors(world)


def _job_grudges(world, entry):
    """Scheduled job `grudges`: open grudges fade, jab, escalate and nudge the offender to apologise (systems/grudges.py)."""
    from systems.grudges import tick_grudges
    tick_grudges(world)


def _job_focus_check(world, entry):
    """Scheduled job `focus_check`: worried characters' mitigation intentions and the 3-minute concentration
    roll (systems/worry_relief.py)."""
    from systems.worry_relief import tick_focus_checks
    tick_focus_checks(world)


def _job_persona_expectations(world, entry):
    """Scheduled job `persona_expectations` (was an every() block in tick()); see core/scheduler.py."""
    tick_persona_expectations(world)  # value-alignment clashes between close kin


def _job_cleanliness(world, entry):
    """Scheduled job `cleanliness` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    from systems.chores import tick_room_cleanliness_decay, maybe_react_to_mess
    from systems.refurnishing import maybe_want_to_redecorate
    from systems.clothing import tick_clothing_dirty
    tick_room_cleanliness_decay(world)
    for c in characters:
        if c.get("alive", True) and not c.get("off_grid"):
            maybe_react_to_mess(c, world)
            maybe_want_to_redecorate(c, world)
            tick_clothing_dirty(c, world)


def _job_socioeconomics(world, entry):
    """Scheduled job `socioeconomics` (was an every() block in tick()); see core/scheduler.py."""
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


def _job_police_feed(world, entry):
    """Scheduled job `police_feed` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    try:
        from core.definitions import load_definitions as _load_defs_pf
        from systems.police_feed import tick_police_feed
        tick_police_feed(world, _load_defs_pf(world.get("sim_id", "default")))
    except Exception:
        pass
    tick_quid_pro_quo(world)
    tick_emotional_control(world)
    tick_religious_repression(world)
    tick_harassment_daily(world)
    tick_libido(world)
    tick_discovery_checks(world)
    tick_life_comparison(world)
    tick_sports_leagues(world)
    schedule_game_day_events(world)
    apply_game_day_outcomes(world)
    tick_criminal_career_progression(world)
    tick_gang_wars(world)
    generate_darknet_listings(world)
    tick_pi_assignments(world)
    tick_corruption_risk(world)
    for c in characters:
        maybe_offer_corruption(c, world)
    for c in characters:
        decay_stories(c)
        decay_workplace_views(c)
        aggregate_daily_observations(c, world)
        maybe_recruit_into_crime(c, world)
        maybe_write_diary(c, world)
        if is_sociopath(c):
            contacts = [world["characters"][oid] for oid in c.get("relationships", {})
                        if oid in world["characters"]]
            if contacts:
                maybe_introduce_false_identity(c, random.choice(contacts), world)
            maybe_discover_persona_mismatch(c, world)
            maybe_plant_drama(c, world)
    tick_baby_daily(world)
    for _c in characters:
        sync_anger_from_grievances(_c, world)
        check_victim_revenge(_c, world)
        # Annual trait/belief-learning budget refresh -- see
        # systems/trait_budget.py. Checked at this existing daily-ish
        # cadence rather than a dedicated one; guarded internally
        # against re-firing on the same birthday.
        bd = _c.get("birthday")
        cal = world.get("calendar", {})
        if bd and bd.get("month") == cal.get("month") and bd.get("day") == cal.get("day"):
            recompute_budget_on_birthday(_c, world)


def _job_crisis(world, entry):
    """Scheduled job `crisis` (was an every() block in tick()); see core/scheduler.py."""
    check_crises(world)
    process_crises(world)


def _job_election(world, entry):
    """Scheduled job `election` (was an every() block in tick()); see core/scheduler.py."""
    check_election(world)
    process_pending_effects(world)
    resolve_legislation_votes(world)


def _job_faction(world, entry):
    """Scheduled job `faction` (was an every() block in tick()); see core/scheduler.py."""
    apply_faction_influence(world)
    apply_public_figure_influence(world)
    apply_social_influence(world)
    process_rival_tensions(world)


def _job_hierarchy(world, entry):
    """Scheduled job `hierarchy` (was an every() block in tick()); see core/scheduler.py."""
    update_hierarchy(world)


def _job_lt_needs(world, entry):
    """Scheduled job `lt_needs` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        update_lt_needs(c, world)
        # generate_socialize_intention (systems/social.py) was fully
        # built -- real target selection off relationship strength --
        # but had no caller anywhere; generate_lt_need_intentions covers
        # the other 11 lt_needs categories, none of which previously
        # ever produced a real active_intentions entry either.
        generate_socialize_intention(c, world)
        generate_lt_need_intentions(c, world)


def _job_social_odor(world, entry):
    """Scheduled job `social_odor` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        apply_odor_social_pressure(c, world)


def _job_contagion(world, entry):
    """Scheduled job `contagion` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    groups = {}
    for c in characters:
        c["location_tile"] = f"{int(c.get('x', 0))},{int(c.get('y', 0))}"
        groups.setdefault(c.get("building_id"), []).append(c)
    for group in groups.values():
        if len(group) > 1:
            tick_contagion_location(group, world)


def _job_child_care(world, entry):
    """Scheduled job `child_care` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    tick_child_needs(world)
    tick_child_welfare(world)
    tick_child_disclosure(world)
    for c in characters:
        if c.get("dependents"):
            tick_dependent_checks(c, world)


def _job_bedroom_assignment(world, entry):
    """Scheduled job `bedroom_assignment` (was an every() block in tick()); see core/scheduler.py."""
    tick_bedroom_assignments(world)


def _job_plants(world, entry):
    """Scheduled job `plants` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    tick_plants(world)
    from systems.chores import maybe_tend_plants
    for c in characters:
        if c.get("alive", True) and not c.get("off_grid"):
            maybe_tend_plants(c, world)


def _job_food_aging(world, entry):
    """Scheduled job `food_aging` (was an every() block in tick()); see core/scheduler.py."""
    age_food_items(world)


def _job_home_presence(world, entry):
    """Scheduled job `home_presence` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    from systems.home_presence import tick_home_presence_sample
    for c in characters:
        if c.get("alive", True) and not c.get("off_grid"):
            tick_home_presence_sample(c, world)


def _job_body_composition(world, entry):
    """Scheduled job `body_composition` (was an every() block in tick()); see core/scheduler.py."""
    tick_body_composition(world)


def _job_intercourse_sessions(world, entry):
    """Scheduled job `intercourse_sessions` (was an every() block in tick()); see core/scheduler.py."""
    if world.get("intercourse_sessions"):
        from systems.intercourse_session import tick_intercourse_sessions
        tick_intercourse_sessions(world)


def _job_detective_work(world, entry):
    """Scheduled job `detective_work` (was an every() block in tick()); see core/scheduler.py."""
    from systems.detective_work import tick_detective_work
    tick_detective_work(world)


def _job_addictions(world, entry):
    """Scheduled job `addictions` (was an every() block in tick()); see core/scheduler.py."""
    from systems.addictions import tick_addictions
    tick_addictions(world)


def _job_claustrophobia(world, entry):
    """Scheduled job `claustrophobia` (was an every() block in tick()); see core/scheduler.py."""
    from systems.claustrophobia import tick_claustrophobia
    tick_claustrophobia(world)


def _job_phone_battery(world, entry):
    """Scheduled job `phone_battery` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        act = c.get("activity") or {}
        if act.get("interaction") == "charge":
            charge_device(c, world)
        else:
            update_phone_battery(c)


def _job_phone_behavior(world, entry):
    """Scheduled job `phone_behavior` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        maybe_set_phone_down(c, world)
        last_building = c.get("_last_building_id")
        current_building = c.get("building_id")
        if last_building is not None and current_building != last_building:
            maybe_forget_phone(c, world, last_building)
        c["_last_building_id"] = current_building


def _job_character_wait(world, entry):
    """Scheduled job `character_wait` (was an every() block in tick()); see core/scheduler.py."""
    characters = [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]
    for c in characters:
        wait = c.get("character_wait")
        if wait and not wait.get("ready") and world["tick"] >= wait.get("ready_at_tick", 0):
            wait["ready"] = True
            from brain.cognition_scheduler import wake_character
            wake_character(c, world, "wait_ready")


def _job_calendar_events(world, entry):
    """Scheduled job `calendar_events` (was an every() block in tick()); see core/scheduler.py."""
    check_calendar_reminders(world)
    check_reminders(world)
    tick_contract_clauses(world)
    tick_pending_payouts(world)
    tick_insurance_renewals(world)


scheduler.register_recurring("perception", _job_perception, every=CADENCE["perception"], offset=(-0) % CADENCE["perception"])
scheduler.register_recurring("attention", _job_attention, every=CADENCE["attention"], offset=(-1) % CADENCE["attention"])
scheduler.register_recurring("memory_decay", _job_memory_decay, every=CADENCE["memory_decay"], offset=(-2) % CADENCE["memory_decay"])
scheduler.register_recurring("polarization", _job_polarization, every=CADENCE["polarization"], offset=(-3) % CADENCE["polarization"])
scheduler.register_recurring("relationships", _job_relationships, every=CADENCE["relationships"], offset=(-4) % CADENCE["relationships"])
scheduler.register_recurring("worry_poll", _job_worry_poll, every=CADENCE["worry_poll"], offset=(-6) % CADENCE["worry_poll"])
scheduler.register_recurring("focus_check", _job_focus_check, every=CADENCE["focus_check"], offset=(-7) % CADENCE["focus_check"])
scheduler.register_recurring("grudges", _job_grudges, every=CADENCE["grudges"], offset=(-8) % CADENCE["grudges"])
scheduler.register_recurring("rumors", _job_rumors, every=CADENCE["rumors"], offset=(-9) % CADENCE["rumors"])
scheduler.register_recurring("neighbours", _job_neighbours, every=CADENCE["neighbours"], offset=(-10) % CADENCE["neighbours"])
scheduler.register_recurring("kids_play", _job_kids_play, every=CADENCE["kids_play"], offset=(-11) % CADENCE["kids_play"])
scheduler.register_recurring("introductions", _job_introductions, every=CADENCE["introductions"], offset=(-12) % CADENCE["introductions"])
scheduler.register_recurring("influence_exposure", _job_influence_exposure, every=CADENCE["influence_exposure"], offset=(-21) % CADENCE["influence_exposure"])
scheduler.register_recurring("cooking", _job_cooking, every=CADENCE["cooking"], offset=(-5) % CADENCE["cooking"])
scheduler.register_recurring("reading", _job_reading, every=CADENCE["reading"], offset=(-9) % CADENCE["reading"])
scheduler.register_recurring("health", _job_health, every=CADENCE["health"], offset=(-19) % CADENCE["health"])
scheduler.register_recurring("reading#2", _job_reading_2, every=CADENCE["reading"], offset=(-17) % CADENCE["reading"])
scheduler.register_recurring("cooking#2", _job_cooking_2, every=CADENCE["cooking"], offset=(-33) % CADENCE["cooking"])
scheduler.register_recurring("deliveries", _job_deliveries, every=CADENCE["deliveries"], offset=(-6) % CADENCE["deliveries"])
scheduler.register_recurring("service_workers", _job_service_workers, every=CADENCE["service_workers"], offset=(-7) % CADENCE["service_workers"])
scheduler.register_recurring("service_workers#2", _job_service_workers_2, every=CADENCE["service_workers"], offset=(-17) % CADENCE["service_workers"])
scheduler.register_recurring("household_monitoring", _job_household_monitoring, every=CADENCE["household_monitoring"], offset=(-8) % CADENCE["household_monitoring"])
scheduler.register_recurring("mentality_compilation", _job_mentality_compilation, every=CADENCE["mentality_compilation"], offset=(-12) % CADENCE["mentality_compilation"])
scheduler.register_recurring("market", _job_market, every=CADENCE["market"], offset=(-9) % CADENCE["market"])
scheduler.register_recurring("job_market", _job_job_market, every=CADENCE["job_market"], offset=(-10) % CADENCE["job_market"])
scheduler.register_recurring("traffic", _job_traffic, every=CADENCE["traffic"], offset=(-11) % CADENCE["traffic"])
scheduler.register_recurring("postal", _job_postal, every=CADENCE["postal"], offset=(-12) % CADENCE["postal"])
scheduler.register_recurring("postal#2", _job_postal_2, every=CADENCE["postal"], offset=(-34) % CADENCE["postal"])
scheduler.register_recurring("business_support", _job_business_support, every=CADENCE["business_support"], offset=(-14) % CADENCE["business_support"])
scheduler.register_recurring("appliance_degradation", _job_appliance_degradation, every=CADENCE["appliance_degradation"], offset=(-13) % CADENCE["appliance_degradation"])
scheduler.register_recurring("service_workers#3", _job_service_workers_3, every=CADENCE["service_workers"], offset=(-14) % CADENCE["service_workers"])
scheduler.register_recurring("service_workers#4", _job_service_workers_4, every=CADENCE["service_workers"], offset=(-48) % CADENCE["service_workers"])
scheduler.register_recurring("service_workers#5", _job_service_workers_5, every=CADENCE["service_workers"], offset=(-18) % CADENCE["service_workers"])
scheduler.register_recurring("fires", _job_fires, every=CADENCE["fires"], offset=(-16) % CADENCE["fires"])
scheduler.register_recurring("trials", _job_trials, every=CADENCE["trials"], offset=(-16) % CADENCE["trials"])
scheduler.register_recurring("news", _job_news, every=CADENCE["news"], offset=(-17) % CADENCE["news"])
scheduler.register_recurring("reading#3", _job_reading_3, every=CADENCE["reading"], offset=(-23) % CADENCE["reading"])
scheduler.register_recurring("conversation_cleanup", _job_conversation_cleanup, every=CADENCE["conversation_cleanup"], offset=(-19) % CADENCE["conversation_cleanup"])
scheduler.register_recurring("conversation_seating", _job_conversation_seating, every=CADENCE["conversation_seating"], offset=(-21) % CADENCE["conversation_seating"])
scheduler.register_recurring("weather", _job_weather, every=CADENCE["weather"], offset=(-44) % CADENCE["weather"])
scheduler.register_recurring("social_projects", _job_social_projects, every=CADENCE["social_projects"], offset=(-48) % CADENCE["social_projects"])
scheduler.register_recurring("social_availability", _job_social_availability, every=CADENCE["social_availability"], offset=(-52) % CADENCE["social_availability"])
scheduler.register_recurring("job_market#2", _job_job_market_2, every=CADENCE["job_market"], offset=(-20) % CADENCE["job_market"])
scheduler.register_recurring("evictions", _job_evictions, every=CADENCE["evictions"], offset=(-18) % CADENCE["evictions"])
scheduler.register_recurring("migration", _job_migration, every=CADENCE["migration"], offset=(-19) % CADENCE["migration"])
scheduler.register_recurring("conflicts", _job_conflicts, every=CADENCE["conflicts"], offset=(-24) % CADENCE["conflicts"])
scheduler.register_recurring("grapples", _job_grapples, every=CADENCE["grapples"], offset=(-35) % CADENCE["grapples"])
scheduler.register_recurring("grievances", _job_grievances, every=CADENCE["grievances"], offset=(-25) % CADENCE["grievances"])
scheduler.register_recurring("contract_checks", _job_contract_checks, every=CADENCE["contract_checks"], offset=(-26) % CADENCE["contract_checks"])
scheduler.register_recurring("persona_expectations", _job_persona_expectations, every=CADENCE["persona_expectations"], offset=(-42) % CADENCE["persona_expectations"])
scheduler.register_recurring("cleanliness", _job_cleanliness, every=CADENCE["cleanliness"], offset=(-43) % CADENCE["cleanliness"])
scheduler.register_recurring("socioeconomics", _job_socioeconomics, every=CADENCE["socioeconomics"], offset=(-19) % CADENCE["socioeconomics"])
scheduler.register_recurring("police_feed", _job_police_feed, every=CADENCE["police_feed"], offset=(-21) % CADENCE["police_feed"])
scheduler.register_recurring("crisis", _job_crisis, every=CADENCE["crisis"], offset=(-20) % CADENCE["crisis"])
scheduler.register_recurring("election", _job_election, every=CADENCE["election"], offset=(-21) % CADENCE["election"])
scheduler.register_recurring("faction", _job_faction, every=CADENCE["faction"], offset=(-22) % CADENCE["faction"])
scheduler.register_recurring("hierarchy", _job_hierarchy, every=CADENCE["hierarchy"], offset=(-23) % CADENCE["hierarchy"])
scheduler.register_recurring("lt_needs", _job_lt_needs, every=CADENCE["lt_needs"], offset=(-27) % CADENCE["lt_needs"])
scheduler.register_recurring("social_odor", _job_social_odor, every=CADENCE["social_odor"], offset=(-28) % CADENCE["social_odor"])
scheduler.register_recurring("contagion", _job_contagion, every=CADENCE["contagion"], offset=(-36) % CADENCE["contagion"])
scheduler.register_recurring("child_care", _job_child_care, every=CADENCE["child_care"], offset=(-37) % CADENCE["child_care"])
scheduler.register_recurring("bedroom_assignment", _job_bedroom_assignment, every=CADENCE["bedroom_assignment"], offset=(-38) % CADENCE["bedroom_assignment"])
scheduler.register_recurring("plants", _job_plants, every=CADENCE["plants"], offset=(-39) % CADENCE["plants"])
scheduler.register_recurring("food_aging", _job_food_aging, every=CADENCE["food_aging"], offset=(-40) % CADENCE["food_aging"])
scheduler.register_recurring("home_presence", _job_home_presence, every=CADENCE["home_presence"], offset=(-46) % CADENCE["home_presence"])
scheduler.register_recurring("body_composition", _job_body_composition, every=CADENCE["body_composition"], offset=(-41) % CADENCE["body_composition"])
scheduler.register_recurring("intercourse_sessions", _job_intercourse_sessions, every=CADENCE["intercourse_sessions"], offset=(-48) % CADENCE["intercourse_sessions"])
scheduler.register_recurring("detective_work", _job_detective_work, every=CADENCE["detective_work"], offset=(-49) % CADENCE["detective_work"])
scheduler.register_recurring("addictions", _job_addictions, every=CADENCE["addictions"], offset=(-47) % CADENCE["addictions"])
scheduler.register_recurring("claustrophobia", _job_claustrophobia, every=CADENCE["claustrophobia"], offset=(-50) % CADENCE["claustrophobia"])
scheduler.register_recurring("phone_battery", _job_phone_battery, every=CADENCE["phone_battery"], offset=(-29) % CADENCE["phone_battery"])
scheduler.register_recurring("phone_behavior", _job_phone_behavior, every=CADENCE["phone_behavior"], offset=(-30) % CADENCE["phone_behavior"])
scheduler.register_recurring("character_wait", _job_character_wait, every=CADENCE["character_wait"], offset=(-34) % CADENCE["character_wait"])
scheduler.register_recurring("calendar_events", _job_calendar_events, every=CADENCE["calendar_events"], offset=(-32) % CADENCE["calendar_events"])
