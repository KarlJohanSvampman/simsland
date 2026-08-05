# =========================================================
# IMPORTS
# =========================================================

from brain.context_builder import (
    build_context
)

from systems.activities import (
    execute_activity,
    start_activity
)

from brain.intentions import (
    clean_intentions,
    sort_intentions
)
from systems.body import (
    update_body_needs,
    ensure_body,
)

from systems.body_intentions import (
    generate_body_intentions
)
from brain.self_model import (
    consolidate_identity
)

from systems.cooking_process import (
        update_cooking_process
)


from systems.strategy import (
    resolve_strategy
)

from brain.narratives import (

    consolidate_relationship_narratives,

    consolidate_life_narratives
)

from systems.persistent_desires import (
    update_desires
)

from brain.llm_brain import (
    think
)

from brain.cognition_scheduler import (
    should_think,
    note_think,
)

from brain.memory import (
    decay_memories,
    store_memory
)

from brain.emotion import (
    update_emotion
)

from systems.habits import (
    decay_habits
)

from systems.activities import (
    execute_activity
)

from systems.scheduling import (
    update_schedule_runtime
)

from systems.travel import (
    update_travel,
    TRAVEL_FROZEN_STATES,
    TRAVEL_WALKING_STATES,
)

from systems.offgrid import (
    maybe_go_offgrid,
    maybe_schedule_doctor_visit,
    process_return
)

from systems.social_intentions import (
    update_social_intentions
)

from systems.jobs import (
    maybe_fire,
    apply_for_job,
    process_interview
)

from systems.health import (
    process_health
)

from systems.mail import (
    attempt_pay_bills,
    sort_household_mail,
    respond_to_mail
)

from systems.story import (
    update_story_arc
)

from systems.movement import (
    update_character_movement
)

from systems.action_router import (
    clear_expired_speech
)

from systems.posture import (
    promote_pending_posture
)

from systems.activity_queue import (
    process_activity_queue,
    suspend_activity_queue,
)

from systems.item_knowledge import (
    update_item_knowledge,
)

# =========================================================
# URGENT NEED THRESHOLDS — beyond these, interrupt a hobby
# Only activities flagged "interruptible" can be suspended.
# =========================================================
# body thresholds that trigger interruption (0-100 scale)
_BODY_INTERRUPT_THRESHOLDS = {
    "bladder":  88,
    "hunger":   82,
    "fatigue":  90,
    "hydration": 25,   # below this triggers (inverted: low hydration = urgent)
}

def _check_urgent_interruption(c):
    """Return a reason string if a body need is critical, else None."""
    body = c.get("body", {})
    if body.get("bladder", 0) >= _BODY_INTERRUPT_THRESHOLDS["bladder"]:
        return "urgent_bladder"
    if body.get("bowels", 0) >= 88:
        return "urgent_bowels"
    if body.get("hunger", 0) >= _BODY_INTERRUPT_THRESHOLDS["hunger"]:
        return "urgent_hunger"
    if body.get("fatigue", 0) >= _BODY_INTERRUPT_THRESHOLDS["fatigue"]:
        return "urgent_fatigue"
    if body.get("hydration", 100) <= _BODY_INTERRUPT_THRESHOLDS["hydration"]:
        return "urgent_thirst"
    return None


# =========================================================
# INTERNAL STATE UPDATE
# =========================================================

def update_internal_state(

    c,

    world
):
    ensure_body(c)           # migrate old characters; no-op on new ones
    update_body_needs(c)
    update_emotion(
        c,
        world
    )
    # Ensure lt_needs distributed (idempotent — no-op if already set)
    from systems.lt_needs import distribute_lt_needs
    distribute_lt_needs(c, world=world)

    clear_expired_speech(c, world)

    promote_pending_posture(c, world)

    decay_memories(c)

    decay_habits(c)

    process_health(
        c,
        world
    )

    from systems.waiting import tick_waiting
    tick_waiting(c, world)

    from systems.pain_fatigue import tick_pain_fatigue
    tick_pain_fatigue(c, world)

    from systems.pain_complaints import tick_pain_complaints
    tick_pain_complaints(c, world)

    from systems.curiosity import tick_curiosity
    tick_curiosity(c, world)

    consolidate_relationship_narratives(c)

    consolidate_life_narratives(c)

    consolidate_identity(c)
    generate_body_intentions(c)

# =========================================================
# ECONOMY
# =========================================================

def update_economy(

    c,

    world
):

    maybe_fire(
        c,
        world
    )

    apply_for_job(
        c,
        world
    )

    process_interview(
        c,
        world
    )

    attempt_pay_bills(
        c,
        world
    )


# =========================================================
# OFFGRID
# =========================================================

def update_offgrid(

    c,

    world
):

    process_return(
        c,
        world
    )

    update_travel(
        c,
        world
    )

    maybe_go_offgrid(
        c,
        world
    )

    maybe_schedule_doctor_visit(
        c,
        world
    )


# =========================================================
# STORE INTENTION
# =========================================================

def store_intention(

    c,

    intention
):

    if not intention:
        return

    # intention comes straight from parsed LLM JSON (see llm_brain.py's
    # decision schema) — clamp priority into the same 0-100 scale every
    # hardcoded intention (body_intentions.py etc.) uses. Without this, a
    # hallucinated numeric token (seen in practice: values in the
    # 10^31 range) makes final_priority() = category_score*1000 + priority
    # dwarf every other intention's score, permanently locking the
    # character onto whatever this intention is and starving all others
    # (sleep, eat, going outside, ...) forever.
    try:
        priority = float(intention.get("priority", 0))
    except (TypeError, ValueError):
        priority = 0

    intention["priority"] = max(0, min(100, priority))

    c.setdefault(
        "active_intentions",
        []
    )

    c["active_intentions"].append(
        intention
    )

    # limit
    c["active_intentions"] = (
        c["active_intentions"][-10:]
    )


# =========================================================
# PROCESS AI DECISION
# =========================================================

def process_decision(

    c,

    world,

    decision,

    available_actions=None
):

    from systems.action_validator import (
        validate_action
    )

    from systems.action_router import (
        route_action
    )

    # =====================================
    # THOUGHT
    # =====================================

    c["last_thought"] = (
        decision.get(
            "thought"
        )
    )

    # brain/llm_brain.py::_to_legacy_decision() maps the envelope's
    # "narration" straight into decision["thought"] unchanged -- the plan
    # for the Round 7 envelope called for narration to also land in its
    # own c["last_narration"] (for a future narration-feed UI, distinct
    # from last_thought's other historical readers) but that half of the
    # wiring was never actually added. Same source value today; kept as
    # its own field since the two are conceptually separate.
    c["last_narration"] = c["last_thought"]

    # =====================================
    # EMOTION
    # =====================================

    emotion = decision.get(
        "emotion"
    )

    if emotion:

        c["emotion"] = emotion

    # =====================================
    # REFLECTION
    # =====================================

    c["last_reflection"] = (
        decision.get(
            "reflection"
        )
    )

    # =====================================
    # INTENTION
    # =====================================

    intention = decision.get(
        "intention"
    )

    if intention:

        store_intention(
            c,
            intention
        )

    # =====================================
    # MEMORY
    # =====================================

    if decision.get("thought"):

        store_memory(

            c,

            text=decision[
                "thought"
            ],

            tags=[
                "thought"
            ],

            importance=10,

            source="internal"
        )

    # =====================================
    # ACTION + SPEECH  (via action router)
    # =====================================

    action = decision.get("action")
    speech = decision.get("speech")

    if action:

        # Resolve action["target_description"] -> action["target"] against
        # the real candidate ids, if the envelope set one and didn't
        # already supply a target — see brain/action_resolver.py. On
        # failure this clears `action` (falling through to the `elif
        # speech:` below, same as the LLM having given no action at all —
        # a target that couldn't be resolved must not also silently
        # swallow a real utterance).
        if available_actions is not None:
            from brain.action_resolver import resolve_and_apply
            if not resolve_and_apply(c, world, action, available_actions):
                action = None

        # brain/llm_brain.py::_to_legacy_decision() gives speech the same
        # target_description as the action when they're plausibly the
        # same person (speak/socialize/phone_*), rather than resolving it
        # a second time — reuse the action's already-resolved target here.
        if action and speech and not speech.get("target") and speech.get("target_description") and action.get("target"):
            speech["target"] = action["target"]

    if action:

        valid = validate_action(
            c,
            world,
            action
        )

        if valid:

            route_action(
                c,
                world,
                action,
                speech,
                definitions=world.get("definitions", {}),
                available_actions=available_actions
            )

            # route_action() above scaffolds c["activity"] for activity-style
            # action types (eat, sleep, work, ...) via _scaffold()/start_activity().
            # Process that scaffolded activity's first tick immediately rather
            # than waiting a full tick — but read it back off c, not the raw
            # LLM `action` dict, which never has the "phase"/"duration"/etc.
            # fields execute_activity() requires and isn't itself an activity.
            # Some action types (hug, confront, propose_chore, ...) don't set
            # c["activity"] at all, hence the truthiness guard.
            if action.get("type") not in (
                "speak", "socialize", "move",
                "interact", "wait", "call", "text",
            ) and c.get("activity"):
                execute_activity(
                    c,
                    world,
                    c["activity"]
                )

        else:

            c["last_invalid_action"] = action

            if speech:
                from systems.action_router import apply_speech
                apply_speech(c, world, speech)

    elif speech:
        # LLM wants to speak but gave no action (or its target failed to
        # resolve, see above)
        from systems.action_router import apply_speech
        apply_speech(c, world, speech)

# =========================================================
# POST UPDATE
# =========================================================

def post_update(

    c,

    world
):

    update_story_arc(c)


# =========================================================
# MAIN AGENT TICK
# =========================================================

def update_agent(

    c,

    world
):

    from systems.reflection import (
        process_reflections
    )

    # =====================================
    # OFFGRID
    # =====================================

    update_offgrid(

        c,

        world
    )

    if c.get(
        "off_grid"
    ) or c.get(
        "travel_state"
    ) in TRAVEL_FROZEN_STATES:
        return

    # =====================================
    # INTERNAL STATE
    # =====================================

    update_internal_state(

        c,

        world
    )

    # =====================================
    # PERSISTENT DESIRES
    # =====================================

    update_desires(
    c,
    world
    )

    # =====================================
    # COOKING FOOD
    # =====================================

    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    if household:

        update_cooking_process(

            c,

            household,

            world
        )

    # =====================================
    # REFLECTIONS
    # =====================================

    process_reflections(

        c,

        world
    )

    # =====================================
    # SOCIAL INTENTIONS
    # =====================================

    update_social_intentions(

        c,

        world
    )

    # =====================================
    # ECONOMY
    # =====================================

    update_economy(

        c,

        world
    )

    # =====================================
    # SCHEDULES
    # =====================================

    update_schedule_runtime(

        c,

        world
    )

    # =====================================
    # CLEAN / SORT INTENTIONS
    # =====================================

    clean_intentions(c)

    # Boost priorities for activities the character habitually does at this hour
    from systems.habits import apply_habit_bias_to_intentions
    apply_habit_bias_to_intentions(c, world)

    sort_intentions(c)

    # =====================================
    # ITEM KNOWLEDGE DECAY
    # =====================================

    update_item_knowledge(c, world)

    # =====================================
    # ACTIVE ACTIVITY
    # =====================================

    if c.get("activity"):

        # Check whether an urgent body need should interrupt a queued hobby.
        # Only activities in queues flagged "interruptible" can be suspended;
        # survival activities (sleep, toilet, eat) always run to completion.
        urgent = _check_urgent_interruption(c)
        if urgent and c.get("activity_queue"):
            from systems.hobby_requirements import HOBBY_REQUIREMENTS
            act_type = (c["activity"] or {}).get("type", "")
            hobby_params = c.get("_active_hobby_params", {})
            hobby_name   = hobby_params.get("hobby", "")
            interruptible = HOBBY_REQUIREMENTS.get(hobby_name, {}).get("interruptible", False)
            if interruptible:
                suspend_activity_queue(c, world, reason=urgent)
                # Fall through: no activity now, agent loop will address the urgent need
            else:
                execute_activity(c, world, c["activity"])
                return
        else:
            execute_activity(c, world, c["activity"])
            return

    # =====================================
    # MOVEMENT
    # =====================================
    # If still walking a previously-planned route, let it continue and
    # skip evaluating new intentions / calling the LLM this tick.

    moving = update_character_movement(
        c,
        world
    )

    if moving or c.get("travel_state") in TRAVEL_WALKING_STATES:
        return

    # =====================================
    # EXECUTE SOCIAL / BODY INTENTIONS
    # =====================================

    for intention in c.get(
        "active_intentions",
        []
    ):

        activity_type = resolve_strategy(
            c,
            world,
            intention
        )

        if not activity_type:
            continue

        started = start_activity(
            c,
            world,
            activity_type
        )

        if started:

            c["current_intention"] = (
                intention
            )

            return

    # =====================================
    # COGNITION GATE
    # =====================================
    # Only call the LLM if there's actually something to decide — an idle
    # cadence interval elapsed, an urgent body need just crossed threshold,
    # or an event (perception/activity/speech) woke this character. See
    # brain/cognition_scheduler.py for why this replaced calling think()
    # on every single tick.

    wake_reason = should_think(c, world)

    if not wake_reason:
        return

    # =====================================
    # BUILD CONTEXT
    # =====================================

    from brain.cognition_scheduler import wake_line as _wake_line
    context = build_context(
        c,
        world,
        trigger_reason=wake_reason,
        wake_line=_wake_line(c),
        staged=c.get("cognition", {}).get("staged_knowledge") or (),
    )

    # =====================================
    # THINK
    # =====================================

    decision = think(
        context,
        char_id=c["id"],
        session=c.get("_llm_session")
    )

    # Clear the wake state and schedule the next idle check-in regardless
    # of whether the LLM call succeeded — a failed call must not leave the
    # character re-triggering should_think() every tick forever.
    note_think(c, world, decision, wake_reason=wake_reason)

    if not decision:
        return

    # =====================================
    # PROCESS DECISION
    # =====================================

    process_decision(
        c,
        world,
        decision,
        available_actions=context.get("available_actions")
    )

    # =====================================
    # POST
    # =====================================

    post_update(
        c,
        world
    )
    #