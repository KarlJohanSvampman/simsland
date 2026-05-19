# =========================================================
# IMPORTS
# =========================================================

from brain.perception import (
    perceive_environment
)

from brain.emotion import (
    update_emotion
)

from brain.memory import (
    decay_memories
)

from systems.habits import (
    decay_habits
)

from brain.intention import (
    generate_intentions
)

from brain.goals import (
    select_goal
)

from brain.planner import (
    generate_plan
)

from systems.activities import (
    execute_activity
)

from systems.commitment import (
    is_committed
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
    trigger_health_event,
    process_health
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
    from brain.intentions import (
        add_intention,
        decay_intentions
    )

    decay_intentions(c)
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
# ECONOMIC UPDATE
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
# OFFGRID UPDATE
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
# THINK
# =========================================================

def think(

    c,

    world
):

    # perception
    perception = perceive_environment(
        c,
        world
    )

    c["perception"] = perception

    # generate intentions
    generate_intentions(
        c,
        world
    )

    # committed?
    if is_committed(c):

        return c.get(
            "commitment",
            {}
        ).get("goal")


    traits = c.get(
        "traits",
        []
    )

    if "ambitious" in traits:

        add_intention(
            c,
            "career",
            70
        )

    if "romantic" in traits:

        add_intention(
            c,
            "romance",
            60
        )

    if "lonely" in traits:

        add_intention(
            c,
            "friendship",
            80
        )
    # select goal
    goal = select_goal(
        c,
        world
    )

    return goal


# =========================================================
# PLAN
# =========================================================

def plan(

    c,

    world,

    goal
):

    if not goal:
        return None

    return generate_plan(

        c,

        world,

        goal
    )


# =========================================================
# EXECUTE
# =========================================================

def execute(

    c,

    world,

    plan
):

    if not plan:
        return

    execute_activity(

        c,

        world,

        plan
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
    # INTERNAL STATE
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
    # ACTIVE ACTIVITY
    # =====================================

    if c.get("activity"):

        execute_activity(
            c,
            world,
            c["activity"]
        )

        return

    # =====================================
    # THINK
    # =====================================

    goal = think(
        c,
        world
    )

    # =====================================
    # PLAN
    # =====================================

    p = plan(
        c,
        world,
        goal
    )

    # =====================================
    # EXECUTE
    # =====================================

    execute(
        c,
        world,
        p
    )

    # =====================================
    # POST UPDATE
    # =====================================

    post_update(
        c,
        world
    )