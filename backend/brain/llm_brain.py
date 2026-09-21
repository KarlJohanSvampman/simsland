import json
import difflib
import re

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

# Per the user's explicit ask ("bare minimum D&D style, no more than a
# tweet"): this used to be a ~2KB, five-paragraph preamble explaining the
# same handful of rules at length. A GM's actual table-talk is this
# short -- the model doesn't need paragraphs to know not to eat a
# bookshelf.
_PREAMBLE = """You're a real person in a life sim, not a narrator. Narrate your turn in 1-2 short sentences, in character.
Describe targets in your own words, never invent an id. Only use things for what they're actually for."""


def _render_action_lines(offered, specs):
    """Kept for list_available_actions' fuller, on-demand listing
    (action_router.py::_route_list_available_actions) -- doc strings are
    only worth the tokens there, once, when a character actually asks
    what else they can do. The default per-tick menu (_format_action_menu
    below) never shows this."""
    by_group = {}
    for t in offered:
        spec = specs.get(t)
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
    return lines


def _format_action_menu(available_actions):
    """Per the user's explicit ask ("bare minimum, no descriptions"):
    just the core action names, comma-separated -- no per-action doc
    strings at all in the default per-tick prompt (that was the single
    biggest chunk of every prompt's size). Everything else stays
    reachable via list_available_actions exactly as before, which still
    returns the fuller described listing on demand."""
    from systems.action_registry import ACTION_SPECS

    offered = available_actions.get("action_types") or []
    core = sorted(t for t in offered if ACTION_SPECS.get(t, {}).get("group") == "core")

    extra_count = sum(1 for t in offered if ACTION_SPECS.get(t, {}).get("group") != "core")
    names = list(core)
    if extra_count:
        names.append(f"list_available_actions (+{extra_count} more)")
    return ", ".join(names)


# Per the user's explicit ask: replaces the old strict-JSON envelope with
# a compact, line-based reply shape -- a screenplay/script format an LLM
# already has heavy prior exposure to, without JSON's brace/quote/escape
# overhead. Parsed by _parse_compact_envelope() below into the exact same
# {"narration", "action", "say", "then"} shape the JSON envelope used to
# produce, so _to_legacy_decision() and everything downstream of it
# (action_router.py, process_decision, ...) needed zero changes.
_ENVELOPE_FORMAT = """
Reply in EXACTLY this shape, one line each. Skip a line entirely if it doesn't apply.
<what you do, ONLY if it's worth describing -- skip this line for a routine action, don't narrate every single move>
ACTION: <type> | <target, in your own words> | <extra detail, if needed>
SAY: <exact words, REQUIRED whenever your action is speak/socialize/phone_call/phone_answer -- never leave this blank if you're talking to someone>
THEN: <short next intention>
"""


def build_system_prompt(available_actions):
    menu = _format_action_menu(available_actions or {})
    return f"{_PREAMBLE}\n\nActions: {menu}\n{_ENVELOPE_FORMAT}"


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
  - "contact_business": target a business "id" from known_businesses, set "reason" to what you're
    calling about (a late delivery, a complaint, a general question). You do NOT know the
    business's hours in advance -- if they're closed, your message just gets left for them and
    they'll get back to you later, not right away.
  - "book_appointment": same targeting as contact_business, but only for a business whose
    business_kind is "service" (doctor, lawyer, therapist, ...) -- set "reason" to one of that
    business's reason_options if it has any. Only resolves to a confirmed appointment if you
    happen to call during their phone hours; otherwise it's left as a request, same as
    contact_business.
- When you choose "move", set "target" to a prop id or character id you want to approach.
- "jog_to" and "sneak_to" work exactly like "move" (same "target" field) but change your pace: jog_to when you're in a hurry (running late, an urgent need), sneak_to when you're deliberately moving quietly and trying not to be noticed (slipping out, avoiding someone without confronting them). Use plain "move" otherwise.
- When you choose "eat" or "sleep", set "target" to a prop id tagged "eatable" or "sleepable".
- If no suitable prop exists for your intended action, choose "wait" instead.
- If you're waiting on something specific rather than just idling (a person to show up, a business to call back, a delivery), set "wait"'s "waiting_for" field: {"kind": "person"|"business"|"delivery", "ref": <character id, business key, or a short description>}. This arms a patience timer (shorter if you're stressed or impatient, longer if patient) that nudges you to follow up once it runs out — a plain "wait" with no waiting_for is just idling and has no timer.
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
  lie, awkward_silence, joke, guilt_trip, comfort, question, smalltalk, urgent_report — on top of
  the always-valid greet, ask, declare, argue, whisper. A flirt nudges attraction and can cause
  blushing; an insult raises tension and can damage trust; a lie gets recorded and can be caught
  later if it's ever contradicted by where you actually are. Use urgent_report to tell someone
  about a hostile act you personally witnessed (only works if you actually saw one) — it gives
  the listener the same real awareness you have, including the ability to intervene or call 911.
  compliment, flirt, joke, and guilt_trip are real attempts that can succeed or visibly flop
  depending on how stressed/prepared you are, and who you're targeting (systems/contested_checks.py) — don't assume it always lands.
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
    "type":        "interact | speak | move | eat | sleep | wait | work | socialize | call | text | examine | search | carry | clean | trash | destroy | lean_against_wall | push_off_wall | sit_down | stand_up | lie_down | phone_call | phone_answer | phone_send_text | phone_check | phone_read_text | retrieve_phone | charge | computer_social_media | computer_videos | computer_game | computer_wiki_research | computer_news | computer_window_shopping | computer_dating | computer_job_search | computer_apply_for_job | computer_send_email | computer_respond_email | computer_check_email | propose_rule | add_rule_exception | propose_request | respond_request | advance_request_round | form_theory | check_device",
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


# Per-category plain-language labels for describe_id_only() below -- one
# line per non-empty pool instead of a raw JSON dump. Kept in id_only's
# own vocabulary (still "reference by exact id" for anything you'd act
# on) so a character reading a look_around result can still target
# something precisely, just never has to see it as literal JSON.
_ID_ONLY_LABELS = {
    "open_proposals":    "Open proposals",
    "snoopable_devices": "Devices you could check",
    "wearable_items":    "Wearable items nearby",
    "worn_slots":        "What you're wearing",
    "assembly_boxes":    "Boxes of parts",
    "tile_boxes":        "Boxes of tiles",
    "paint_buckets":     "Paint buckets",
    "nearby_walls":      "Nearby walls",
    "held_stack_names":  "What's in your stack",
    "active_incidents":  "Things happening nearby",
}


def describe_id_only(available_actions):
    """Plain-language version of _id_only_block()'s payload -- the real
    content behind the new look_around action (action_router.py::
    _route_look_around) instead of a raw JSON dump. Still names each
    entry's exact id alongside its description so a subsequent action
    can target it precisely."""
    lines = []
    for key, label in _ID_ONLY_LABELS.items():
        items = available_actions.get(key) or []
        if not items:
            continue
        entries = []
        for it in items[:10]:
            if isinstance(it, dict):
                ident = it.get("id") or it.get("wall_id")
                desc = it.get("name") or it.get("template") or it.get("type") or it.get("material") or "item"
                entries.append(f"{desc} ({ident})" if ident else str(desc))
            else:
                entries.append(str(it))
        lines.append(f"{label}: {'; '.join(entries)}.")

    held = available_actions.get("held_item")
    if held:
        if isinstance(held, dict):
            lines.append(f"You're holding: {held.get('name') or held.get('template') or held.get('id')}.")
        else:
            lines.append(f"You're holding: {held}.")

    return "\n".join(lines)


def build_prompt(context):

    # context = {"narrative": "<prose>", "available_actions": {...},
    # "environment_scan": {...} | None} (brain/context_builder.py::
    # build_context()).
    narrative = context.get("narrative", "")
    available_actions = context.get("available_actions", {}) or {}

    scene = _prose_scene(available_actions)

    parts = [narrative]
    if scene:
        parts.append(scene)

    # Per the user's ask: don't dump the id-only pools (walls, devices,
    # proposals, ...) into every single prompt as raw JSON. Only surface
    # them once the character has actually chosen to look_around --
    # environment_scan is that cached, already-prose result (set by
    # action_router.py::_route_look_around, carried in context by
    # context_builder.py::build_context()). Absent that, a short one-line
    # nudge is all that's sent, so the model knows more detail exists
    # without being handed it unasked.
    scan = context.get("environment_scan")
    if scan and scan.get("text"):
        parts.append(f"What you took stock of when you last looked around:\n{scan['text']}")
    if scan and scan.get("focused"):
        parts.append(scan["focused"])
    if not (scan and scan.get("text")) and any(available_actions.get(k) for k in _ID_ONLY_KEYS):
        parts.append("There are some things nearby you haven't looked closely at — look_around to take stock, or focus on something specific you already know about.")

    # Cached result of list_available_actions (action_router.py::
    # _route_list_available_actions) -- the fuller, non-core action menu,
    # already grouped and grounded against whatever's actually nearby.
    # Same "cache until refreshed" shape as environment_scan above.
    menu_cache = context.get("action_menu_cache")
    if menu_cache and menu_cache.get("text"):
        parts.append(f"Everything else you can currently do:\n{menu_cache['text']}")

    return "\n\n".join(p for p in parts if p)


# =========================================================
# PARSE COMPACT RESPONSE
# =========================================================
# Mirrors _ENVELOPE_FORMAT above -- one ACTION: line is the only hard
# requirement; everything before it is narration, SAY:/THEN: are each
# optional. Tolerant of stray whitespace/casing and an accidental
# markdown code fence, since this is free-text the model is producing,
# not a real grammar.

_ACTION_LINE_RE = re.compile(r'(?im)^[ \t>*_-]*ACTION[ \t]*:[ \t]*(.+)$')
_SAY_LINE_RE    = re.compile(r'(?im)^[ \t>*_-]*SAY[ \t]*:[ \t]*(.*)$')
_THEN_LINE_RE   = re.compile(r'(?im)^[ \t>*_-]*THEN[ \t]*:[ \t]*(.*)$')
_CODE_FENCE_RE  = re.compile(r'^```[a-zA-Z]*\n?|\n?```$')


def _parse_compact_envelope(raw):
    """Parses _ENVELOPE_FORMAT's line-based reply into the same
    {"narration", "action": {"type","target_description","detail"},
    "say", "then"} shape the old JSON envelope produced -- only the wire
    format changed, _to_legacy_decision() below is untouched. Returns
    None if no ACTION: line is found at all (not this format -- think()
    falls back to trying strict JSON next, then fallback_response())."""
    if not isinstance(raw, str):
        return None
    text = _CODE_FENCE_RE.sub("", raw.strip()).strip()

    action_match = _ACTION_LINE_RE.search(text)
    if not action_match:
        return None

    narration = text[:action_match.start()].strip()
    action_line = action_match.group(1).strip()

    say_match = _SAY_LINE_RE.search(text)
    then_match = _THEN_LINE_RE.search(text)

    parts = [p.strip() for p in action_line.split("|")]
    action_type = (parts[0] if parts else "").lower().replace(" ", "_")

    return {
        "narration": narration,
        "action": {
            "type": action_type,
            "target_description": parts[1] if len(parts) > 1 and parts[1] else "",
            "detail": parts[2] if len(parts) > 2 and parts[2] else "",
        },
        "say": say_match.group(1).strip() if say_match else "",
        "then": then_match.group(1).strip() if then_match else "",
    }


# =========================================================
# VALIDATE RESPONSE
# =========================================================

def validate_response(data):
    """Validates the new envelope shape only — action.type (non-empty
    str) is the only hard requirement. Per the user's explicit ask
    ("cheap pick, rich talk only when needed"): narration used to be
    required, forcing 1-3 sentences of prose out of the model on every
    single routine action (move, wait, examine, ...) -- the dominant
    cost of a generation call is OUTPUT length, so that was paying full
    narration price on every tick regardless of whether anything was
    actually worth describing. Empty narration is now valid; think()
    fills in a short canned line from the action itself (see
    _canned_narration()) rather than leaving the character silent.
    say/then/action.target_description/action.detail all stay optional.
    A stale prompt-cache hit returning the OLD shape is detected
    separately in think() (via "thought" in data) and never reaches this
    function."""
    if not isinstance(data, dict):
        return False
    action = data.get("action")
    if not isinstance(action, dict) or not action.get("type"):
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


def _append_history(session, decision):
    """Confirmed live bug (player report: a character stuck examining the
    same bookshelf for real minutes straight): the last 6 turns were
    appended verbatim regardless of content, so a stuck loop showed up as
    6 near-identical "thought: ... — did: describe" lines fed straight
    back into the character's OWN next prompt as "recent memory" -- the
    model sees a repeating pattern and, unsurprisingly, continues it,
    actively reinforcing the exact loop this history was meant to give
    useful continuity against. Collapses a run of the SAME action
    type+target into one entry with a growing repeat count instead --
    see _render_history_entry() below for how that reads to the model."""
    digest = _condense_turn(decision)
    if not digest:
        return

    action = decision.get("action") or {}
    key = (action.get("type"), action.get("target_description") or action.get("target"))

    history = session.setdefault("history", [])
    last = history[-1] if history else None
    if isinstance(last, dict) and last.get("_key") == key:
        last["count"] = last.get("count", 1) + 1
        last["text"] = digest
    else:
        history.append({"_key": key, "count": 1, "text": digest})
    session["history"] = history[-20:]


def _render_history_entry(h):
    """A history entry is either a plain string (an older session
    predating _append_history()'s collapsing, or one that's never
    repeated) or the {"text","count",...} shape above. Once count > 1,
    the repeat itself becomes part of the text -- a real signal to try
    something else, not just N near-identical lines diluting the same
    signal into invisibility."""
    if isinstance(h, str):
        return h
    text = h.get("text", "")
    count = h.get("count", 1)
    return f"{text} (×{count} in a row now -- try something different)" if count > 1 else text


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

# Per the user's explicit ask ("cheap pick, rich talk only when needed"):
# narration is now optional (validate_response no longer requires it) --
# a routine action the model chose not to narrate gets a flat, generic
# line synthesized here instead of an empty "thought", so the character
# still has SOMETHING for their own history digest / UI display. Not
# meant to carry personality -- that budget is spent on speech instead
# (see _fill_missing_speech()), which is the one place this codebase's
# own "make it feel alive" ask actually shows up to a player.
_CANNED_NARRATION = {
    "move": "I head toward {target}.",
    "jog_to": "I hurry toward {target}.",
    "sneak_to": "I quietly slip toward {target}.",
    "examine": "I take a closer look at {target}.",
    "describe": "I look around.",
    "search": "I search {target}.",
    "eat": "I eat {target}.",
    "sleep": "I settle in to sleep.",
    "wait": "I wait.",
    "work": "I get to work.",
    "interact": "I use {target}.",
    "carry": "I pick up {target}.",
    "clean": "I clean {target}.",
    "recall": "I think back for a moment.",
    "sit_down": "I sit down.",
    "stand_up": "I stand up.",
    "lean_against_wall": "I lean against the wall.",
    "push_off_wall": "I stand back up.",
    "speak": "I turn to speak with {target}.",
    "socialize": "I strike up a casual conversation with {target}.",
    "phone_call": "I call {target}.",
    "phone_answer": "I answer the phone.",
}
_CANNED_NARRATION_DEFAULT = "I get on with it."


def _canned_narration(action_type, target):
    template = _CANNED_NARRATION.get(action_type, _CANNED_NARRATION_DEFAULT)
    if "{target}" in template:
        return template.format(target=target or "it")
    return template


def _match_intention_type(phrase):
    """Fuzzy-match a free-text "then" phrase against real activity types
    (systems/activities.py::ACTIVITIES) using the same scorer brain/
    action_resolver.py uses for targets — reused here for its exact same
    strength (candidate pool is small, vocabulary overlap is the signal).

    Returns None when nothing scores well -- confirmed live bug: this
    used to fall back to the raw phrase as the intention's own "type".
    Since every slightly-differently-worded "then" phrase is a distinct
    string, none of them ever match an existing entry to get replaced
    (brain/intentions.py::add_intention()'s dedup-by-type never fires),
    and resolve_strategy() can never resolve a sentence-shaped type to a
    real activity either -- so these just accumulate as permanent dead
    weight. store_intention()'s last-10 cap then silently evicted real,
    resolvable intentions (drink, expectation:make_dinner, ...) to make
    room, which is why a character could sit next to a working sink at
    46% hydration repeating "let me find a phone to call for help" turn
    after turn instead of just drinking -- its real "drink" intention had
    been pushed out of the window entirely."""
    try:
        from systems.activities import ACTIVITIES
        from brain.action_resolver import _score
    except ImportError:
        return None

    best_type, best_score = None, 0.0
    for activity_type in ACTIVITIES:
        s = _score(phrase, [activity_type.replace("_", " ")])
        if s > best_score:
            best_type, best_score = activity_type, s

    return best_type if best_score >= 0.55 else None


# Confirmed live bug (real player report + screenshot): the model is
# told to put spoken words in the dedicated "say" field, separate from
# "narration" -- but doesn't always comply, sometimes folding a quoted
# line of dialogue into narration instead and leaving "say" empty
# (e.g. narration: "I smile and respond to Paul, 'Not bad, just getting
# ready for work...'"). That meant the character never got a real white
# speech bubble for what was unmistakably them talking out loud -- only
# the blue narration/thought bubble showed, reading as if they'd only
# thought it. This is a deterministic best-effort fallback for exactly
# that case, never overriding a real "say" value when one is present.
#
# Confirmed live bug in an EARLIER version of this fallback: a bare
# `'(.+)'` (greedy, to survive an apostrophe inside the quoted line)
# matched between two totally unrelated apostrophes -- e.g. "I'm
# feeling overwhelmed... before addressing Paul Wright's question" --
# manufacturing fake dialogue out of a narration that never quoted
# anyone. Anchoring the quote to a real speech verb immediately before
# it (say/respond/tell/ask/...) is what actually distinguishes "this is
# a quotation" from "this narration happens to contain two apostrophes
# that aren't a matched pair." Double quotes are tried first since they
# can't collide with a contraction's/possessive's apostrophe at all.
_SPEECH_CUE = (
    r"\b(?:say|says|said|saying"
    r"|respond|responds|responded|responding"
    r"|repl(?:y|ies|ied|ying)"
    r"|tell|tells|telling|told"
    r"|ask|asks|asked|asking"
    r"|whisper|whispers|whispered|whispering"
    r"|shout|shouts|shouted|shouting"
    r"|exclaim|exclaims|exclaimed|exclaiming"
    r"|mutter|mutters|muttered|muttering"
    r"|answer|answers|answered|answering)\b"
)
# Confirmed live bug in the FIRST version of this cue-anchor: "respond
# to Paul Wright's question, but..." still matched, because a speech
# verb followed by ANY quote-type character within range is not enough
# -- "Wright's" own possessive apostrophe sits right there too, and
# nothing distinguished it from a real opening quote. A real quotation
# is always punctuated as "<verb> ..., '...'" or "<verb> ...: '...'" in
# English -- requiring a literal comma/colon immediately before the
# quote mark (with the character class still banning any stray quote
# char in between) is what actually rules out a mid-sentence possessive/
# contraction sitting between the verb and a real closing quote later on.
_QUOTED_SPEECH_PATTERNS = (
    re.compile(_SPEECH_CUE + r"[^\"'\n]{0,30}[,:]\s*\"([^\"]+)\"", re.IGNORECASE),
    re.compile(_SPEECH_CUE + r"[^\"'\n]{0,30}[,:]\s*'(.+)'", re.IGNORECASE),
)


def _extract_quoted_speech(narration):
    for pattern in _QUOTED_SPEECH_PATTERNS:
        m = pattern.search(narration)
        if m:
            quoted = m.group(1).strip()
            if quoted:
                return quoted
    return None


# Confirmed live bug, deeper than the display glitch above: even once an
# utterance is correctly extracted, a speech dict with no "target" never
# gets threaded into a real conversation at all -- action_router.py::
# apply_speech()'s entire conversation block (get_or_create_conversation,
# add_message, waking the LISTENER specifically, scheduling their reply)
# is gated on a resolved target character. Narration that clearly names
# who's being spoken to ("I ... respond to Paul, '...'") carries that
# information, but nothing extracted it -- speech["target_description"]
# only ever got set by borrowing the ACTION's own target when the action
# type happened to also be speak-like (_SPEAK_LIKE_TYPES), which a
# narrated-mid-other-activity reply often isn't. This is what actually
# produced "the reply never reaches the other character and the
# conversation doesn't continue" -- not just a display issue.
#
# This is a best-effort SIGNAL, not the only fix -- apply_speech() itself
# (systems/action_router.py) now also falls back to whichever real
# co-present character is nearest when no target resolves at all, per
# the user's own framing: you don't need to know someone's name for your
# words to reach whoever's standing right there. This regex still adds
# real value on top of that when multiple people are around and the
# narration names a specific one of them. Case-insensitively matches the
# same speech-cue verbs as the quote extractor above, but the captured
# name itself stays case-SENSITIVE (must start with a capital letter) so
# "responds to him"/"tells her" don't get misread as a literal name
# called "Him"/"Her".
_SPEECH_TARGET_PATTERN = re.compile(
    r"(?i:" + _SPEECH_CUE + r"\s+(?:to\s+)?)([A-Z][a-zA-Z'-]{1,30})\b"
)


def _extract_speech_target_name(narration):
    m = _SPEECH_TARGET_PATTERN.search(narration)
    if m:
        return m.group(1)
    return None


# Confirmed live gap (player report): narration very often describes a
# real conversational beat -- "I decide to address his question", "I ask
# him to elaborate" -- without the envelope's own "say" field being set
# and without an anchored quote for _extract_quoted_speech() to find (by
# design -- that extractor deliberately only fires on a real, punctuated
# quotation, see the comment above it). The result was a silent
# character: something was clearly said, but no actual line of dialogue
# ever reached apply_speech()/the speech bubble. This is a looser
# detector than _SPEECH_CUE -- it also catches the bare nouns
# "question"/"response" the user pointed out, not just the verb forms --
# used only to decide whether a follow-up call is worth making, never to
# extract text itself.
_SPEECH_IMPLIED_PATTERN = re.compile(
    r"\b(?:question|questions|answer|answers|response|responses"
    r"|ask|asks|asked|asking"
    r"|repl(?:y|ies|ied|ying)"
    r"|respond|responds|responded|responding)\b",
    re.IGNORECASE,
)


def _fill_missing_speech(narration, char_id, priority):
    """One small, focused follow-up call -- NOT the full per-tick
    context/system prompt again, just enough to ask "what did you
    actually say." A nice-to-have enrichment, never load-bearing: any
    failure (timeout, malformed reply, preempted by a higher-priority
    call) just leaves the character silent this tick, exactly like
    before this existed. Returns an utterance string, or None."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are voicing one character's spoken line in a life "
                "simulation, in the moment described below. Reply with "
                "ONLY the exact words they say out loud right now, in "
                "natural first-person spoken English -- no quotation "
                "marks, no narration, no stage directions, no labels. "
                "If they would not actually speak out loud in this "
                "moment, reply with exactly: NONE"
            ),
        },
        {"role": "user", "content": narration[:500]},
    ]
    try:
        raw = run_llm_call(
            call_llm_safe(messages, char_id=char_id),
            priority=priority,
        )
    except Exception:
        return None
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip('"').strip("'").strip()
    if not text or text.upper().startswith("NONE"):
        return None
    return text


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
    if not say:
        say = _extract_quoted_speech(narration) or ""
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

        # Still nothing to go on (a reply narrated mid-other-activity,
        # whose action type isn't speak-like at all) -- try pulling a
        # named recipient straight out of the narration itself. Real
        # resolution to a character id, and the nearest-co-present
        # fallback when even this finds nobody, both happen in
        # process_decision()/apply_speech() -- this only supplies the
        # candidate name to resolve.
        if not speech.get("target_description"):
            target_name = _extract_speech_target_name(narration)
            if target_name:
                speech["target_description"] = target_name

        decision["speech"] = speech

    then = (envelope.get("then") or "").strip()
    if then:
        matched_type = _match_intention_type(then)
        if matched_type:
            decision["intention"] = {
                "type": matched_type,
                "reason": then,
                "priority": 40,
            }

    return decision


def think(

    context,

    char_id=None,

    session=None,

    priority=None
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
        rendered = [_render_history_entry(h) for h in history[-6:]]
        messages.insert(1, {
            "role": "system",
            "content": "Your recent turns:\n" + "\n".join(rendered),
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
    from llm.llm_gate import PRIORITY_NORMAL
    raw = run_llm_call(
        call_llm_safe(messages, char_id=char_id),
        priority=PRIORITY_NORMAL if priority is None else priority,
    )

    # Compact line-based reply (see _ENVELOPE_FORMAT) is the primary
    # format now. Falls back to strict JSON for a stale llm_client.py
    # cache hit (5-minute window) from just before this round's format
    # flip, or a model that reverts to JSON out of habit -- either way,
    # _to_legacy_decision()/process_decision() below never see the
    # difference, only this parsing step does.
    envelope = _parse_compact_envelope(raw)

    if envelope is not None:

        if not validate_response(envelope):

            return fallback_response()

        decision = _to_legacy_decision(envelope, char_id=char_id)

    else:

        try:

            data = json.loads(raw)

        except Exception:

            return fallback_response()

        if not isinstance(data, dict):

            return fallback_response()

        # Compatibility branch: the OLD ("thought"/"emotion"/"goal"/
        # "action") shape, from even further back. Detect and pass it
        # straight through — process_decision() already understands it.
        if "thought" in data and "action" in data:

            decision = data

        else:

            if not validate_response(data):

                return fallback_response()

            decision = _to_legacy_decision(data, char_id=char_id)

    # Fetch the actual words whenever they're missing -- two ways to get
    # here: (1) the narration clearly describes a conversational beat but
    # nothing captured a real line (original trigger), or (2) per the
    # user's explicit ask ("rich talk only when needed"), the CHOSEN
    # ACTION itself is speak-like -- the reliable signal now that
    # narration is optional and can't be counted on to even exist. Either
    # way this is the ONE place a routine decision is allowed a second
    # round-trip; every other action type stays a single call. Gated on
    # speech still being empty so a real "say"/quoted line already
    # resolved is never overridden.
    action_type = (decision.get("action") or {}).get("type")
    if not decision.get("speech"):
        narration_text = decision.get("thought") or ""
        target_description = (decision.get("action") or {}).get("target_description")
        speech_implied = narration_text and _SPEECH_IMPLIED_PATTERN.search(narration_text)
        if speech_implied or action_type in _SPEAK_LIKE_TYPES:
            # No real narration to hand the follow-up call as context when
            # it was skipped (the whole point of making it optional) --
            # a short synthesized prompt naming the target stands in.
            context_text = narration_text or (
                f"You decide to talk to {target_description}." if target_description
                else "You decide to say something."
            )
            utterance = _fill_missing_speech(
                context_text, char_id,
                PRIORITY_NORMAL if priority is None else priority,
            )
            if utterance:
                speech = {
                    "utterance": utterance,
                    "speech_act": "declare",
                    "topic": "",
                    "target": None,
                }
                target_name = target_description or _extract_speech_target_name(narration_text)
                if target_name:
                    speech["target_description"] = target_name
                decision["speech"] = speech

    # Per the user's explicit ask: narration is optional now (the model
    # was told to skip it for anything routine) -- fill in a flat canned
    # line from the action itself rather than leaving "thought" empty,
    # so history digests/UI display still have something to show.
    if not decision.get("thought") and action_type:
        target_description = (decision.get("action") or {}).get("target_description")
        decision["thought"] = _canned_narration(action_type, target_description)

    if session is not None:

        _append_history(session, decision)

    return decision