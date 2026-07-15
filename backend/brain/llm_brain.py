import json

from llm.llm_client import (
    call_llm_safe
)

from llm.llm_gate import (
    run_llm_call
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
WHAT YOU'RE GIVEN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The user message has two parts:
1. Free-text narration — what you perceive, remember, and feel right now, written like a
   game master describing a scene. Treat it as ground truth about your situation, but it is
   prose, not data — never copy an id or number out of it.
2. A LEGAL_MOVES JSON block — the ONLY source of real ids you may reference:
     interactable_props  — props you can see right now, each with an "id", "tags", "interactions".
     nearby_characters   — people nearby, each with an "id" and "name".
     action_types        — legal action type strings.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHOOSING ACTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
- "push_off_wall": stand back up from leaning. Only valid when posture.current == "leaning_wall".
- "sit_down": sit on a nearby seat prop (target the prop id). Sets posture to sitting_seat.
- "stand_up": stand up from sitting or lying.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPEECH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Populate "speech.utterance" whenever you speak or think out loud. Set "speech.target" to a
  character id from LEGAL_MOVES when you're speaking to someone specific — this actually threads
  your words into a real conversation with them (history, tone, relationship effects), not just a
  bubble.
- If a conversation turn is active, strongly prioritize replying naturally.
- Speech should be emotionally honest — characters may lie, deflect, ramble, or ask questions.
- Keep utterances short (1-3 sentences). They appear as speech bubbles above your head.
- "speech_act" genuinely shapes what happens, so pick the one that actually matches: compliment,
  flirt, insult, challenge, vulnerable, confession, apology, supportive, dismissive, gossip, brag,
  lie, awkward_silence, joke, comfort, question, smalltalk, urgent_report — on top of the
  always-valid greet, ask, declare, argue, whisper. A flirt nudges attraction and can cause
  blushing; an insult raises tension and can damage trust; a lie gets recorded and can be caught
  later if it's ever contradicted by where you actually are. Use urgent_report to tell someone
  about a hostile act you personally witnessed (only works if you actually saw one) — it gives
  the listener the same real awareness you have, including the ability to intervene or call 911.
- "conversation_type" is optional — set it when you're starting a conversation or deliberately
  steering its shape: smalltalk, argument, negotiation, persuasion, competition, gossip. Leave it
  out to just continue naturally. It's yours to set or change any time, not locked in once picked.
  For a negotiation or persuasion attempt with a concrete ask (not just talk), use the
  propose_social/respond_social/advance_social_round actions when available in LEGAL_MOVES — that
  gets you a real accept/decline/counter negotiation instead of just conversation.

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
    "target":      "prop_id or character_id — MUST be a real id from LEGAL_MOVES",
    "interaction": "interaction name from interactable_props (for interact actions only)",
    "destination": {"x": 0, "y": 0},
    "reason":      "why you chose this"
  },
  "speech": {
    "target":            "character_id or null",
    "speech_act":        "greet | ask | declare | joke | comfort | argue | whisper | ...",
    "topic":             "topic keyword",
    "utterance":         "exact words you say aloud — shown as speech bubble",
    "conversation_type": "smalltalk | argument | negotiation | persuasion | competition | gossip | null"
  },
  "reflection": "brief reflection on recent events",
  "confidence": 0.0
}
"""


# =========================================================
# BUILD USER PROMPT
# =========================================================

def build_prompt(context):

    # context = {"narrative": "<prose>", "available_actions": {...}}
    # (brain/context_builder.py::build_context). The narrative is sent as
    # plain text — prose is denser per-token than the equivalent JSON (no
    # repeated keys/braces/quotes), which is what actually motivated the
    # older compact-JSON-only encoding this replaced. available_actions is
    # still compact JSON (no pretty-print whitespace, same reasoning as
    # before) — it's the one place literal ids appear, and those must stay
    # exact.
    narrative = context.get("narrative", "")

    legal_moves = json.dumps(

        context.get("available_actions", {}),

        separators=(",", ":")
    )

    return (

        f"{narrative}\n\n"

        f"LEGAL_MOVES (the only source of real ids — reference these "

        f"exactly, never invent an id):\n{legal_moves}"
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

def _condense_turn(data):
    """Reduce a parsed decision down to one short line for session history —
    see think()'s session handling below for why this can't just be the
    raw messages/response."""
    action = data.get("action") or {}
    speech = data.get("speech") or {}

    bits = []
    if data.get("thought"):
        bits.append(f'thought: "{data["thought"]}"')
    if action.get("type"):
        bits.append(f'did: {action["type"]}')
    if speech.get("utterance"):
        bits.append(f'said: "{speech["utterance"]}"')

    return " — ".join(bits) if bits else None


def think(

    context,

    char_id=None,

    session=None
):

    prompt = build_prompt(
        context
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    # Persistent per-character session (c["_llm_session"], see
    # schema_defaults.py). Deliberately NOT passed as call_llm_safe's own
    # `session=` kwarg — that mechanism re-embeds the entire messages list
    # (system prompt + full per-tick context) into rolling history on every
    # call, which would compound the exact token-cost problem the compact
    # JSON encoding above was already fighting. Instead, a short condensed
    # digest of the last few turns (thought/action/speech only, via
    # _condense_turn) is folded in as one extra message — real continuity
    # of "what did I just do" without repeating the full context each tick.
    history = (session or {}).get("history", [])
    if history:
        messages.insert(1, {
            "role": "system",
            "content": "Your recent turns:\n" + "\n".join(history[-6:]),
        })

    # call_llm_safe is async; think() runs synchronously inside a
    # ThreadPoolExecutor worker thread (via _run_agent), a plain OS thread
    # with no pre-existing event loop. run_llm_call() hands the coroutine
    # off to llm_gate.py's single shared event-loop thread and blocks here
    # until it completes — this is what actually bounds how many characters'
    # LLM calls are in flight to Ollama at once (OLLAMA_MAX_CONCURRENCY),
    # instead of every agent worker thread hitting Ollama independently.
    # char_id lets call_llm log this prompt/response into the per-character
    # ring buffer (llm_client.py::_PROMPT_LOG), which the World Editor's
    # Inspector reads via GET /debug/prompt-log/{char_id} when a character
    # is selected — without it, that log only ever gets populated by the
    # manual /debug/prompt-send tool, never by real gameplay decisions.
    raw = run_llm_call(
        call_llm_safe(messages, char_id=char_id)
    )

    try:

        data = json.loads(raw)

    except Exception:

        return fallback_response()

    if not validate_response(data):

        return fallback_response()

    if session is not None:

        digest = _condense_turn(data)

        if digest:

            session.setdefault("history", []).append(digest)

            session["history"] = session["history"][-20:]

    return data