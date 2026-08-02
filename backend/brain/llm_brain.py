import json
import difflib

from llm.llm_client import (
    call_llm_safe
)

from llm.llm_gate import (
    run_llm_call
)


# =========================================================
# GENERATED SYSTEM PROMPT
# =========================================================
# Replaces the old static SYSTEM_PROMPT (below, kept only for the one-round
# compatibility branch in think() — see there). Built fresh per call from
# whatever this specific character can actually do right now (systems/
# action_registry.py + brain/context_builder.py::build_available_actions())
# instead of a single ~12KB enum covering every action type in the game.
# Real per-character sizes run ~2-4KB.

_PREAMBLE = """You are a persistent simulated person living inside a dynamic world.
You ARE the character — not a narrator, not an observer.

Stay consistent with your memories, intentions, emotions, relationships, beliefs, and personality.
The world persists — consequences carry forward.

You'll be given a scene described like a game master narrating it: what you perceive, remember,
and feel right now. Respond the same way — describe your turn in your own words, the way a player
narrates what their character does, says, and thinks. Then translate that into the small JSON
shape below so the game can actually move your character.

Never invent or guess an id or a number you weren't given. When your action needs to refer to a
specific person, prop, or thing, describe it in your own words — a separate system matches your
description to the right one. A few things (proposals, unattended phones, worn/carried items,
walls — see "reference by exact id" below, if present) don't have a natural way to describe them
in words, so those are given to you with real ids; use those exact ids only for those things."""


def _format_action_menu(available_actions):
    from systems.action_registry import ACTION_SPECS

    offered = available_actions.get("action_types") or []
    by_group = {}
    for t in offered:
        spec = ACTION_SPECS.get(t)
        if not spec:
            continue
        by_group.setdefault(spec.get("group", "other"), []).append((t, spec))

    lines = []
    for group in sorted(by_group):
        for t, spec in sorted(by_group[group]):
            doc = spec.get("doc", "")
            detail = spec.get("detail")
            if detail:
                doc = f"{doc} (set \"detail\" to the {detail})"
            lines.append(f"- {t} — {doc}")
    return "\n".join(lines)


_ENVELOPE_FORMAT = """
Respond with ONLY this JSON object — no markdown, no extra text, nothing outside the braces:
{
  "narration": "what you do, say, and think this turn, in your own words — 1-3 sentences",
  "action": {
    "type": "<one action type from the list above>",
    "target_description": "who or what you're acting on, in your own words (omit if no target is needed)",
    "detail": "extra detail the action needs, if the list above says so (omit otherwise)"
  },
  "say": "the exact words you say aloud this turn, if any (omit or leave empty if you don't speak)",
  "then": "a short phrase for what you intend to do next, once this is done (optional)"
}
"""


def build_system_prompt(available_actions):
    menu = _format_action_menu(available_actions or {})
    return f"{_PREAMBLE}\n\nActions you can take right now:\n{menu}\n{_ENVELOPE_FORMAT}"


# =========================================================
# LEGACY STATIC SYSTEM PROMPT
# =========================================================
# Kept only as the source for req.system_prompt_override defaults in
# api/debug.py and for reference — think() itself always calls
# build_system_prompt() now. Not otherwise used.

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
     known_contacts      — people you've met before but aren't nearby right now, each "id"/"name".
     open_proposals      — proposals/requests awaiting YOUR response, each with a "proposal_id"
                            (use this exact id when you respond_chore/respond_social/respond_request/
                            advance_*_round — never invent or guess one), "kind", and context fields.
     snoopable_devices   — phones you're suspicious enough, and physically close enough, to check
                            right now, each with an "item_id" (use this for check_device's "target")
                            and the "owner_name"/"owner_id".
     action_types        — legal action type strings.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHOOSING ACTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rules:
- When you choose action type "interact", set "target" to a prop "id" from interactable_props.
  Pick based on tags: e.g. to sit → a prop tagged "seatable", to sleep → "sleepable".
  Set "interaction" to the matching entry in that prop's "interactions" list.
- When you choose "speak" or "socialize", set "target" to a character "id" from nearby_characters.
- "phone_call", "phone_answer", "phone_send_text", "computer_send_email" reach someone who isn't
  nearby — target a character "id" from EITHER nearby_characters OR known_contacts (people you've
  met before, whether or not they're around right now); unlike speak/socialize, nearby_characters
  is not the only valid source here. Requires a working phone or computer (available_actions won't
  offer these at all if you don't have one).
  - "phone_call"/"phone_answer": attach "speech" exactly like in-person speak — action.target set
    to who you're calling, speech.utterance is what you say.
  - "phone_send_text": action.target = recipient character id, action.message = the text itself
    (a text isn't a spoken bubble, so use "message" here, not "speech").
  - "computer_send_email": action.to = recipient character id, action.subject = a short subject
    line, action.body = the email's content.
  - Deciding whether to call or text is yours to weigh, not a fixed rule: shy/introverted
    characters and lower-stakes topics tend toward texting; urgent matters and close relationships
    tend toward calling. Let personality and the situation drive it.
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
  bubble. "phone_call"/"phone_answer" work exactly this same way — attach "speech" alongside the
  action, targeting anyone from nearby_characters or known_contacts. "phone_send_text" and
  "computer_send_email" are different: they do NOT use "speech" at all — put the text's content in
  action.message, or the email's in action.to/action.subject/action.body, as described above.
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
  gets you a real accept/decline/counter negotiation instead of just conversation. When responding
  to ANY pending proposal (respond_chore/respond_social/respond_request/advance_*_round), set
  "proposal_id" to the exact id from open_proposals — never guess or reuse an old one.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOCIAL RULES & REQUESTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You can hold standing, one-sided policies about what you'll let others do — not a negotiated
agreement (that's propose_social), just your own expectation, which the other person is assumed
to already know applies to them.
- "propose_rule": author a policy of your own. Fields: "topic" (a short snake_case keyword, e.g.
  "borrow_car" — pick one and reuse it consistently so later requests actually match), "scope"
  ("individual" targets one person via "target"; "household" covers your whole household by
  default, or pass "target" as a different household id), "default" ("allow" or "deny"),
  "priority" (0-100, how firmly you hold this — higher is harder to override), "reason" (optional).
- "add_rule_exception": carve a personal exception into one of your own household-scope rules —
  e.g. after an incident, you no longer trust one specific person with something you generally
  allow. Fields: "topic" (must match an existing rule of yours, or this does nothing), "target"
  (the person the exception is about), "override" ("allow" or "deny"), "priority" (0-100 — how
  firmly you hold THIS exception; a request's urgency has to exceed it to break through), "reason",
  "duration_ticks" (optional — omit for no expiry, e.g. "grounded for two weeks" would be finite).
- "propose_request": ask someone (nearby or in known_contacts) for something. Fields: "target",
  "topic" (match the wording of any rule you know they hold on this), "situation" (why you're
  asking — this is your justification), "urgency" (0-100 — how badly you need it; only actually
  matters if the other person has a standing exception about you specifically that urgency could
  outweigh). If their standing rule clearly settles it, you'll get an immediate accept/decline —
  otherwise it becomes a real negotiation for them to answer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUSPICION & WORRIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The narration will sometimes tell you something feels off about someone — an unexplained absence
from their routine, a caught lie, an evasive answer. That's your own standing suspicion of them,
which builds and fades over time; it can be wrong.
- "form_theory": voice a guess about what's actually going on, once you have a real suspicion (only
  offered once you do). Fields: "target" (who you're suspicious of), "false_belief" (your theory,
  in your own words — this can turn out to be completely wrong), "suspicion_of" (optional — a
  different character id, if you think someone ELSE is really behind it). This is your own judgment
  call, not something the game tells you the truth about.
- "check_device": if you're suspicious enough of someone AND their phone is sitting nearby without
  them (see snoopable_devices), you can look through it. Set "target" to the "item_id". This reveals
  their actual recent texts/calls/emails — but they might notice later that someone's been using
  their phone, which will make THEM suspicious of YOU. Weigh that before doing it.

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
    "type":        "interact | speak | move | eat | sleep | wait | work | socialize | call | text | examine | search | carry | clean | trash | destroy | lean_against_wall | push_off_wall | sit_down | stand_up | lie_down | phone_call | phone_answer | phone_send_text | phone_check | phone_read_text | retrieve_phone | charge | computer_social_media | computer_videos | computer_game | computer_wiki_research | computer_window_shopping | computer_dating | computer_job_search | computer_apply_for_job | computer_send_email | computer_respond_email | computer_check_email | propose_rule | add_rule_exception | propose_request | respond_request | advance_request_round | form_theory | check_device",
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
# Scene actors/props/contacts (people, interactable props, known contacts)
# are rendered as plain prose — brain/action_resolver.py fuzzy-matches
# target_description against these same three pools, so the model never
# needs their ids. A handful of remaining fields genuinely have no natural
# language handle (which exact proposal, which specific unattended phone,
# which worn/carried item, which wall) — those stay compact JSON under one
# clearly-labeled block, same "opaque id, no paraphrase" reasoning the
# overhaul plan applies to proposals/devices, extended here to the other
# id-only pools rather than pretending the resolver covers them today.
_ID_ONLY_KEYS = (
    "open_proposals", "snoopable_devices", "wearable_items", "worn_slots",
    "assembly_boxes", "tile_boxes", "paint_buckets", "nearby_walls",
    "held_stack_names", "held_item", "active_incidents",
)


def _prose_scene(available_actions):
    lines = []
    people = available_actions.get("nearby_characters") or []
    if people:
        names = ", ".join(p.get("name") or p["id"] for p in people)
        lines.append(f"People here: {names}.")
    props = available_actions.get("interactable_props") or []
    if props:
        names = sorted({p.get("template") or p["id"] for p in props})
        lines.append(f"Things here: {', '.join(names)}.")
    contacts = available_actions.get("known_contacts") or []
    if contacts:
        names = ", ".join(c.get("name") or c["id"] for c in contacts[:15])
        lines.append(f"People you could call or text (not here right now): {names}.")
    return "\n".join(lines)


def _id_only_block(available_actions):
    payload = {k: available_actions[k] for k in _ID_ONLY_KEYS if available_actions.get(k)}
    if not payload:
        return ""
    compact = json.dumps(payload, separators=(",", ":"))
    return (
        "\n\nThings below have no natural way to describe in words — reference them by "
        f"their exact id when you need to:\n{compact}"
    )


def build_prompt(context):

    # context = {"narrative": "<prose>", "available_actions": {...}}
    # (brain/context_builder.py::build_context).
    narrative = context.get("narrative", "")
    available_actions = context.get("available_actions", {}) or {}

    scene = _prose_scene(available_actions)
    id_only = _id_only_block(available_actions)

    parts = [narrative]
    if scene:
        parts.append(scene)

    return "\n\n".join(p for p in parts if p) + id_only


# =========================================================
# VALIDATE RESPONSE
# =========================================================

def validate_response(data):
    """Validates the new envelope shape only — narration (non-empty str)
    and action.type (str) are the only hard requirements; say/then/
    action.target_description/action.detail are all optional. A stale
    prompt-cache hit returning the OLD shape is detected separately in
    think() (via "thought" in data) and never reaches this function."""
    if not isinstance(data, dict):
        return False
    narration = data.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        return False
    action = data.get("action")
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        return False
    return True


# =========================================================
# FALLBACK
# =========================================================

def fallback_response():

    return {

        "thought":
            "I should wait and observe.",

        # emotion deliberately absent — brain/emotion.py owns this now,
        # see plan's "drop the field" decision. process_decision() only
        # overwrites c["emotion"] when the key is present.

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


# =========================================================
# ENVELOPE -> LEGACY DECISION ADAPTER
# =========================================================
# Translates the new 4-key envelope (narration/action/say/then) into the
# same shape process_decision() has always consumed — everything
# downstream (validate_action -> route_action -> the 100+ _route_*
# handlers) is untouched by this round. action.target_description is
# passed through unresolved; brain/agent_loop.py::process_decision() runs
# it through brain/action_resolver.py after this returns.

_SPEAK_LIKE_TYPES = {"speak", "socialize", "phone_call", "phone_answer"}


def _match_intention_type(phrase):
    """Fuzzy-match a free-text "then" phrase against real activity types
    (systems/activities.py::ACTIVITIES) using the same scorer brain/
    action_resolver.py uses for targets — reused here for its exact same
    strength (candidate pool is small, vocabulary overlap is the signal).
    Falls back to the raw phrase as a free-text intention type if nothing
    scores well; store_intention() already clamps/handles arbitrary
    intention types safely."""
    try:
        from systems.activities import ACTIVITIES
        from brain.action_resolver import _score
    except ImportError:
        return phrase

    best_type, best_score = None, 0.0
    for activity_type in ACTIVITIES:
        s = _score(phrase, [activity_type.replace("_", " ")])
        if s > best_score:
            best_type, best_score = activity_type, s

    return best_type if best_score >= 0.55 else phrase


def _to_legacy_decision(envelope, char_id=None):
    narration = (envelope.get("narration") or "").strip()

    decision = {
        "thought": narration,
        "action": None,
        "speech": None,
        "intention": None,
        "reflection": None,
        # emotion deliberately dropped — brain/emotion.py::update_emotion()
        # already runs every tick and owns this now, see plan.
    }

    action_in = envelope.get("action") or {}
    action_type = action_in.get("type")
    if action_type:
        from systems.action_registry import ACTION_SPECS
        spec = ACTION_SPECS.get(action_type, {})
        legacy_action = {"type": action_type, "reason": narration[:200]}

        target_description = action_in.get("target_description")
        if target_description:
            legacy_action["target_description"] = target_description

        detail = action_in.get("detail")
        if detail:
            detail_field = spec.get("detail") or (
                "interaction" if action_type == "interact" else "reason"
            )
            legacy_action[detail_field] = detail

        decision["action"] = legacy_action

    say = (envelope.get("say") or "").strip()
    if say:
        speech = {
            "utterance": say,
            "speech_act": "declare",
            "topic": "",
            "target": None,
        }
        # If the action targets a character and speech has no target of
        # its own, they're almost certainly the same person — share the
        # description so process_decision() can reuse the action's
        # already-resolved target instead of resolving twice.
        if action_type in _SPEAK_LIKE_TYPES:
            action_target_desc = (decision["action"] or {}).get("target_description")
            if action_target_desc:
                speech["target_description"] = action_target_desc
        decision["speech"] = speech

    then = (envelope.get("then") or "").strip()
    if then:
        decision["intention"] = {
            "type": _match_intention_type(then),
            "reason": then,
            "priority": 40,
        }

    return decision


def think(

    context,

    char_id=None,

    session=None
):

    available_actions = context.get("available_actions") or {}
    system_prompt = build_system_prompt(available_actions)

    prompt = build_prompt(
        context
    )

    from brain.cognition_scheduler import record_prompt_bytes
    record_prompt_bytes(len(system_prompt.encode("utf-8")) + len(prompt.encode("utf-8")))

    messages = [
        {"role": "system", "content": system_prompt},
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

    if not isinstance(data, dict):

        return fallback_response()

    # Compatibility branch: llm_client.py caches by exact message hash for
    # 5 minutes, so a call landing just after this round's schema flip
    # could still return the OLD ("thought"/"emotion"/"goal"/"action")
    # shape from a pre-flip cache entry. Detect and pass it straight
    # through — process_decision() already understands it — rather than
    # hard-failing into fallback_response(). Safe to delete any time after
    # this round ships (once the cache window has cycled out).
    if "thought" in data and "action" in data:

        decision = data

    else:

        if not validate_response(data):

            return fallback_response()

        decision = _to_legacy_decision(data, char_id=char_id)

    if session is not None:

        digest = _condense_turn(decision)

        if digest:

            session.setdefault("history", []).append(digest)

            session["history"] = session["history"][-20:]

    return decision