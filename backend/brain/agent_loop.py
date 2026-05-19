# =========================================================
# IMPORTS
# =========================================================

from brain.context_builder import (
    build_context
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


# =========================================================
# INTERNAL STATE UPDATE
# =========================================================

def update_internal_state(

    c,

    world
):

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
# MAIN AGENT TICK
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

    if c.get("off_grid"):
        return

    # =====================================
    # INTERNAL
    # =====================================

    update_internal_state(
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
    # ALREADY BUSY?
    # =====================================

    if c.get("activity"):

        execute_activity(

            c,

            world,

            c["activity"]
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
    # LLM THINK
    # =====================================

    decision = think(
        context
    )

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