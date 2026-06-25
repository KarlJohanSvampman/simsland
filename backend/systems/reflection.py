import random
import asyncio

from llm.cognition_jobs import (
    queue_social_reflection
)

from systems.social_models import (
    add_social_observation
)


# =========================================================
# ENSURE REFLECTIONS
# =========================================================

def ensure_reflections(c):

    c.setdefault(
        "pending_reflections",
        []
    )


# =========================================================
# SCHEDULE REFLECTION
# =========================================================

def schedule_reflection(

    c,

    reflection
):

    ensure_reflections(c)

    c[
        "pending_reflections"
    ].append(reflection)


# =========================================================
# PROCESS REFLECTIONS
# =========================================================

def process_reflections(

    c,

    world
):

    ensure_reflections(c)

    now = world["tick"]

    remaining = []

    for r in c[
        "pending_reflections"
    ]:

        if r[
            "scheduled_tick"
        ] > now:

            remaining.append(r)
            continue

        handle_reflection(

            c,

            world,

            r
        )

    c[
        "pending_reflections"
    ] = remaining

# =========================================================
# HANDLE REFLECTION
# =========================================================

def handle_reflection(

    c,

    world,

    reflection
):

    target_id = reflection.get(
        "target_id"
    )

    if not target_id:
        return

    target = world[
        "characters"
    ].get(
        target_id
    )

    if not target:
        return

    observations = reflection.get(
        "observations",
        []
    )

    # =====================================================
    # EMOTIONAL FILTERING
    # =====================================================

    emotion = c.get(
        "emotion"
    )

    if emotion == "angry":

        observations.append({

            "text":
                "Something about them feels irritating.",

            "emotional_weight":
                0.6
        })

    elif emotion == "lonely":

        observations.append({

            "text":
                "I wish they cared more about me.",

            "emotional_weight":
                0.5
        })

    elif emotion == "insecure":

        observations.append({

            "text":
                "I feel judged around them.",

            "emotional_weight":
                0.7
        })

    # =====================================================
    # STORE OBSERVATIONS
    # =====================================================

    for o in observations:

        add_social_observation(

            c,

            target_id,

            o["text"],

            o.get(
                "emotional_weight",
                0
            )
        )

    # =====================================================
    # QUEUE LLM REFLECTION
    # =====================================================

    asyncio.create_task(

        queue_social_reflection(

            observer=c,

            target=target,

            context={

                "observations":
                    observations,

                "tick":
                    world["tick"]
            }
        )
    )

from brain.memory import (
    biased_recall,

    rewrite_memory_salience
)

# =========================================================
# REVISIT MEMORIES
# =========================================================

def revisit_related_memories(

    c,

    target_id
):

    memories = biased_recall(

        c,

        limit=20
    )

    for m in memories:

        people = m.get(
            "people",
            []
        )

        if target_id not in people:
            continue

        emotion = c.get(
            "emotion"
        )

        if emotion in [

            "angry",

            "resentful"
        ]:

            rewrite_memory_salience(

                c,

                m,

                0.15
            )

        elif emotion in [

            "romantic",

            "nostalgic"
        ]:

            rewrite_memory_salience(

                c,

                m,

                0.10
            )