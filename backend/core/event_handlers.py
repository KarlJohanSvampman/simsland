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
  job_application_submitted → advance_job_application (polled on its own stage_deadline_tick)
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

import random

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


def _on_character_fired_detective_work(data, world):
    from systems.detective_work import notice_job_loss
    c = world.get("characters", {}).get(data["character_id"])
    if c:
        notice_job_loss(c, world)

subscribe("character_fired", _on_character_fired_detective_work)


def _on_character_fired_convenience(data, world):
    """A layoff is an involuntary loss -- disrupts the established
    employment convenience (systems/convenience.py). No specific person
    to blame here (maybe_fire is an economy-wide roll, not a person's
    decision) -- feeds a "rebuild employment" desire instead."""
    from systems.convenience import disrupt_convenience
    c = world.get("characters", {}).get(data["character_id"])
    if c:
        disrupt_convenience(c, "employment", world)

subscribe("character_fired", _on_character_fired_convenience)


def _on_job_application_submitted(data, world):
    """Nothing to do immediately — advance_job_application() polls its own
    stage_deadline_tick from sim_loop.py's job_market cadence."""
    pass

subscribe("job_application_submitted", _on_job_application_submitted)


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
    """Their grievances against someone have built up: they want to take it up with them. Nothing is started for
    them -- the wish goes into their prompt (social/context.py) and they're woken to decide whether, when and how to
    raise it, or to let it go and avoid the person (low standing doesn't have to mean a confrontation)."""
    initiator = world.get("characters", {}).get(data["initiator_id"])
    target    = world.get("characters", {}).get(data["target_id"])
    if not initiator or not target:
        return
    wants = initiator.setdefault("wants_to_raise", {})
    wants[data["target_id"]] = {"since": world.get("tick", 0), "score": round(data.get("score", 0), 1)}
    from brain.cognition_scheduler import wake_character
    wake_character(initiator, world, "wants_to_raise", {"target_id": data["target_id"],
                                                        "target_name": target.get("name")})

subscribe("confrontation_desired", _on_confrontation_desired)


_BAD_CONFLICT_OUTCOMES = {"storm_off", "cold_shoulder", "physical_resolved", "suppressed"}


def _on_conflict_resolved(data, world):
    """Any resolved argument/fight gets committed to memory (with a real
    validation/comfort need attached, systems/confiding.py) for everyone
    involved -- not just the absence-suspicion confrontations that already
    tag their own. A bad-enough outcome also gives each party a real
    chance of moving out for a while (systems/temporary_separation.py)."""
    from systems.confiding import tag_dramatic_memory
    from systems import fights

    chars = world.get("characters", {})
    parties = [chars[pid] for pid in data.get("parties", []) if pid in chars]
    if not parties:
        return

    outcome = data.get("outcome")
    from social.confrontations import lookup, STAGES
    conflict = lookup(world, data.get("conflict_id")) or {}
    topic = conflict.get("topic") or fights.topic_of(conflict.get("issues"))
    aggressor = conflict.get("aggressor")
    # a confrontation (social/confrontations.py) is a fight only once it got to a verbal confrontation or worse
    was_fight = outcome == "physical_resolved" or "stage_idx" not in conflict or \
        STAGES.index(conflict.get("peak_stage") or STAGES[0]) >= 2

    # what the fight was about and who was in it goes on the record (a suppressed one never got said, an agreement was no fight)
    entry = None
    if outcome not in ("agreement", "suppressed") and was_fight:
        inc = next((i for i in world.get("incidents", []) if data.get("conflict_id") and i.get("conflict_id") == data.get("conflict_id")), None)
        entry = fights.log_fight(world, [p["id"] for p in parties], topic, outcome, aggressor=aggressor, conflict=conflict,
                                 incident_id=inc["id"] if inc else None)
        if inc:
            inc["fight_id"] = entry["id"]
        # filed under the issue between them (social/issues.py)
        from social.issues import file_fight
        file_fight(world, entry)

    for c in parties:
        others = [p["id"] for p in parties if p["id"] != c["id"]]
        if outcome == "suppressed":
            if c["id"] == conflict.get("initiator"):
                text = f"Wanted to take up {topic} with {fights.names(world, others)} but backed down and kept it in."
            else:
                text = f"Sensed that {fights.names(world, others)} was upset, but nothing was said."
            importance = 0.45
        elif not was_fight:
            res = (conflict.get("resolution") or {})
            text = f"Took up {topic} with {fights.names(world, others)}: {str(res.get('outcome', outcome)).replace('_', ' ')}" \
                + (f" -- {res['summary']}" if res.get("summary") else ".")
            importance = 0.45
        else:
            text = fights.memory_line(world, c, others, topic, outcome, conflict=conflict, aggressor=aggressor)
            importance = 0.5 if outcome in ("agreement", "de_escalated") else 0.65
        mem = tag_dramatic_memory(c, world, text, importance=importance, people=others)
        if mem is not None:
            mem["conflict_outcome"] = outcome
            mem["fight_topic"] = topic
            if entry:
                mem["fight_id"] = entry["id"]

    # A bad ending between people who live together no longer has a chance of sending someone off to stay elsewhere
    # on the spot: it opens a rift, which they try to resolve first -- leaving comes later, and for a reason
    # (systems/rifts.py).
    from systems.rifts import on_conflict_resolved as _rift_on_conflict
    _rift_on_conflict(world, data)

subscribe("conflict_resolved", _on_conflict_resolved)


def _on_contract_violated(data, world):
    """Feed a contract violation back into the grievance system."""
    from systems.grievances import add_grievance
    victim = world.get("characters", {}).get(data["victim_id"])
    if victim:
        k = (world.get("social_contracts") or {}).get(data.get("contract_id")) or {}
        last = (k.get("violation_records") or [{}])[-1]
        disputed = bool(last.get("disputed"))
        from systems.grievances import SEVERITY
        add_grievance(victim, data["violator_id"], "contract_violated", world,
                      severity=SEVERITY["contract_violated"] * (0.5 if disputed else 1.0),
                      details={"commitment": data.get("commitment"), "contract_id": data.get("contract_id"),
                               "disputed": disputed})
        from social import standing
        standing.change(victim, data["violator_id"], world, "contract_violated", delta=-4 if disputed else None,
                        cause=f"didn't keep to: {data.get('commitment')}" + (" (they deny it)" if disputed else ""))

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
    from systems import fights
    chars = world.get("characters", {})
    parties = [p for p in data.get("parties", []) if p in chars]
    if not parties:
        return
    # one incident per fight: whoever threw the first punch is the offender, the other the victim
    aggressor_id = data.get("aggressor") if data.get("aggressor") in parties else parties[0]
    victim_id = next((p for p in parties if p != aggressor_id), None)
    topic = data.get("topic") or fights.topic_of(data.get("issues"), data.get("context"))
    inc = report_assault_incident(world, chars[aggressor_id], chars.get(victim_id), topic=topic,
                                  context=data.get("context"), conflict_id=data.get("conflict_id"))
    if not data.get("conflict_id"):
        # nothing else will log a fight that came from a one-off outburst (a conflict is logged when it resolves)
        entry = fights.log_fight(world, parties, topic, "physical_resolved", aggressor=aggressor_id, context=data.get("context"),
                                 issues=data.get("issues"), incident_id=inc["id"])
        inc["fight_id"] = entry["id"]

subscribe("fight_physical", _on_fight_physical)


def _co_present(c, world):
    """Everyone else physically here right now -- same room_id-preferred/
    building_id-fallback idiom as systems/action_router.py::
    _co_present_characters (kept as a small local copy rather than a
    cross-module import of that leading-underscore helper)."""
    room_id = c.get("room_id")
    building_id = c.get("building_id")
    if not room_id and not building_id:
        return []
    result = []
    for other_id, other in world.get("characters", {}).items():
        if other_id == c["id"] or other.get("alive") is False:
            continue
        if room_id and other.get("room_id") == room_id:
            result.append(other)
        elif not room_id and building_id and other.get("building_id") == building_id:
            result.append(other)
    return result


def _on_hostile_action_resolved(data, world):
    """systems/hostile_actions.py's own docstring confirmed this event
    was emitted with ZERO subscribers before this -- systems/
    target_reactions.py::flag_provocation() already wakes the direct
    TARGET for real, but nobody who merely witnessed a punch/kick/shove/
    threaten/grab/hold/wrestle land got any reactive prompt at all.
    Gated to outcome == "hit" -- a miss/fumble isn't dramatic enough to
    interrupt a bystander who wasn't even directly involved."""
    if data.get("outcome") != "hit":
        return
    chars = world.get("characters", {})
    actor = chars.get(data.get("actor_id"))
    target = chars.get(data.get("target_id"))
    if not actor or not target:
        return

    from brain.cognition_scheduler import wake_character
    for other in _co_present(actor, world):
        if other["id"] in (actor["id"], target["id"]):
            continue
        wake_character(other, world, "witnessed_violence", {
            "actor_id":     actor["id"],
            "actor_name":   actor.get("name", "someone"),
            "target_id":    target["id"],
            "target_name":  target.get("name", "someone"),
            "action":       data.get("action"),
            "incident_id":  data.get("incident_id"),
        })

subscribe("hostile_action_resolved", _on_hostile_action_resolved)


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
subscribe("speech_unheard", _wake("speaker_id", "not_heard"))      # systems/conversation_reach.py::note_unheard


# ── Debug-event bubbles + execution-trace memory (systems/debug_log.py) ────
# Per the user's explicit ask: a visible, colored debug bubble (green for
# actions/activities, red for reactions, purple for violent/illegal ones)
# plus a real low-importance memory entry every time an activity actually
# starts, completes, is interrupted, or is aborted. Riding the existing
# activity_started/activity_completed/activity_finished/activity_aborted
# emit() calls (systems/activities.py, systems/activity_queue.py) rather
# than adding a fourth set of direct call sites there.

def _on_activity_started(data, world):
    from systems.debug_log import log_activity
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        act = c.get("activity") or {}
        from systems.activity_trace import begin
        begin(c, world)
        log_activity(c, world, data.get("activity_type", "?"), "started", target_id=data.get("target_id"),
                    interaction=act.get("interaction"), anchor_name=act.get("anchor_name"))
        # A character stuck repeating the same activity notices and breaks out
        # (systems/loop_guard.py).
        try:
            from systems.loop_guard import note_start
            note_start(c, world, data.get("activity_type"))
        except Exception as exc:
            print(f"[loop_guard] error: {exc}")

subscribe("activity_started", _on_activity_started)


def _on_activity_completed(data, world):
    from systems.debug_log import log_activity
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        # activity_completed fires as the activity resolves -- c["activity"]
        # may already be cleared by the time this handler runs, same as
        # activity_finished below, so interaction/anchor_name are a
        # best-effort read, not guaranteed present.
        act = c.get("activity") or {}
        log_activity(c, world, data.get("activity_type", "?"), "completed", target_id=data.get("target_id"),
                    interaction=act.get("interaction"), anchor_name=act.get("anchor_name"))

subscribe("activity_completed", _on_activity_completed)


def _on_activity_finished(data, world):
    from systems.debug_log import log_activity
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        act = c.get("activity") or {}
        log_activity(c, world, data.get("activity_type", "?"), "finished", target_id=data.get("target_id"),
                    interaction=act.get("interaction"), anchor_name=act.get("anchor_name"))

subscribe("activity_finished", _on_activity_finished)


def _on_activity_aborted(data, world):
    from systems.debug_log import log_debug_event
    c = world.get("characters", {}).get(data.get("character_id"))
    if c:
        reason = (data.get("reason") or "unknown").replace("_", " ")
        log_debug_event(c, world, "activity", f"Activity queue aborted: {reason}")

subscribe("activity_aborted", _on_activity_aborted)


# ── Household summary logging (systems/household_summary.py) ──────────
# Feeds household["event_log"], later condensed hourly/daily/weekly by
# sim_loop.py's calendar-boundary-gated sweeps. Presence-gated inside
# the handlers themselves (systems/home_presence.py::is_character_home).

def _on_household_activity_started(data, world):
    from systems.household_summary import on_activity_started
    on_activity_started(data, world)

subscribe("activity_started", _on_household_activity_started)


def _on_household_activity_completed(data, world):
    from systems.household_summary import on_activity_completed
    on_activity_completed(data, world)

subscribe("activity_completed", _on_household_activity_completed)


def _on_household_activity_interrupted(data, world):
    from systems.household_summary import on_activity_interrupted
    on_activity_interrupted(data, world)

subscribe("activity_interrupted", _on_household_activity_interrupted)


def _on_household_speech_spoken(data, world):
    from systems.household_summary import on_speech_spoken
    on_speech_spoken(data, world)

subscribe("speech_spoken", _on_household_speech_spoken)


# ── Relationship impact (systems/relationship_ledger.py subscribes on import) ──
import systems.relationship_ledger  # noqa: E402,F401


# ── Clock boundary events + scheduled jobs (systems/calendar_handlers.py) ──
import systems.calendar_handlers  # noqa: E402,F401


# ── Lazy needs: the scheduler handler for per-character body timers ──
import systems.body_lazy  # noqa: E402,F401


# ── Character actors: model answers arrive as events (brain/cognition_actor.py) ──
import brain.cognition_actor  # noqa: E402,F401
import systems.worry_relief  # noqa: E402,F401  (subscribes to activity_completed)
import systems.online_posts  # noqa: E402,F401  (subscribes to activity_completed: browsing social media reads posts)
import systems.rumors  # noqa: E402,F401  (subscribes to third_party_remark)
