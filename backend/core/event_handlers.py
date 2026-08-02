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
  person_entered_view       → wake_character(observer, "person_entered_view")
  heard_speech               → wake_character(listener, "heard_speech")

Latency note on the last two: emit() is called from inside a character's own
agent worker thread (brain/perception.py::perceive(), systems/
action_router.py::apply_speech()), but the target of the wake is a
*different* character who may be concurrently processed by their own worker
thread this same tick. Mutating another character's c["cognition"] dict
off-thread would race. Routing through emit() (thread-safe, see
core/event_bus.py) and applying the actual wake_character() call here, at
flush() (main-thread-only, after every worker for the tick has finished),
avoids that at the cost of the wake landing one tick later than the emit —
invisible at 1 tick == 1 simulated second. Self-wakes (a character's own
activity finishing/aborting) don't have this problem — see
systems/activities.py / systems/activity_queue.py, which call
wake_character() directly, immediately, no bus round-trip needed.
"""

from core.event_bus import subscribe


def _wake(char_key, reason):
    """Build a handler that resolves world["characters"][data[char_key]]
    and marks it due for a think() call, tagging the wake with the event's
    own payload so cognition_scheduler/context_builder can render a
    wake_line without a second lookup."""
    def handler(data, world, _char_key=char_key, _reason=reason):
        from brain.cognition_scheduler import wake_character
        c = world.get("characters", {}).get(data.get(_char_key))
        if not c:
            return
        wake_character(c, world, _reason, data)
    return handler


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


def _on_lie_detected(data, world):
    """A lie caught by systems/excuses.py revives the dead "lied"
    grievance preset -- the event was already emitted (docstring said
    "for grievance system") but nothing subscribed to it until now."""
    from systems.grievances import add_grievance
    authority = world.get("characters", {}).get(data["authority_id"])
    if authority:
        add_grievance(authority, data["liar_id"], "lied", world,
                      details={"lie": data.get("lie"), "truth": data.get("truth")})

subscribe("lie_detected", _on_lie_detected)


def _on_fight_physical(data, world):
    """Physical altercation — reliably create a real incident (not the
    dice-roll trigger_incident(), which almost never fires for the exact
    fight that just happened)."""
    from systems.emergency import report_assault_incident
    for pid in data.get("parties", []):
        c = world.get("characters", {}).get(pid)
        if c:
            report_assault_incident(world, c)
            break  # one incident per fight is enough

subscribe("fight_physical", _on_fight_physical)


# ── Reputation hooks ───────────────────────────────────────────────────────

def _on_character_arrested(data, world):
    from systems.reputation import apply_reputation_event
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        apply_reputation_event(c, "arrested", world)

subscribe("character_arrested", _on_character_arrested)


def _on_character_convicted(data, world):
    from systems.reputation import apply_reputation_event
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        apply_reputation_event(c, "convicted", world)
        apply_reputation_event(c, "notoriety_crime", world)

subscribe("character_jailed", _on_character_convicted)


def _on_character_fired_rep(data, world):
    from systems.reputation import apply_reputation_event
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        apply_reputation_event(c, "fired", world)

subscribe("character_fired", _on_character_fired_rep)


def _on_fight_rep(data, world):
    from systems.reputation import apply_reputation_event
    for pid in data.get("parties", []):
        c = world.get("characters", {}).get(pid)
        if c:
            apply_reputation_event(c, "assault", world)
            apply_reputation_event(c, "notoriety_violence", world)

subscribe("fight_physical", _on_fight_rep)


# ── Gossip / social transgression ─────────────────────────────────────────

def _on_social_transgression_gossip(data, world):
    """
    When a character is outed for ignoring a rejection, word spreads through
    their social network.  Close contacts of the gossiper hear about it and
    form grievances / see a reputation hit.
    """
    from systems.grievances import add_grievance
    from systems.reputation import apply_reputation_event

    accused_id  = data.get("accused_id")
    gossiper_id = data.get("gossiper_id")
    severity    = data.get("severity", 0.50)

    accused  = world.get("characters", {}).get(accused_id)
    gossiper = world.get("characters", {}).get(gossiper_id)
    if not accused or not gossiper:
        return

    # Spread to gossiper's social connections (friends + acquaintances)
    for oid, rel in gossiper.get("relationships", {}).items():
        if rel.get("trust", 0) < 30:
            continue
        listener = world.get("characters", {}).get(oid)
        if not listener or listener["id"] == accused_id:
            continue
        # Listener adds a grievance against the accused proportional to how
        # close they are to the gossiper and the severity of the act
        bond_factor = rel.get("trust", 30) / 100.0
        add_grievance(
            listener, accused_id, "witnessed_transgression", world,
            severity=severity * bond_factor * 10,
            details={"heard_from": gossiper_id, "transgression": data.get("transgression")},
        )

subscribe("social_transgression_gossip", _on_social_transgression_gossip)


# ── Cognition wakes (see brain/cognition_scheduler.py) ─────────────────────

subscribe("person_entered_view", _wake("observer_id", "person_entered_view"))
subscribe("heard_speech", _wake("listener_id", "heard_speech"))
