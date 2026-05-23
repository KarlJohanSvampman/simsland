# =========================================================
# IMPORTS
# =========================================================

from brain.context_builder import (
    build_context
)

from brain.intention_cleanup import (

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

from brain.narratives import (

    consolidate_relationship_narratives,

    consolidate_life_narratives
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

from systems.schedule_runtime import (
    update_schedule_runtime
)

from systems.offgrid import (
    maybe_go_offgrid,
    process_return
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

from systems.payments import (
    attempt_pay_bills
)

from systems.story import (
    update_story_arc
)

from systems.movement import (
    update_character_movement
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
    # ACTION
    # =====================================

    action = decision.get(
        "action"
    )

    if action:

        valid = validate_action(
            c,
            world,
            action
        )

        if valid:

            execute_activity(
                c,
                world,
                action
            )

        else:

            c["last_invalid_action"] = (
                action
            )

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

def update_agent(

    c,

    world
):

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
    # RFLECTIONS
    # =====================================

    process_reflections(
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
    # INTENTIONS
    # =====================================

    update_intentions(

        c,

        world
    )

    # =====================================
    # MOVEMENT
    # =====================================

    moving = update_character_movement(

        c,

        world
    )

    # =====================================
    # ACTIVE ACTIVITY
    # =====================================

    if c.get(
        "activity"
    ):

        update_activity(

            c,

            world
        )

        return

    # =====================================
    # STILL WALKING?
    # =====================================

    if moving:
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
    # EXECUTE
    # =====================================

    execute(

        c,

        decision,

        world
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