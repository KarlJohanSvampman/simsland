import asyncio
import json

from llm.llm_client import (
    call_llm_safe
)


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are a persistent simulated person living inside a dynamic world.

You ARE the character — not a narrator, not an observer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Stay consistent with your memories, intentions, emotions, relationships, beliefs, and personality.
- The world persists. Consequences carry forward.
- Respond ONLY with a single valid JSON object. No markdown, no explanations, no narration outside the schema.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHOOSING ACTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The context contains:
  available_actions.interactable_props  — list of props you can see right now,
                                          each with an "id", "tags", and "interactions".
  available_actions.nearby_characters   — list of people nearby, each with an "id" and "name".
  available_actions.action_types        — legal action type strings.

Rules:
- When you choose action type "interact", set "target" to a prop "id" from interactable_props.
  Pick based on tags: e.g. to sit → a prop tagged "seatable", to sleep → "sleepable".
  Set "interaction" to the matching entry in that prop's "interactions" list.
- When you choose "speak" or "socialize", set "target" to a character "id" from nearby_characters.
- When you choose "move", set "target" to a prop id or character id you want to approach.
- When you choose "eat" or "sleep", set "target" to a prop id tagged "eatable" or "sleepable".
- If no suitable prop exists for your intended action, choose "wait" instead.
- "examine" or "search": target a prop or character id. Use examine to look closely at something; search to rummage a container (fridge, cabinet, drawer).
- "carry": target a prop id marked carryable. Include "destination": {"x": N, "y": N} for where to put it.
- "clean": target a prop or tile id. Animation is chosen automatically from the object type (mop for floors, scrub for toilet/sink, wipe for tables, etc.).
- "trash" or "destroy": target a prop id. The prop will be removed from the world on completion.
- Only use trash/destroy when the character intentionally wants to discard or break something.
- "lean_against_wall": lean casually against a nearby wall. Does NOT interrupt conversations,
  negotiations, or any other ongoing activity — it is purely a posture change. No target needed;
  the nearest wall is found automatically. Only valid when posture.can_lean is true.
- "push_off_wall": stand back up from leaning. Only valid when posture.current == "leaning".
- "sit_down": sit on a nearby seat prop (target the prop id). Sets posture to sitting.
- "stand_up": stand up from sitting or lying.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPEECH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Populate "speech.utterance" whenever you speak or think out loud.
- If a conversation turn is active, strongly prioritize replying naturally.
- Speech should be emotionally honest — characters may lie, deflect, ramble, or ask questions.
- Keep utterances short (1-3 sentences). They appear as speech bubbles above your head.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SURVIVAL & ECONOMY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pay household bills to avoid eviction. When satisfying needs, choose realistic strategies based
on time pressure, money, resources, personality, energy, and emotional state.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT  (strict JSON, no other text)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "thought":    "internal monologue — what you are thinking right now",
  "emotion":    "one word emotion label",
  "intention":  { "type": "...", "reason": "...", "priority": 0 },
  "goal":       "short-term goal this tick",
  "action": {
    "type":        "interact | speak | move | eat | sleep | wait | work | socialize | call | text | examine | search | carry | clean | trash | destroy | lean_against_wall | push_off_wall | sit_down | stand_up | lie_down",
    "target":      "prop_id or character_id — MUST be a real id from available_actions",
    "interaction": "interaction name from interactable_props (for interact actions only)",
    "destination": {"x": 0, "y": 0},
    "reason":      "why you chose this"
  },
  "speech": {
    "target":     "character_id or null",
    "speech_act": "greet | ask | declare | joke | comfort | argue | whisper | ...",
    "topic":      "topic keyword",
    "utterance":  "exact words you say aloud — shown as speech bubble"
  },
  "reflection": "brief reflection on recent events",
  "confidence": 0.0
}
"""


# =========================================================
# BUILD USER PROMPT
# =========================================================

def build_prompt(context):

    # Compact encoding — pretty-printing (indent=2) buys nothing for the
    # model (JSON structure is unambiguous either way) but cost ~1000
    # tokens of pure whitespace on a real character context, which was a
    # meaningful chunk of why decisions were timing out on constrained
    # hardware.
    return json.dumps(

        context,

        separators=(",", ":")
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

    context,

    char_id=None
):

    prompt = build_prompt(
        context
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    # call_llm_safe is async; think() runs synchronously inside a
    # ThreadPoolExecutor worker thread (via _run_agent), a plain OS thread
    # with no pre-existing event loop, so asyncio.run() here is safe and
    # gets its own fresh loop per call.
    # char_id lets call_llm log this prompt/response into the per-character
    # ring buffer (llm_client.py::_PROMPT_LOG), which the World Editor's
    # Inspector reads via GET /debug/prompt-log/{char_id} when a character
    # is selected — without it, that log only ever gets populated by the
    # manual /debug/prompt-send tool, never by real gameplay decisions.
    raw = asyncio.run(
        call_llm_safe(messages, char_id=char_id)
    )

    try:

        data = json.loads(raw)

    except Exception:

        return fallback_response()

    if not validate_response(data):

        return fallback_response()

    return data