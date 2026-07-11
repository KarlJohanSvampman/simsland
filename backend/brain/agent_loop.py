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

from systems.offgrid import (
    maybe_go_offgrid,
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
    process_health,
    trigger_health_event
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

    decay_memories(c)

    decay_habits(c)

    process_health(
        c,
        world
    )

    trigger_health_event(
        c,
        world
    )

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

    maybe_go_offgrid(
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

    decision
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
                definitions=world.get("definitions", {})
            )

            # still call execute_activity for non-router
            # action types (eat, sleep, work handled there)
            if action.get("type") not in (
                "speak", "socialize", "move",
                "interact", "wait", "call", "text",
            ):
                execute_activity(
                    c,
                    world,
                    action
                )

        else:

            c["last_invalid_action"] = action

    elif speech:
        # LLM wants to speak but gave no movement action
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

    from systems.social_execution import (
        execute_social_intention
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
    ):
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

    if moving:
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
    # BUILD CONTEXT
    # =====================================

    context = build_context(
        c,
        world
    )

    # =====================================
    # THINK
    # =====================================

    decision = think(
        context
    )

    if not decision:
        return

    # =====================================
    # PROCESS DECISION
    # =====================================

    process_decision(
        c,
        world,
        decision
    )

    # =====================================
    # POST
    # =====================================

    post_update(
        c,
        world
    )
    #