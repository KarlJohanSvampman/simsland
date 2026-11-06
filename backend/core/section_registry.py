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

    # ---- calendar boundaries ----

    # ---- housekeeping ----
    "section:clear_one_tick_departure_flags": ("housekeeping", "character", "flag cleared by the handler that consumes it"),
    "section:prune_expired_transient_ambient_sounds": ("timer", "perception", "expiry timer per sound"),

    # ---- perception / attention ----
    "section:fast_perception_attention": ("event", "perception", "spatial index updated on movement events"),

    # ---- movement and agents ----
    "section:per_tick_movement": ("continuous", "movement", "own loop, only while an entity has a route"),
    "section:per_tick_conversation_floor": ("timer", "social", "floor timers scheduled when a line is spoken"),
    "section:per_tick_agent_brain": ("event", "character", "per-character actor: wakes on events/timers, async LLM"),

    # ---- memory / relationships ----
    "section:medium_memory_beliefs_relationships": ("housekeeping", "character", "grouping header"),

    # ---- household ----
    "section:medium_household_systems": ("housekeeping", "household", "grouping header"),

    # ---- market / economy / world services ----
    "section:medium_market": ("housekeeping", "economy", "grouping header"),
    "section:slow_still_periodic_systems": ("housekeeping", "world", "grouping header"),
    "section:police_rss_feed": ("calendar", "world", "time.hour, in the background (network)"),
    "section:very_slow": ("housekeeping", "world", "grouping header"),

    # ---- conflict / drama ----
    "section:conflict_social_drama": ("housekeeping", "social", "grouping header"),
    "section:daily_stats_drift": ("calendar", "world", "time.day"),

    # ---- body / needs ----
    "section:intimacy_arousal_decay": ("threshold", "body", "lazy decay"),
    "section:impulse_control_pressure_boilover": ("threshold", "body", "lazy pressure + boilover timer"),
    "section:body_lt_needs_systems": ("threshold", "body", "lazy needs"),
    "section:disease_contagion_proximity_sweep_grouped_by": ("event", "body", "on proximity change"),
    "section:child_needs_oversight_baseline_accountabilit": ("event", "social", "on child need threshold"),
    "section:age_based_bedroom_ownership": ("event", "household", "on birthday / household change"),
    "section:plant_growth_moisture_weeds_character_reacti": ("threshold", "world", "lazy growth + needs-water timer"),
    "section:food_freshness_decay": ("threshold", "world", "lazy freshness + spoil timer"),
    "section:mobile_data_consumption_entertainment_subscr": ("calendar", "economy", "time.day"),
    "section:hourly_home_presence_sample": ("calendar", "household", "time.hour"),
    "section:body_weight_fitness_trait_sync": ("calendar", "body", "time.day"),
    "section:autonomous_intercourse_scene_progression": ("timer", "social", "scene step timers"),
    "section:detective_story_chapter_progression": ("timer", "character", "chapter timers"),
    "section:claustrophobia_panic_sweep": ("event", "body", "on enclosed-space change"),
    "section:battery_drain_charging": ("threshold", "world", "lazy battery + empty timer"),
    "section:phone_carry_drop_forget_behavior": ("event", "character", "on departure / activity change"),
    "section:individual_wait_activities": ("timer", "character", "wait-until timers"),
}



# Every background job's entry comes from the job table itself (core/flow.py: what sets it off), so the two can't
# disagree -- a job added to the table is classified by being added.
def _from_flow():
    from core import flow
    kinds = {"event": "event", "clock": "calendar", "process": "continuous"}
    out = {}
    for job in flow.JOBS:
        if job["kind"] == "event":
            becomes = "on " + ", ".join(job["on"])
        elif job["kind"] == "clock":
            becomes = (f"daily at {job['daily'] // 3600:02d}:{job['daily'] % 3600 // 60:02d}" if job.get("daily") is not None
                       else f"hourly at :{(job.get('hourly') or 0) // 60:02d}")
        else:
            becomes = f"every {job['every']} s of sim time"
        out["every:" + job["name"]] = (kinds[job["kind"]], job["name"], f"{becomes} -- {job['why']}")
    return out


REGISTRY.update(_from_flow())


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
