import json

from llm.llm_client import (
    call_llm_safe
)


# =========================================================
# GENERATE SOCIAL INTERPRETATION
# =========================================================

async def generate_social_interpretation(

    observer,

    target,

    context
):

    session = observer.setdefault(

        "llm_session",

        {

            "history": []
        }
    )

    observer_traits = observer.get(
        "traits",
        []
    )

    observer_emotion = observer.get(
        "emotion"
    )

    target_traits = target.get(
        "traits",
        []
    )

    existing_model = context.get(
        "existing_model",
        {}
    )

    observations = context.get(
        "observations",
        []
    )

    baseline_traits = context.get(
        "baseline_traits",
        []
    )

    summary = context.get(
        "summary",
        ""
    )

    prompt = f"""
You are simulating a person's SUBJECTIVE impression of another person.

IMPORTANT:
- This is NOT objective truth.
- People are biased.
- People project emotions.
- People misinterpret behavior.
- People form emotional narratives.
- Different people may perceive the same person differently.

Observer:
Name: {observer.get("name")}
Traits: {observer_traits}
Emotion: {observer_emotion}

Target:
Name: {target.get("name")}
Traits: {target_traits}

Existing impression:
{json.dumps(existing_model, ensure_ascii=False)}

Observed behaviors:
{json.dumps(observations[-8:], ensure_ascii=False)}

Baseline interpretation:
Traits: {baseline_traits}
Summary: {summary}

Generate:
- a revised subjective summary
- perceived personality traits
- emotional interpretation shifts

Return STRICT JSON only.

Schema:

{{
    "summary": "...",

    "perceived_traits": [

        "..."
    ],

    "trust_shift": 0,

    "respect_shift": 0,

    "fear_shift": 0,

    "attraction_shift": 0
}}
"""

    messages = [

        {

            "role": "system",

            "content":

                "Return STRICT JSON only."
        },

        {

            "role": "user",

            "content": prompt
        }
    ]

    result = await call_llm_safe(

        messages,

        session=session
    )

    if result.get("error"):

        return None

    text = result

    if isinstance(result, dict):

        text = result.get(
            "text",
            ""
        )

    try:

        data = json.loads(text)

    except Exception:

        return None

    return data