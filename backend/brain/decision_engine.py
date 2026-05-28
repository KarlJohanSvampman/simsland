import json
import random

from llm.llm_client import (
    call_llm,
    call_llm_safe
)


# =========================================================
# ⚡ HEURISTIC GATE
# =========================================================

def should_use_llm(c):

    needs = c.get(
        "needs",
        {}
    )

    # =====================================
    # BASIC SURVIVAL
    # =====================================

    if needs.get(
        "hunger",
        0
    ) > 0.8:

        return False

    if needs.get(
        "energy",
        1
    ) < 0.2:

        return False

    # =====================================
    # ALREADY EXECUTING PLAN
    # =====================================

    if c.get(
        "plan"
    ):

        return False

    # =====================================
    # STRONG EMOTIONS
    # =====================================

    if c.get(
        "emotion"
    ) in [

        "angry",

        "jealous",

        "fear",

        "sad"

    ]:

        return True

    # =====================================
    # ACTIVE ATTENTION
    # =====================================

    attention = c.get(
        "attention",
        {}
    )

    focus = attention.get(
        "focus"
    )

    if focus:

        if focus.get(
            "strength",
            0
        ) > 0.5:

            return True

    # =====================================
    # DEFAULT
    # =====================================

    return False


# =========================================================
# 🔁 DECISION CACHE
# =========================================================

def get_recent_decision(c):

    return c.get(
        "_last_decision"
    )


def set_recent_decision(

    c,

    decision
):

    c["_last_decision"] = decision


# =========================================================
# 🧠 FALLBACK
# =========================================================

def fallback_decision(c):

    needs = c.get(
        "needs",
        {}
    )

    if needs.get(
        "hunger",
        0
    ) > 0.7:

        return {

            "action":
                "eat"
        }

    if needs.get(
        "energy",
        1
    ) < 0.3:

        return {

            "action":
                "sleep"
        }

    if needs.get(
        "bladder",
        0
    ) > 0.7:

        return {

            "action":
                "toilet"
        }

    return {

        "action":
            "idle"
    }


# =========================================================
# 🧠 PERCEPTION SUMMARY
# =========================================================

def summarize_perception(
    perception
):

    lines = []


    
    # =====================================
    # PEOPLE
    # =====================================

    for p in perception.get(
        "visible_people",
        []
    ):

        line = (

            f"You see "

            f"{p['name']} "

            f"nearby looking "

            f"{p['appears']}."
        )

        if p.get(
            "activity"
        ):

            line += (

                f" They appear to be "

                f"{p['activity']}."
            )

        lines.append(line)

   # =====================================
    # SOCIAL RELATIONSHIPS
    # =====================================

    for r in perception.get(
        "social_relations",
        []
    ):

        target = r.get(
            "target"
        )

        for i in r.get(
            "interpretation",
            []
        ):

            lines.append(

                f"Around {target}, "

                f"{i}."
            )
    # =====================================
    # SOCIAL SCENES
    # =====================================

    for s in perception.get(
        "social_scenes",
        []
    ):

        topic = s.get(
            "topic"
        ) or "something"

        tone = s.get(
            "tone"
        ) or "neutral"

        participants = ", ".join(
            s.get(
                "participants",
                []
            )
        )

        line = (

            f"There is a "

            f"{tone} "

            f"conversation about "

            f"{topic} "

            f"between "

            f"{participants}."
        )

        if s.get(
            "conflict",
            0
        ) > 0.6:

            line += (
                " The interaction feels tense."
            )

        if s.get(
            "warmth",
            0
        ) > 0.7:

            line += (
                " The atmosphere feels warm."
            )

        lines.append(line)

    # =====================================
    # AUDIO
    # =====================================

    for a in perception.get(
        "audible_events",
        []
    ):

        lines.append(

            f"You hear "

            f"{a['speaker']} "

            f"speaking nearby."
        )
    # =====================================
    # SUMMARIZE PERCIEVED ENVIRONMENT
    # =====================================
    env = perception.get(
        "environment",
        {}
    )

    if env.get(
        "clutter",
        0
    ) > 0.5:

        lines.append(
            "The environment feels cluttered and messy."
        )

    if env.get(
        "crowded"
    ):

        lines.append(
            "The area feels somewhat crowded."
        )

    # =====================================
    # EMPTY
    # =====================================

    if not lines:

        return (
            "Nothing especially "
            "noteworthy is happening nearby."
        )

    return "\n".join(lines)


# =========================================================
# 🧠 ATTENTION SUMMARY
# =========================================================

def build_attention_summary(

    c,

    world
):

    attention = c.get(
        "attention",
        {}
    )

    focus = attention.get(
        "focus"
    )

    if not focus:

        return (

            "Nothing strongly "
            "holds your attention "
            "right now."
        )

    key = focus.get(
        "key",
        ""
    )

    strength = focus.get(
        "strength",
        0
    )

    intensity = "mildly"

    if strength > 0.75:

        intensity = "strongly"

    elif strength > 0.45:

        intensity = "noticeably"

    # =====================================
    # PERSON
    # =====================================

    if key.startswith(
        "person:"
    ):

        pid = key.split(":")[1]

        other = world.get(
            "characters",
            {}
        ).get(pid)

        if other:

            return (

                f"You are {intensity} "

                f"focused on "

                f"{other.get('name')}."
            )

    # =====================================
    # SCENE
    # =====================================

    if key.startswith(
        "scene:"
    ):

        scene = key.split(":")[1]

        return (

            f"Your attention keeps "

            f"returning to the "

            f"{scene} situation nearby."
        )

    # =====================================
    # EVENT
    # =====================================

    if key.startswith(
        "event:"
    ):

        evt = key.split(":")[1]

        return (

            f"You remain distracted "

            f"by the recent "

            f"{evt}."
        )

    return (
        "Your thoughts feel scattered."
    )


# =========================================================
# 🧠 LLM DECISION
# =========================================================

async def llm_decision(

    c,

    world,

    perception,

    memories
):

    attention_summary = (
        build_attention_summary(
            c,
            world
        )
    )

    perception_summary = (
        summarize_perception(
            perception
        )
    )

    prompt = f"""
You are {c.get("name")}.

You are a real person living inside a persistent simulated world.

Think naturally and emotionally.

Do not behave randomly.

Maintain continuity of attention, emotion, relationships, obligations, and ongoing situations.

Current emotional state:
{c.get("emotion")}

Current needs:
{json.dumps(c.get("needs", {}), indent=2)}

Perceived surroundings:
{perception_summary}

Current attentional focus:
{attention_summary}

Recent memories:
{memories}

Respond ONLY with valid JSON.

Format:
{{
  "action": "...",
  "target": "...",
  "reason": "..."
}}
"""

    try:

        result = await call_llm(

            [
                {
                    "role":
                        "user",

                    "content":
                        prompt
                }
            ]
        )

        if (

            isinstance(result, dict)

            and

            "message" in result
        ):

            text = result[
                "message"
            ].get(
                "content",
                ""
            )

        else:

            text = str(result)

        parsed = json.loads(
            text
        )

        return parsed

    except Exception:

        return fallback_decision(c)


# =========================================================
# 🎯 MAIN ENTRY
# =========================================================

async def decide_action(

    c,

    world,

    perception,

    memories
):

    # =====================================
    # CACHE REUSE
    # =====================================

    recent = get_recent_decision(
        c
    )

    if (

        recent

        and

        not should_use_llm(c)
    ):

        return recent

    # =====================================
    # LLM OR FALLBACK
    # =====================================

    if should_use_llm(c):

        decision = await llm_decision(

            c,

            world,

            perception,

            memories
        )

    else:

        decision = fallback_decision(
            c
        )

    # =====================================
    # CACHE
    # =====================================

    set_recent_decision(

        c,

        decision
    )

    return decision