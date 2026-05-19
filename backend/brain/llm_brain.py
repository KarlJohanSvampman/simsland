import json

from llm.llm_client import (
    call_llm_safe
)


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are controlling a persistent simulated person inside a living world.

You are NOT narrating a story.

You ARE the character.

Stay consistent with:
- memories
- intentions
- emotions
- relationships
- beliefs
- personality traits

The world is persistent and consequences matter.

You may:
- speak
- move
- interact
- call
- text
- work
- eat
- sleep
- wait
- socialize

You must ONLY respond with valid JSON.

Never explain JSON.

Never use markdown.

Never narrate.

Never describe actions outside the schema.

Output format:

{
  "thought": "...",

  "emotion": "...",

  "intention": {
    "type": "...",
    "reason": "...",
    "priority": 0-100
  },

  "goal": "...",

  "action": {
    "type": "...",
    "target": "...",
    "reason": "..."
  },

  "speech": {
    "target": "...",
    "speech_act": "...",
    "topic": "...",
    "utterance": "..."
  },

  "reflection": "...",

  "confidence": 0.0-1.0
}
"""


# =========================================================
# BUILD USER PROMPT
# =========================================================

def build_prompt(context):

    return json.dumps(

        context,

        indent=2
    )


# =========================================================
# VALIDATE RESPONSE
# =========================================================

def validate_response(data):

    required = [

        "thought",

        "emotion",

        "goal",

        "action"
    ]

    for r in required:

        if r not in data:
            return False

    return True


# =========================================================
# FALLBACK
# =========================================================

def fallback_response():

    return {

        "thought":
            "I should wait and observe.",

        "emotion":
            "neutral",

        "goal":
            "idle",

        "action": {

            "type":
                "wait",

            "target":
                None,

            "reason":
                "No valid action."
        },

        "speech": None,

        "reflection":
            "",

        "confidence":
            0.1
    }


# =========================================================
# MAIN THINK FUNCTION
# =========================================================

def think(

    context
):

    prompt = build_prompt(
        context
    )

    raw = call_llm_safe(

        SYSTEM_PROMPT,

        prompt
    )

    try:

        data = json.loads(raw)

    except Exception:

        return fallback_response()

    if not validate_response(data):

        return fallback_response()

    return data