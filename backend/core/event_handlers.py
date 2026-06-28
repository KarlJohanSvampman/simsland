"""
core/event_handlers.py — subscribe all event-driven handlers at startup.

Import this module once (in main.py or sim_loop) to wire everything up.
Each handler receives (event_data, world) and runs synchronously inside
flush_events() at the end of the tick that emitted the event.

Event chain overview:
  health_threshold_crossed  → trigger_health_event / process_health
  incident_created          → auto_report_incidents
  emergency_call_created    → dispatch
  responder_dispatched      → (resolve runs on next responder tick)
  incident_resolved         → maybe_arrest_from_incidents
  trial_scheduled           → process_trials (on its tick)
  character_jailed          → process_jail watch (cadence ÷30)
  character_fired           → apply_for_job
  interview_scheduled       → process_interview (on its tick)
  bills_overdue             → evict_household
  household_wants_to_move   → _do_migrate
"""

from core.event_bus import subscribe


# ── Health ────────────────────────────────────────────────

def _on_health_threshold(data, world):
    from systems.health import trigger_health_event, process_health
    c = world.get("characters", {}).get(data["character_id"])
    if c:
        trigger_health_event(c, world)
        process_health(c, world)

subscribe("health_threshold_crossed", _on_health_threshold)


# ── Incident pipeline ─────────────────────────────────────

def _on_incident_created(data, world):
    """Auto-report the incident that was just created."""
    from systems.emergency import auto_report_incidents
    auto_report_incidents(world)

subscribe("incident_created", _on_incident_created)


def _on_call_created(data, world):
    """Dispatch a responder as soon as a 911 call comes in."""
    from systems.emergency import dispatch
    dispatch(world)

subscribe("emergency_call_created", _on_call_created)


def _on_incident_resolved(data, world):
    """Check for arrests once an emergency is resolved."""
    from systems.law import maybe_arrest_from_incidents
    maybe_arrest_from_incidents(world)

subscribe("incident_resolved", _on_incident_resolved)


def _on_trial_scheduled(data, world):
    """Process any trial that is now due (tick already past trial_tick)."""
    from systems.law import process_trials
    process_trials(world)

subscribe("trial_scheduled", _on_trial_scheduled)


def _on_character_jailed(data, world):
    """Start watching for release — mark character for jail processing."""
    # process_jail still runs on a ÷30 cadence in sim_loop because
    # we need to poll for jail_until tick. Nothing extra needed here;
    # the emit is useful for downstream hooks (reputation, notifications).
    pass

subscribe("character_jailed", _on_character_jailed)


# ── Jobs ──────────────────────────────────────────────────

def _on_character_fired(data, world):
    """Immediately start job search for the fired character."""
    from systems.jobs import apply_for_job
    c = world.get("characters", {}).get(data["character_id"])
    if c:
        apply_for_job(c, world)

subscribe("character_fired", _on_character_fired)


def _on_interview_scheduled(data, world):
    """Nothing to do immediately — process_interview will fire on its tick."""
    pass

subscribe("interview_scheduled", _on_interview_scheduled)


# ── Housing ───────────────────────────────────────────────

def _on_bills_overdue(data, world):
    from systems.eviction import evict_household
    hh = world.get("households", {}).get(data["household_id"])
    if hh:
        evict_household(hh, world)

subscribe("bills_overdue", _on_bills_overdue)


def _on_wants_to_move(data, world):
    from systems.migration import _do_migrate
    hh = world.get("households", {}).get(data["household_id"])
    if hh:
        _do_migrate(hh, world)

subscribe("household_wants_to_move", _on_wants_to_move)


# ── Conflict pipeline ─────────────────────────────────────

def _on_confrontation_desired(data, world):
    """Start a conflict when a character's grievances hit threshold."""
    from systems.conflict_pipeline import start_conflict
    initiator = world.get("characters", {}).get(data["initiator_id"])
    target    = world.get("characters", {}).get(data["target_id"])
    if not initiator or not target:
        return
    # Only start if they're in the same room or building
    same_room     = initiator.get("room_id")     and initiator.get("room_id")     == target.get("room_id")
    same_building = initiator.get("building_id") and initiator.get("building_id") == target.get("building_id")
    if same_room or same_building:
        start_conflict(data["initiator_id"], data["target_id"], world)

subscribe("confrontation_desired", _on_confrontation_desired)


def _on_contract_violated(data, world):
    """Feed a contract violation back into the grievance system."""
    from systems.grievances import add_grievance
    victim = world.get("characters", {}).get(data["victim_id"])
    if victim:
        add_grievance(victim, data["violator_id"], "contract_violated", world,
                      details={"commitment": data.get("commitment")})

subscribe("contract_violated", _on_contract_violated)


def _on_fight_physical(data, world):
    """Physical altercation — trigger the emergency/law pipeline."""
    from systems.emergency import trigger_incident
    for pid in data.get("parties", []):
        c = world.get("characters", {}).get(pid)
        if c:
            trigger_incident(world, c)
            break  # one incident per fight is enough

subscribe("fight_physical", _on_fight_physical)
