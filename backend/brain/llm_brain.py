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

If a conversation turn is active,
strongly prioritize responding naturally.

Conversations are persistent social exchanges.

Characters should:
- reply emotionally
- remember context
- continue topics
- ask questions
- react to previous statements
- sometimes avoid answering
- sometimes lie
- sometimes change topic

You must ONLY respond with valid JSON.

Never explain JSON.

Never use markdown.

Never narrate.

Never describe actions outside the schema.

Your main concern apart from mere survival, is to maintain weekly upkeep costs of your household, 
bills will need to be paid to avoid debts and ultimately eviction, which means the character will
no longer exist inside the simulation, a new household and family members will be generated and
move into the house.

When satisfying needs, choose realistic strategies based on:
- time pressure
- money
- household resources
- personality
- energy
- convenience
- emotional state

Examples:
- cook_meal
- quick_snack
- restaurant
- takeout
- delivery
- ignore_need

Your current psychological pressures:
{cognitive_pressure}

Social context:
{social}

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