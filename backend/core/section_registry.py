"""
core/section_registry.py

Every section of `sim_loop.tick()` (the labels given to core/tick_profile.mark()),
classified for the move to an event-driven architecture
(docs/distributed_architecture_plan.md, sec. 4 and 6):

  kind     continuous | threshold | timer | calendar | event | housekeeping
  owner    the component group that should own it afterwards
  becomes  what replaces the poll

  continuous    keeps its own loop, only while something is active
  threshold     lazy value + a timer set for the moment the threshold is crossed
  timer         scheduled at the moment the thing is decided (duration, deadline, due date)
  calendar      driven by a sim-clock boundary event (hour / day / week / month)
  event         driven by an event that already exists, or should
  housekeeping  maintenance that disappears with the architecture (flags cleared per tick, ...)

`tests/` (and tools) check that every mark in sim_loop.py has an entry, so a new section can't
be added without deciding how it will be triggered.
"""

# label -> (kind, owner, becomes)
REGISTRY = {
    "tick_head": ("housekeeping", "clock", "schedule self-heal -> on character creation"),
    "clock_and_scheduler": ("housekeeping", "clock", "the clock emits boundary events, the scheduler fires due timers (core/clock.py, core/scheduler.py)"),

    # ---- scheduled jobs registered in systems/calendar_handlers.py ----
    "every:popularity_decay": ("threshold", "social", "lazy decay; no per-minute work"),
    "every:post_engagement": ("calendar", "social", "time.hour"),
    "every:orphan_props": ("housekeeping", "world", "fixed at the source: release on interrupt (already done)"),
    "every:background_services": ("timer", "character", "each background job schedules its own collection wake"),

    # ---- calendar boundaries ----

    # ---- housekeeping ----
    "section:clear_one_tick_departure_flags": ("housekeeping", "character", "flag cleared by the handler that consumes it"),
    "section:prune_expired_transient_ambient_sounds": ("timer", "perception", "expiry timer per sound"),

    # ---- perception / attention ----
    "section:fast_perception_attention": ("event", "perception", "spatial index updated on movement events"),
    "every:perception": ("event", "perception", "entered_view / audible events on position change"),
    "every:attention": ("event", "character", "derived from perception events"),

    # ---- movement and agents ----
    "section:per_tick_movement": ("continuous", "movement", "own loop, only while an entity has a route"),
    "section:per_tick_conversation_floor": ("timer", "social", "floor timers scheduled when a line is spoken"),
    "section:per_tick_agent_brain": ("event", "character", "per-character actor: wakes on events/timers, async LLM"),

    # ---- memory / relationships ----
    "section:medium_memory_beliefs_relationships": ("housekeeping", "character", "grouping header"),
    "every:memory_decay": ("threshold", "character", "lazy salience; decay computed on read"),
    "every:polarization": ("event", "character", "on opinion/belief change"),
    "every:relationships": ("event", "social", "on proximity/interaction events"),
    "every:focus_check": ("timer", "character", "the 3-minute concentration roll becomes a timer set when a demanding activity starts (systems/worry_relief.py)"),
    "every:worry_poll": ("calendar", "character", "time.hour per character (staggered); new memories/news are the input (systems/worry_cases.py)"),
    "every:influence_exposure": ("calendar", "social", "time.hour"),
    "every:value_influence": ("calendar", "social", "time.day"),
    "every:persona_expectations": ("timer", "character", "expectation window start/end timers"),

    # ---- household ----
    "section:medium_household_systems": ("housekeeping", "household", "grouping header"),
    "every:cooking": ("timer", "household", "cook-step completion timers"),
    "every:reading": ("timer", "character", "reading-process timers"),
    "every:health": ("threshold", "body", "lazy needs + threshold timers"),
    "every:deliveries": ("timer", "world", "delivery due timers"),
    "every:service_workers": ("timer", "world", "service shift timers"),
    "every:household_monitoring": ("event", "household", "on household state change"),
    "every:mentality_compilation": ("event", "character", "on character created / belief change (background job)"),
    "every:daily_finance": ("calendar", "household", "time.day"),
    "every:home_presence": ("event", "household", "arrived/departed events"),
    "every:calendar_events": ("timer", "world", "event start timers"),
    "every:character_wait": ("timer", "character", "wait-until timers"),

    # ---- market / economy / world services ----
    "section:medium_market": ("housekeeping", "economy", "grouping header"),
    "every:market": ("calendar", "economy", "time.hour"),
    "section:slow_still_periodic_systems": ("housekeeping", "world", "grouping header"),
    "every:job_market": ("calendar", "economy", "time.day"),
    "every:traffic": ("continuous", "world", "own loop only while vehicles move"),
    "every:postal": ("timer", "world", "mail due timers"),
    "every:business_support": ("timer", "world", "callback due timers"),
    "every:appliance_degradation": ("threshold", "household", "lazy wear + failure timer"),
    "every:arrests": ("timer", "world", "event-driven from incidents"),
    "every:fires": ("event", "world", "spread/extinguish timers from the fire event"),
    "every:trials": ("timer", "world", "hearing date timers"),
    "every:news": ("calendar", "world", "time.hour"),
    "every:weather": ("calendar", "world", "time.hour"),
    "every:evictions": ("timer", "household", "notice expiry timers"),
    "every:migration": ("calendar", "world", "time.day"),
    "every:social_projects": ("timer", "social", "proposal expiry + start timers"),
    "every:social_availability": ("event", "social", "on sleep/off-grid change of a target"),
    "every:conversation_cleanup": ("timer", "social", "conversation idle timer"),
    "every:conversation_seating": ("event", "social", "on conversation start"),
    "every:socioeconomics": ("calendar", "economy", "time.day"),
    "section:police_rss_feed": ("calendar", "world", "time.hour, in the background (network)"),
    "every:police_feed": ("calendar", "world", "time.hour, in the background (network)"),
    "every:crisis": ("event", "world", "stat threshold events"),
    "every:election": ("calendar", "world", "time.week / election date timer"),
    "every:faction": ("calendar", "world", "time.week"),
    "every:hierarchy": ("calendar", "world", "time.week"),
    "section:very_slow": ("housekeeping", "world", "grouping header"),

    # ---- conflict / drama ----
    "section:conflict_social_drama": ("housekeeping", "social", "grouping header"),
    "every:conflicts": ("event", "social", "driven by hostile/speech events + stage timers"),
    "every:grapples": ("timer", "social", "grapple escape timers"),
    "every:grievances": ("event", "social", "on grievance added / expiry timer"),
    "every:contract_checks": ("timer", "social", "contract term due timers"),
    "section:daily_stats_drift": ("calendar", "world", "time.day"),

    # ---- body / needs ----
    "section:intimacy_arousal_decay": ("threshold", "body", "lazy decay"),
    "section:impulse_control_pressure_boilover": ("threshold", "body", "lazy pressure + boilover timer"),
    "section:body_lt_needs_systems": ("threshold", "body", "lazy needs"),
    "every:lt_needs": ("threshold", "body", "lazy long-term needs + frustration timer"),
    "every:social_odor": ("event", "perception", "recomputed on position/hygiene change"),
    "section:disease_contagion_proximity_sweep_grouped_by": ("event", "body", "on proximity change"),
    "every:contagion": ("event", "body", "on proximity change"),
    "section:child_needs_oversight_baseline_accountabilit": ("event", "social", "on child need threshold"),
    "every:child_care": ("event", "social", "on child need threshold"),
    "section:age_based_bedroom_ownership": ("event", "household", "on birthday / household change"),
    "every:bedroom_assignment": ("event", "household", "on birthday / household change"),
    "section:plant_growth_moisture_weeds_character_reacti": ("threshold", "world", "lazy growth + needs-water timer"),
    "every:plants": ("threshold", "world", "lazy growth + needs-water timer"),
    "section:food_freshness_decay": ("threshold", "world", "lazy freshness + spoil timer"),
    "every:food_aging": ("threshold", "world", "lazy freshness + spoil timer"),
    "section:mobile_data_consumption_entertainment_subscr": ("calendar", "economy", "time.day"),
    "section:hourly_home_presence_sample": ("calendar", "household", "time.hour"),
    "section:body_weight_fitness_trait_sync": ("calendar", "body", "time.day"),
    "every:body_composition": ("calendar", "body", "time.day"),
    "every:cleanliness": ("threshold", "household", "lazy decay + threshold timer"),
    "section:autonomous_intercourse_scene_progression": ("timer", "social", "scene step timers"),
    "every:intercourse_sessions": ("timer", "social", "scene step timers"),
    "section:detective_story_chapter_progression": ("timer", "character", "chapter timers"),
    "every:detective_work": ("timer", "character", "chapter timers"),
    "every:addictions": ("threshold", "body", "lazy craving + threshold timer"),
    "section:claustrophobia_panic_sweep": ("event", "body", "on enclosed-space change"),
    "every:claustrophobia": ("event", "body", "on enclosed-space change"),
    "section:battery_drain_charging": ("threshold", "world", "lazy battery + empty timer"),
    "every:phone_battery": ("threshold", "world", "lazy battery + empty timer"),
    "section:phone_carry_drop_forget_behavior": ("event", "character", "on departure / activity change"),
    "every:phone_behavior": ("event", "character", "on departure / activity change"),
    "section:individual_wait_activities": ("timer", "character", "wait-until timers"),
}


def base_label(label):
    """'every:reading#3' -> 'every:reading'."""
    return label.split("#", 1)[0]


def classify(label):
    base = base_label(label)      # strips a "#2" suffix, so every:reading#2 -> every:reading
    if base.split(":", 1)[0] in ("agent", "internal", "economy", "offgrid"):
        return ("agent_step", "character", "per-character steps of update_agent(): to be made lazy / timer-driven")
    if base.startswith("timer:"):
        owner = base.split(":", 1)[1]
        # a recurring job that used to be an every() block in tick(): its classification is
        # kept under the old "every:<cadence key>" label
        return REGISTRY.get("every:" + owner) or ("timer", owner, "a scheduled handler (core/scheduler.py)")
    return REGISTRY.get(base)


def summary():
    """kind -> count, owner -> count over the registry (for the migration dashboard)."""
    kinds, owners = {}, {}
    for kind, owner, _becomes in REGISTRY.values():
        kinds[kind] = kinds.get(kind, 0) + 1
        owners[owner] = owners.get(owner, 0) + 1
    return {"sections": len(REGISTRY), "by_kind": kinds, "by_owner": owners}
