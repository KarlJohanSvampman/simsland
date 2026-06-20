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
    update_body_needs
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


# =========================================================
# INTERNAL STATE UPDATE
# =========================================================

def update_internal_state(

    c,

    world
):
    update_body_needs(c)
    update_emotion(
        c,
        world
    )

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
    merge_body_intentions(c)

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
# MAIN AGEN  T TICK
# =========================================================

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

    sort_intentions(c)

    # =====================================
    # ACTIVE ACTIVITY
    # =====================================

    if c.get(
        "activity"
    ):

        execute_activity(

            c,

            world,

            c["activity"]
        )

        return

    # =====================================
    # MOVEMENT
    # =====================================

    moving = update_character_movement(

        c,

        world
    )

    if moving:
        return

    # =====================================
    # EXECUTE SOCIAL INTENTIONS
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
    # ===================================================================

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

def merge_body_intentions(c):

    for intention in generate_body_intentions(c):

        store_intention(
            c,
            {
                "type": intention["type"],
                "priority": int(
                    intention["priority"] * 100
                ),
                "source": "body",
                "reason": "body_need"
            }
        )
