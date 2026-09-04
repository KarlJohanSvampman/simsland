# =========================================================
# ACTION ROUTER
# Translates LLM action + speech output into world state
# changes. Called from agent_loop.process_decision.
# =========================================================

import time
import random

from systems.activities import get_phase_animation, get_clean_animation
from systems.navigation import plan_character_route
from systems.offgrid import send_offgrid
from core.tick_schedule import TICK_RATE_SECONDS


# =========================================================
# SPEECH BUBBLE DURATION (sim ticks)
# =========================================================

SPEECH_BUBBLE_TICKS = 8   # how many ticks the bubble stays visible


# =========================================================
# ANIMATION STATE MAP
# Maps action type → animation_state string used by frontend
# =========================================================

_ACTION_ANIMATION = {
    "interact":   "interact",
    "eat":        "eat",
    "sleep":      "sleep",
    "work":       "work",
    "socialize":  "talk",
    "speak":      "talk",
    "move":       "walk",
    "wait":       "idle",
    "call":       "phone",
    "text":       "phone",
}


# =========================================================
# APPLY SPEECH
# Stores utterance on the character so the frontend can
# display it as a speech bubble.
# =========================================================

def apply_speech(c, world, speech):
    """
    speech = {
        "target":      str | None,
        "speech_act":  str,   e.g. "greet", "ask", "declare"
        "topic":       str,
        "utterance":   str    -- the actual text to display
    }
    """
    if not speech:
        return

    utterance = speech.get("utterance", "").strip()
    if not utterance:
        return

    tick = world.get("tick", 0)
    speech_act = speech.get("speech_act", "speak")
    topic = speech.get("topic", "")
    target_id = speech.get("target")

    # Volume (see brain/perception.py's VOLUME_TIERS) -- explicit caller
    # value wins (e.g. a future hostile-action shout), otherwise inferred
    # from the same signals already tracked elsewhere: an "argument"
    # conversation_type on this message, or an active conflict between
    # these two parties already in its heated_argument/shouting_match
    # fight_stage (systems/conflict_pipeline.py). Plain conversation stays
    # "medium" (default speaking volume).
    volume = speech.get("volume")
    if not volume:
        if speech.get("conversation_type") == "argument":
            volume = "high"
        else:
            volume = "medium"
            if target_id:
                for conflict in world.get("conflicts", {}).values():
                    parties = conflict.get("parties", [])
                    if (c["id"] in parties and target_id in parties
                            and conflict.get("fight_stage") in ("heated_argument", "shouting_match")):
                        volume = "high"
                        break

    c["current_speech"] = {
        "utterance":      utterance,
        "speech_act":     speech_act,
        "topic":          topic,
        "target":         target_id,
        "volume":         volume,
        "expires_at_tick": tick + SPEECH_BUBBLE_TICKS,
    }

    # Store in conversation log too
    c.setdefault("speech_log", [])
    c["speech_log"].append({
        "tick":      tick,
        "utterance": utterance,
        "target":    target_id,
    })
    c["speech_log"] = c["speech_log"][-20:]   # keep last 20

    # =====================================================
    # THREAD INTO A REAL CONVERSATION
    # apply_speech() used to be a dead end — no conversations entry ever
    # got created here, so build_active_conversations()'s "it's your turn
    # to respond" context and conversations.py's whole tone/dynamics/
    # memory/observation machinery (add_message()) never fired for
    # LLM-driven speech, only for the (separately broken) templated
    # activity path. See the LLM-conversations plan for the full trace.
    # =====================================================
    listener = world.get("characters", {}).get(target_id) if target_id else None

    # Reachability -- only meaningful for a live call: a text/email always
    # "sends" and just sits unread, matching how those mediums really work,
    # but a call needs someone to actually answer. Previously apply_speech()
    # connected unconditionally regardless of the recipient's phone state
    # (phone_is_usable() already existed and gated the *caller's* own use at
    # _require_phone(), but was never consulted for the listener side) --
    # this is the answering-machine gate: no answer leaves a voicemail in
    # the recipient's inbox instead of threading a live conversation.
    medium = speech.get("medium", "in_person")
    if listener and medium == "call":
        from systems.personal_items import phone_is_usable
        if not phone_is_usable(listener):
            from systems.inbox import get_character_inbox, add_message as add_inbox_message
            add_inbox_message(
                get_character_inbox(listener), "voicemail", c["id"], target_id,
                utterance, tick, metadata={"topic": topic, "missed_call": True},
            )
            return

    if listener:

        from brain.conversations import get_or_create_conversation, add_message
        from systems.reactions import push_conversation_reaction
        from brain.relationships import apply_interaction
        from systems.conversation_analysis import analyze_message, should_schedule_reflection

        conv = get_or_create_conversation(
            world, [c["id"], target_id], topic=topic or "general",
            medium=speech.get("medium", "in_person"),
        )

        # Personal per-participant conversation goals (systems/
        # conversation_goals.py) -- assigned lazily/idempotently for
        # whichever side hasn't formed one yet, so both directions are
        # populated from the first exchange rather than only the speaker.
        from systems.conversation_goals import assign_conversation_goal, check_goal_trending
        assign_conversation_goal(c, world, conv, target_id)
        assign_conversation_goal(listener, world, conv, c["id"])

        # Optional LLM-set framing (argument, negotiation, persuasion, ...).
        # Simple overwrite, not a state machine — a conversation drifting
        # from small talk into an argument is realistic, and either
        # participant can steer it.
        conversation_type = speech.get("conversation_type")
        if conversation_type:
            conv["conversation_type"] = conversation_type

        add_message(
            world, conv, c["id"], utterance, speech_act,
            topic or conv.get("topic", "general"), tick
        )

        push_conversation_reaction(listener, speech_act, tick)

        apply_interaction(c, listener, speech_act)

        result = analyze_message(world, conv, c, listener, utterance, speech_act)

        # Is this trending toward the LISTENER's own goal for talking to
        # c? A sustained "no" from a not_interested participant retires
        # the conversation for them without spending a real LLM turn on
        # it -- see conversation_goals.py::check_goal_trending.
        check_goal_trending(conv, listener, topic or conv.get("topic", "general"))

        if should_schedule_reflection(result):
            listener.setdefault("pending_reflections", []).append({
                "type":           "conversation",
                "target_id":      c["id"],
                "reason":         speech_act,
                "scheduled_tick": tick + random.randint(50, 300),
                "observations":   result.get("observations", []),
            })

        # A real (non-generic) topic surfaced and the listener has no
        # opinion on it yet -- schedule an automatic, spontaneous
        # opinion-forming reflection (systems/reflection.py's
        # "form_opinion" kind), independent of the relationship-
        # significance gate above. See brain/opinions.py.
        topic_str = topic or conv.get("topic", "general")
        if topic_str not in ("general", "incidental") and topic_str not in listener.get("opinions", {}):
            listener.setdefault("pending_reflections", []).append({
                "type":           "form_opinion",
                "topic":          topic_str,
                "reason":         f"{c.get('name', 'Someone')} brought this up in conversation.",
                "scheduled_tick": tick + random.randint(20, 120),
            })

    # =====================================================
    # WAKE LISTENERS — see brain/cognition_scheduler.py. A directed line
    # wakes only its target; an untargeted/ambient line wakes up to 4
    # nearby people by visibility (capped so a shout in a crowded room
    # doesn't stampede everyone present into a simultaneous LLM call on a
    # 2-slot Ollama budget).
    #
    # Deliberately emit-only here, not a direct wake_character() call —
    # this runs inside the speaker's own agent worker thread, but the
    # listener(s) may be a different character concurrently being
    # processed by their own worker thread this same tick. Mutating
    # another character's cognition dict from off-thread would race;
    # routing through core/event_bus.py's emit() (thread-safe) + the
    # heard_speech subscription in core/event_handlers.py (applied at
    # flush(), main-thread-only, after all workers finish) avoids that.
    # =====================================================
    from core.event_bus import emit

    if listener:
        emit("heard_speech", {
            "listener_id": listener["id"], "speaker_id": c["id"],
            "speaker_name": c.get("name") or c["id"], "utterance": utterance,
        })
    else:
        nearby = (c.get("perception") or {}).get("visible_people", [])[:4]
        for entry in nearby:
            listener_id = entry.get("id")
            if not listener_id:
                continue
            emit("heard_speech", {
                "listener_id": listener_id, "speaker_id": c["id"],
                "speaker_name": c.get("name") or c["id"], "utterance": utterance,
            })


# =========================================================
# APPLY SPEECH TO GROUP
# A new, separate entry point for real 3+-participant conversations
# (e.g. a news-triggered debate -- see systems/reading_process.py) --
# apply_speech() above is left completely untouched, since every one of
# its downstream calls (get_or_create_conversation before this change,
# analyze_message, push_conversation_reaction, apply_interaction) is
# written for exactly one listener. Rather than teach all of those
# single-listener functions about groups, this loops each of them once
# per OTHER participant -- each listener gets their own analysis/
# reaction/relationship update off the one shared conversation object,
# which is actually more correct than a single blended one would be.
# =========================================================

def apply_speech_to_group(c, world, speech, participant_ids):
    """speech: same shape as apply_speech()'s, but "target" is ignored --
    participant_ids (list, including the speaker c) defines who's in the
    conversation. Returns the conversation dict, or None if the speech
    was empty."""
    if not speech:
        return None

    utterance = speech.get("utterance", "").strip()
    if not utterance:
        return None

    tick = world.get("tick", 0)
    speech_act = speech.get("speech_act", "speak")
    topic = speech.get("topic", "")

    c["current_speech"] = {
        "utterance":       utterance,
        "speech_act":      speech_act,
        "topic":           topic,
        "target":          None,
        "volume":          speech.get("volume") or "high",
        "expires_at_tick": tick + SPEECH_BUBBLE_TICKS,
    }

    c.setdefault("speech_log", [])
    c["speech_log"].append({"tick": tick, "utterance": utterance, "target": None})
    c["speech_log"] = c["speech_log"][-20:]

    from brain.conversations import get_or_create_conversation, add_message
    from systems.reactions import push_conversation_reaction
    from brain.relationships import apply_interaction
    from systems.conversation_analysis import analyze_message, should_schedule_reflection
    from systems.conversation_goals import assign_conversation_goal, check_goal_trending
    from core.event_bus import emit

    conv = get_or_create_conversation(
        world, participant_ids, topic=topic or "general", medium="in_person",
    )
    conversation_type = speech.get("conversation_type")
    if conversation_type:
        conv["conversation_type"] = conversation_type

    add_message(world, conv, c["id"], utterance, speech_act, topic or conv.get("topic", "general"), tick)

    characters = world.get("characters", {})
    topic_str = topic or conv.get("topic", "general")
    for listener_id in participant_ids:
        if listener_id == c["id"]:
            continue
        listener = characters.get(listener_id)
        if not listener:
            continue

        assign_conversation_goal(c, world, conv, listener_id)
        assign_conversation_goal(listener, world, conv, c["id"])

        push_conversation_reaction(listener, speech_act, tick)
        apply_interaction(c, listener, speech_act)
        result = analyze_message(world, conv, c, listener, utterance, speech_act)
        check_goal_trending(conv, listener, topic_str)

        if should_schedule_reflection(result):
            listener.setdefault("pending_reflections", []).append({
                "type":           "conversation",
                "target_id":      c["id"],
                "reason":         speech_act,
                "scheduled_tick": tick + random.randint(50, 300),
                "observations":   result.get("observations", []),
            })

        topic_str = topic or conv.get("topic", "general")
        if topic_str not in ("general", "incidental") and topic_str not in listener.get("opinions", {}):
            listener.setdefault("pending_reflections", []).append({
                "type":           "form_opinion",
                "topic":          topic_str,
                "reason":         f"{c.get('name', 'Someone')} brought this up in conversation.",
                "scheduled_tick": tick + random.randint(20, 120),
            })

        emit("heard_speech", {
            "listener_id": listener_id, "speaker_id": c["id"],
            "speaker_name": c.get("name") or c["id"], "utterance": utterance,
        })

    return conv


# =========================================================
# CLEAR EXPIRED SPEECH
# Call each tick to expire speech bubbles.
# =========================================================

def clear_expired_speech(c, world):
    tick = world.get("tick", 0)
    speech = c.get("current_speech")
    if speech and tick >= speech.get("expires_at_tick", 0):
        c["current_speech"] = None


# =========================================================
# ROUTE MOVE
# =========================================================

def _movement_blocked(c):
    """
    True if this character is physically unable to move right now.
    Centralizes every reason movement should no-op — see
    systems/grapple.py (wrestle/hold restraint), systems/health.py's
    severity-driven postures (apply_severity_consequences), and
    death/unconsciousness — so _route_move/_route_turn_and_run and
    context_builder.py::build_available_actions() never disagree about
    what's live.
    """
    if c.get("alive") is False:
        return True
    if c.get("posture") == "incapacitated":
        return True
    if c.get("grappled_by") or c.get("grappling"):
        return True
    if c.get("held_by") or c.get("holding"):
        return True
    if c.get("activity"):
        return True
    return False


def _route_move(c, world, action, mode="walk"):
    """
    action: {"type": "move"|"jog_to"|"sneak_to", "target": id}
    mode selects the animation_state (and, via
    movement.py::_current_move_speed(), the matching speed field) --
    "walk" for plain move, "jog"/"sneak" for the two faster/quieter modes.
    Sprint isn't offered here: it's reserved for turn_and_run's panic
    flight, not a voluntary pace choice.
    """
    if _movement_blocked(c):
        return

    # Moving always clears a leaning posture
    if c.get("posture") == "leaning_wall":
        from systems.posture import set_posture
        set_posture(c, world, "standing")
        c["leaning_wall_id"] = None

    target_id = action.get("target")
    if not target_id:
        return

    # Find target position from characters or props
    chars = world.get("characters", {})
    if target_id in chars:
        t = chars[target_id]
        c["move_target"] = {
            "x": t.get("x", 0),
            "y": t.get("y", 0),
            "target_id": target_id,
            "target_type": "character",
        }
        if plan_character_route(world, c, t.get("x", 0), t.get("y", 0)):
            c["animation_state"] = mode
            c["is_moving"]       = True
        return

    # world["props"] is a list, not a dict keyed by id -- see
    # systems/props.py::get_prop_by_id() (the convention used everywhere
    # else in this file). The previous `target_id in world["props"]`
    # dict-style lookup here always failed silently, meaning "move"
    # targeting a prop has never actually worked; jog_to/sneak_to share
    # this same fix.
    from systems.props import get_prop_by_id
    p = get_prop_by_id(world, target_id)
    if p:
        c["move_target"] = {
            "x": p.get("x", 0),
            "y": p.get("y", 0),
            "target_id": target_id,
            "target_type": "prop",
        }
        if plan_character_route(world, c, p.get("x", 0), p.get("y", 0)):
            c["animation_state"] = mode
            c["is_moving"]       = True
        return


# =========================================================
# SCAFFOLD ACTIVITY
# Wraps a bare activity dict in the phase/duration/tick
# fields that execute_activity() requires.
# =========================================================

_INTERACTION_DURATIONS = {
    "sit":        1800,
    "sleep":      28800,
    "eat":        720,
    "cook":       1200,
    "work":       28800,
    "interact":   600,
    "wait":       120,
    "retrieve_phone": 300,
    "check_device": 300,
}

def _scaffold(c, world, activity_type, target_id=None,
              interaction=None, duration=None):
    """Return a fully scaffolded activity dict."""
    if duration is None:
        duration = _INTERACTION_DURATIONS.get(
            interaction or activity_type,
            600
        )

    act = {
        "type":               activity_type,
        "phase":              "using",      # router actions start at 'using' (already at target)
        "phase_started_tick": world.get("tick", 0),
        "duration":           duration,
        "state":              {},
    }

    if target_id:
        act["target_id"] = target_id

    if interaction:
        act["interaction"] = interaction

    return act


# =========================================================
# ROUTE INTERACT
# =========================================================

def _route_interact(c, world, action, definitions):
    target_id = action.get("target")
    if not target_id:
        return

    props = world.get("props", {})
    # props may be a dict keyed by id or a list
    if isinstance(props, list):
        prop = next((p for p in props if p.get("id") == target_id), None)
    else:
        prop = props.get(target_id)

    if not prop:
        return

    # prefer interaction specified by the LLM, then fall back to definition
    interaction = action.get("interaction")

    if not interaction:
        template_id = prop.get("template")
        tpl = (
            definitions
            .get("prop_templates", {})
            .get(template_id, {})
        )
        for anchor in tpl.get("anchors", []):
            interaction = anchor.get("interaction")
            if interaction:
                break

    c["activity"] = _scaffold(
        c, world, "interact",
        target_id=target_id,
        interaction=interaction,
    )

    # Set per-interaction using-phase animation immediately
    if interaction:
        c["animation_state"] = get_phase_animation(interaction, "using")

    # mark prop occupied
    prop["occupied_by"] = c["id"]


# =========================================================
# ROUTE EAT
# =========================================================

def _route_eat(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "eat",
        target_id=target_id,
        interaction="eat",
    )


# =========================================================
# ROUTE SLEEP
# =========================================================

def _route_sleep(c, world, action):
    from systems.posture import set_posture
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "sleep",
        target_id=target_id,
        interaction="sleep",
    )
    set_posture(c, world, "lying")


# =========================================================
# ROUTE INDIVIDUAL WAIT ACTIVITIES — microwave
# =========================================================
# Mirrors _route_eat/_route_sleep, not the generic _route_interact: that
# generic path always sets c["activity"]["type"] literally to "interact"
# (see _scaffold's call site above), so a named activity like this one
# needs its own dedicated route + VALID_ACTIONS entry to ever actually
# become that activity's own type string — "interact" alone would never
# match complete_activity()'s "start_microwave"/"take_out_of_microwave"
# branches.

def _route_start_microwave(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "start_microwave",
        target_id=target_id,
        interaction="microwave",
    )


def _route_take_out_of_microwave(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "take_out_of_microwave",
        target_id=target_id,
        interaction="microwave",
    )


# =========================================================
# ROUTE LAUNDRY — same reachability fix as the microwave routes above.
# do_laundry_fill existed since last round but had no dedicated route,
# so it was only ever startable via a direct start_activity() call, never
# by an LLM-driven character choosing it through the normal available-
# actions path — which meant an accepted chore proposal (systems/
# proposals.py) would have had no way to actually get the chore started.
# =========================================================

def _route_do_laundry_fill(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "do_laundry_fill",
        target_id=target_id,
        interaction="do_laundry",
    )


# =========================================================
# ROUTE CHORES — dishes go through the normal start_activity() anchor
# auto-resolution (kitchen_sink/dishwasher are real anchored props);
# floor/surface cleaning has no single prop to walk to (clean wherever
# you currently are), so those are scaffolded directly instead, same
# shape as jog/sit_ups. See systems/chores.py for the driving mechanism
# that also pushes these as real intentions once a zone's cleanliness
# drops below a character's own threshold.
# =========================================================

def _route_wash_dishes(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "wash_dishes")


def _route_load_dishwasher(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "load_dishwasher")


# clean_floors/dust_and_wipe are ACTIVITIES entries flagged no_target
# (see activities.py::start_activity) -- no anchor to walk to, so this
# just kicks off the short "getting started" gesture; the real
# multi-stage work (sweep/vacuum/scrub, or the per-surface wipe loop)
# plays out afterward via task_process.py's background progression once
# complete_activity()'s hand-off fires, same as laundry/dishes above.
def _route_clean_floors(c, world, action):
    from systems.chores import clean_floors_ready, zone_key_for_character
    if not clean_floors_ready(c, world, zone_key_for_character(c)):
        return
    from systems.activities import start_activity
    start_activity(c, world, "clean_floors")


def _route_dust_and_wipe(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "dust_and_wipe")


def _route_water_plants(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "water_plants")


def _route_weed_plants(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "weed_plants")


def _route_harvest_plants(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "harvest_plants")


def _route_redecorate_room(c, world, action):
    from systems.activities import start_activity
    start_activity(c, world, "redecorate_room")


# =========================================================
# ROUTE WAIT
# =========================================================

def _route_wait(c, world, action):
    ticks = action.get("duration", 120)
    c["activity"] = _scaffold(
        c, world, "wait",
        interaction="wait",
        duration=ticks,
    )

    # Optional "waiting for a reason" -- distinguishes blocked-on-something
    # waiting (a person, a business, a delivery) from plain idle waiting.
    # See systems/waiting.py for the patience timer + backlog-stress this
    # arms; a bare "wait" with no waiting_for behaves exactly as before.
    waiting_for = action.get("waiting_for")
    if waiting_for and waiting_for.get("kind"):
        from systems.waiting import start_waiting_for
        start_waiting_for(c, world, waiting_for["kind"], waiting_for.get("ref"))


# =========================================================
# ROUTE DESCRIBE (Round 8) — costs no in-world time, only yields more
# description; never sets c["activity"] and never emits activity_* events
# (that would trigger the c["activity"]-truthy gate in agent_loop.py and
# swallow the character's very next think() for the activity's whole
# duration — the exact bug the older _route_examine already has, worth
# not repeating here).
# =========================================================

def _route_describe(c, world, action):
    from brain.describe_registry import produce_description
    from brain.cognition_scheduler import stage_and_wake, record_describe_or_recall

    record_describe_or_recall("describe")

    target_id = action.get("target")
    aspect = action.get("aspect") or "default"

    if not target_id:
        # No target — room, self, or activity, disambiguated by aspect.
        if aspect in ("inventory", "equipped", "body", "feelings"):
            target_kind = "self"
        elif aspect == "activity":
            target_kind, aspect = "activity", "default"
        else:
            target_kind, aspect = "room", "default"
    elif target_id in world.get("characters", {}):
        target_kind = "character"
    else:
        from systems.props import get_prop_by_id
        target_kind = "prop" if get_prop_by_id(world, target_id) else "item"

    text = produce_description(c, world, target_kind, aspect, target_id)
    stage_and_wake(c, world, text, "describe_result")


# =========================================================
# ROUTE RECALL (Round 9) — costs no in-world time, same no-activity rule
# as _route_describe above. No target_description: surfaces last_thought
# + the highest-priority active intention. With one: tries resolving it
# against a nearby/known character's name first (recall's overwhelmingly
# common subject — matching a proper name against memory text works far
# better than matching a vague description against it), falling back to
# the raw query text if that doesn't resolve. Deliberately does NOT go
# through action_resolver.resolve_and_apply()'s normal resolve-or-fail
# path (see action_registry.py's "recall" spec, target="none") — an
# unresolvable subject here should still search memory text, not stage a
# "nothing matches" retry and drop the recall entirely.
# =========================================================

def _route_recall(c, world, action, available_actions=None):
    from brain.memory import biased_recall
    from brain.cognition_scheduler import stage_and_wake, record_describe_or_recall

    record_describe_or_recall("recall")

    query = (action.get("target_description") or "").strip()

    if not query:
        text = _default_recall_text(c)
        stage_and_wake(c, world, text, "recall_result")
        return

    subject_name = _resolve_recall_subject(c, world, query, available_actions)
    memories = biased_recall(c, query=subject_name or query, limit=5, world=world)
    text = _render_recall_result(query, memories)
    stage_and_wake(c, world, text, "recall_result")


def _default_recall_text(c):
    parts = []

    thought = c.get("last_thought")
    if thought:
        parts.append(f'Your last thought: "{thought}"')

    active = c.get("active_intentions") or []
    if active:
        from brain.intentions import final_priority
        top = max(active, key=final_priority)
        reason = top.get("reason")
        if reason:
            parts.append(f"You'd been meaning to: {reason}")

    if not parts:
        return "Nothing in particular comes to mind right now."
    return " ".join(parts)


def _resolve_recall_subject(c, world, query, available_actions):
    from brain.action_resolver import _score, ACCEPT_THRESHOLD

    chars = world.get("characters", {})
    pool = []
    if available_actions:
        for entry in available_actions.get("nearby_characters") or []:
            eid = entry.get("id")
            if eid and entry.get("name"):
                pool.append((eid, [entry["name"]]))
        for entry in available_actions.get("known_contacts") or []:
            eid = entry.get("id")
            if eid and entry.get("name"):
                pool.append((eid, [entry["name"]]))
    else:
        for other_id in c.get("relationships", {}):
            other = chars.get(other_id)
            if other and other.get("name"):
                pool.append((other_id, [other["name"]]))

    best_id, best_score = None, 0.0
    for cid, bag in pool:
        s = _score(query, bag)
        if s > best_score:
            best_id, best_score = cid, s

    if best_id is not None and best_score >= ACCEPT_THRESHOLD:
        target = chars.get(best_id)
        if target:
            return target.get("name")
    return None


def _render_recall_result(query, memories):
    if not memories:
        return f'You try to recall something about "{query}", but nothing comes.'

    now = time.time()
    lines = []
    for m in memories:
        age = _humanize_memory_age(now - m.get("created_at", now))
        text = m.get("text", "")
        if text:
            lines.append(f"({age}) {text}")

    if not lines:
        return f'You try to recall something about "{query}", but nothing comes.'
    return "What you remember:\n" + "\n".join(lines)


def _humanize_memory_age(seconds):
    seconds = max(0, seconds)
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


# =========================================================
# ROUTE EXAMINE / INSPECT
# =========================================================

def _route_examine(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "examine",
        target_id=target_id,
        interaction="examine",
        duration=180,
    )
    c["animation_state"] = get_phase_animation("examine", "using")


# =========================================================
# ROUTE SEARCH FOR ITEM
# =========================================================

def _route_search(c, world, action):
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "search",
        target_id=target_id,
        interaction="search",
        duration=600,
    )
    c["animation_state"] = get_phase_animation("search", "using")


# =========================================================
# ROUTE TRASH / DESTROY
# =========================================================

def _route_trash(c, world, action):
    target_id = action.get("target")
    interaction = "trash" if action.get("type") == "trash" else "destroy"
    c["activity"] = _scaffold(
        c, world, action.get("type", "trash"),
        target_id=target_id,
        interaction=interaction,
        duration=120,
    )
    c["animation_state"] = get_phase_animation(interaction, "using")


# =========================================================
# ROUTE CARRY
# Character picks up target prop and walks it to destination.
# LLM action must include:
#   target:      prop_id to carry
#   destination: { x, y } tile to deliver to
# =========================================================

def _route_carry(c, world, action):
    target_id = action.get("target")
    if not target_id:
        return

    props = world.get("props", {})
    prop = props.get(target_id) if isinstance(props, dict) else next(
        (p for p in props if p.get("id") == target_id), None
    )

    if not prop:
        return

    # Only carry props flagged carryable (or small by default)
    if not prop.get("carryable", True):
        return

    dest = action.get("destination", {})

    act = _scaffold(
        c, world, "carry",
        target_id=target_id,
        interaction="carry",
        duration=0,    # duration not used; phase logic drives carry
    )
    act["phase"] = "walking"           # walk to prop first
    act["destination"] = dest
    act["phase_started_tick"] = world.get("tick", 0)

    # Route character to the prop's current position
    c["move_target"] = {
        "x": prop.get("x", 0),
        "y": prop.get("y", 0),
        "target_id": target_id,
        "target_type": "prop",
    }
    # Only mark as walking if a route was actually found — otherwise the
    # "walking" phase (activities.py) would wait on is_moving forever with
    # no route ever progressing to clear it.
    c["is_moving"] = plan_character_route(world, c, prop.get("x", 0), prop.get("y", 0))
    c["activity"] = act
    c["animation_state"] = "walk"


# =========================================================
# MOVABLE PROPS — drag / push / let go
# (see systems/prop_movement.py; a prop tagged move_capacity=1 can be
# dragged solo, move_capacity=2 needs a second character to push before
# it actually moves)
# =========================================================

def _route_drag_prop(c, world, action):
    from systems.props import get_prop_by_id
    from systems.prop_movement import get_move_capacity, play_prop_action_once, can_drag

    target_id = action.get("target")
    if not target_id:
        return
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return
    if get_move_capacity(prop) not in (1, 2):
        return
    if not can_drag(c):
        return
    dragger = prop.get("being_dragged_by")
    if dragger and dragger != c["id"]:
        return

    c["dragged_prop_id"] = target_id
    prop["being_dragged_by"] = c["id"]
    play_prop_action_once(c, world, "start_dragging", target_idle="drag_idle")


def _route_push_prop(c, world, action):
    from systems.props import get_prop_by_id
    from systems.prop_movement import get_move_capacity, play_prop_action_once

    target_id = action.get("target")
    if not target_id:
        return
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return
    if get_move_capacity(prop) != 2:
        return
    dragger = prop.get("being_dragged_by")
    if not dragger or dragger == c["id"]:
        return

    c["pushing_prop_id"] = target_id
    prop["being_pushed_by"] = c["id"]
    # Reuses the dragger's "getting into position" clip for the pusher too
    # — no separate pusher-specific start animation was called for.
    play_prop_action_once(c, world, "start_dragging", target_idle="pushing")


def _route_let_go_prop(c, world, action):
    from systems.props import get_prop_by_id
    from systems.prop_movement import play_prop_action_once

    target_id = action.get("target")

    if target_id and c.get("dragged_prop_id") != target_id and c.get("pushing_prop_id") != target_id:
        return

    dragged_id = c.get("dragged_prop_id")
    if dragged_id:
        prop = get_prop_by_id(world, dragged_id)
        c["dragged_prop_id"] = None
        if prop:
            prop["being_dragged_by"] = None
            # A pusher left attached to a now-driverless prop is invalid
            # state — cascade-clear them too.
            pusher_id = prop.pop("being_pushed_by", None)
            if pusher_id:
                pusher = world.get("characters", {}).get(pusher_id)
                if pusher:
                    pusher["pushing_prop_id"] = None
                    play_prop_action_once(pusher, world, "let_go")
        play_prop_action_once(c, world, "let_go")
        return

    pushing_id = c.get("pushing_prop_id")
    if pushing_id:
        prop = get_prop_by_id(world, pushing_id)
        c["pushing_prop_id"] = None
        if prop:
            prop["being_pushed_by"] = None
        play_prop_action_once(c, world, "let_go")


# =========================================================
# ROUTE CLEAN
# Picks the correct animation based on the target prop's tags.
# =========================================================

def _route_clean(c, world, action, definitions):
    target_id = action.get("target")

    props = world.get("props", {})
    prop = props.get(target_id) if isinstance(props, dict) else next(
        (p for p in props if p.get("id") == target_id), None
    )

    c["activity"] = _scaffold(
        c, world, "clean",
        target_id=target_id,
        interaction="clean",
        duration=900,
    )

    # Use prop-aware animation immediately
    c["animation_state"] = get_clean_animation(prop, "using") if prop else "clean_generic"


# =========================================================
# ROUTE WEAR / UNDRESS
# Put on / take off clothing items from the character's personal inventory.
# action = { "type": "wear",    "item_id": "item_tshirt_abc123" }
# action = { "type": "undress", "slot": "torso" }   or omit slot to undress all
# =========================================================

def _route_wear(c, world, action, definitions=None):
    from systems.clothing import put_on_clothing
    item_id = action.get("item_id")
    if not item_id:
        return
    result = put_on_clothing(c, world, item_id)
    if result.get("swapped_off"):
        # Old item already returned to inventory by put_on_clothing
        pass


def _route_undress(c, world, action):
    from systems.clothing import take_off_clothing, undress_all
    slot = action.get("slot")
    if slot:
        take_off_clothing(c, world, slot)
    else:
        undress_all(c, world)



# =========================================================
# ASSEMBLE PROP
# action = { "type": "assemble_prop", "item_id": "item_box_modern_sofa_abc" }
# =========================================================

def _route_assemble_prop(c, world, action):
    from systems.assembly import assemble_prop
    item_id = action.get("item_id")
    if not item_id:
        return
    assemble_prop(c, world, item_id)


# =========================================================
# ASSEMBLE TILE
# action = { "type": "assemble_tile", "item_id": "item_box_wood_floor_01_abc" }
# Places one tile at character's current position; decrements box quantity.
# =========================================================

def _route_assemble_tile(c, world, action):
    from systems.assembly import assemble_tile
    item_id = action.get("item_id")
    if not item_id:
        return
    assemble_tile(c, world, item_id)


# =========================================================
# HIRE SERVICE
# action = {
#   "type":         "hire_service",
#   "service_type": "reconstruction",
#   "subtype":      "floor_tiling",
#   "details":      {"tiles": [{"x":1,"y":2,"material":"wood_floor_01"}, ...]},
#   "quantity":     5
# }
# Legitimate services bill via mailbox; illicit deduct cash immediately.
# =========================================================

def _route_hire_service(c, world, action):
    from systems.services import request_service
    request_service(
        c, world,
        service_type=action.get("service_type"),
        subtype=action.get("subtype"),
        details=action.get("details", {}),
        quantity=action.get("quantity", 1),
    )


# =========================================================
# MAIN ROUTER
# =========================================================

def route_action(c, world, action, speech, definitions=None, available_actions=None):
    """
    Dispatch the LLM's action and speech into world state.

    action = {
        "type":   str,
        "target": str | None,
        "reason": str | None,
    }
    speech = {
        "utterance": str,
        ...
    }
    definitions = world["definitions"] (optional, for prop lookups)
    """
    if definitions is None:
        definitions = world.get("definitions", {})

    # Always apply speech first so it displays even if action fails
    if speech:
        apply_speech(c, world, speech)

    if not action:
        return

    action_type = action.get("type", "")

    if action_type == "move":
        _route_move(c, world, action)

    elif action_type == "jog_to":
        _route_move(c, world, action, mode="jog")

    elif action_type == "sneak_to":
        _route_move(c, world, action, mode="sneak")

    elif action_type == "interact":
        _route_interact(c, world, action, definitions)

    elif action_type in ("speak", "socialize"):
        # Speech was already applied above.
        # Also point character toward target if given.
        target_id = action.get("target")
        if target_id:
            chars = world.get("characters", {})
            if target_id in chars:
                t = chars[target_id]
                c["look_target"] = {
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                }

    elif action_type == "eat":
        _route_eat(c, world, action)

    elif action_type == "sleep":
        _route_sleep(c, world, action)

    elif action_type == "start_microwave":
        _route_start_microwave(c, world, action)

    elif action_type == "take_out_of_microwave":
        _route_take_out_of_microwave(c, world, action)

    elif action_type == "do_laundry_fill":
        _route_do_laundry_fill(c, world, action)

    elif action_type == "wash_dishes":
        _route_wash_dishes(c, world, action)

    elif action_type == "load_dishwasher":
        _route_load_dishwasher(c, world, action)

    elif action_type == "clean_floors":
        _route_clean_floors(c, world, action)

    elif action_type == "dust_and_wipe":
        _route_dust_and_wipe(c, world, action)

    elif action_type == "water_plants":
        _route_water_plants(c, world, action)

    elif action_type == "weed_plants":
        _route_weed_plants(c, world, action)

    elif action_type == "harvest_plants":
        _route_harvest_plants(c, world, action)

    elif action_type == "redecorate_room":
        _route_redecorate_room(c, world, action)

    elif action_type == "wait":
        _route_wait(c, world, action)

    elif action_type == "work":
        c["activity"] = _scaffold(c, world, "work", interaction="work")

    elif action_type == "describe":
        _route_describe(c, world, action)

    elif action_type == "recall":
        _route_recall(c, world, action, available_actions)

    elif action_type == "examine":
        _route_examine(c, world, action)

    elif action_type == "search":
        _route_search(c, world, action)

    elif action_type in ("trash", "destroy"):
        _route_trash(c, world, action)

    elif action_type == "carry":
        _route_carry(c, world, action)

    elif action_type == "clean":
        _route_clean(c, world, action, definitions)

    elif action_type == "wear":
        _route_wear(c, world, action, definitions)

    elif action_type == "undress":
        _route_undress(c, world, action)

    elif action_type == "assemble_prop":
        _route_assemble_prop(c, world, action)

    elif action_type == "assemble_tile":
        _route_assemble_tile(c, world, action)

    elif action_type == "drag_prop":
        _route_drag_prop(c, world, action)

    elif action_type == "push_prop":
        _route_push_prop(c, world, action)

    elif action_type == "let_go_prop":
        _route_let_go_prop(c, world, action)

    elif action_type == "hire_service":
        _route_hire_service(c, world, action)

    elif action_type == "build_wall":
        _route_build_wall(c, world, action)

    elif action_type == "remove_wall":
        _route_remove_wall(c, world, action)

    elif action_type == "paint_wall":
        _route_paint_wall(c, world, action)

    # ── Phone ──────────────────────────────────────────────────────────────────
    elif action_type == "phone_call":
        _route_phone_call(c, world, action)
    elif action_type == "phone_answer":
        _route_phone_answer(c, world, action)
    elif action_type == "order_taxi_by_phone_call":
        _route_order_taxi_by_phone_call(c, world, action)
    elif action_type == "order_taxi_by_phone_app":
        _route_order_taxi_by_phone_app(c, world, action)
    elif action_type == "order_taxi":
        _route_order_taxi(c, world, action)
    elif action_type == "phone_send_text":
        _route_phone_send_text(c, world, action)
    elif action_type in ("phone_check", "call", "text"):
        _route_phone_check(c, world, action)
    elif action_type == "phone_read_text":
        _route_phone_read_text(c, world, action)
    elif action_type == "retrieve_phone":
        _route_retrieve_phone(c, world, action)
    elif action_type == "check_device":
        _route_check_device(c, world, action)
    elif action_type == "check_computer_history":
        _route_check_computer_history(c, world, action)
    elif action_type == "answer_about_pattern":
        _route_answer_about_pattern(c, world, action)
    elif action_type == "form_theory":
        _route_form_theory(c, world, action)
    elif action_type == "make_argument":
        _route_make_argument(c, world, action)
    elif action_type == "contact_business":
        _route_contact_business(c, world, action)
    elif action_type == "book_appointment":
        _route_book_appointment(c, world, action)

    # ── Computer ───────────────────────────────────────────────────────────────
    elif action_type == "computer_social_media":
        _route_computer(c, world, action, "computer_social_media")
    elif action_type == "computer_videos":
        _route_computer(c, world, action, "computer_videos")
    elif action_type == "computer_game":
        _route_computer(c, world, action, "computer_game")
    elif action_type == "computer_wiki_research":
        _route_computer_wiki_research(c, world, action)
    elif action_type == "computer_news":
        _route_computer_news(c, world, action)
    elif action_type == "read_newspaper":
        _route_read_newspaper(c, world, action)
    elif action_type == "browse_news":
        _route_browse_news(c, world, action)
    elif action_type == "computer_window_shopping":
        _route_computer(c, world, action, "computer_window_shopping")
    elif action_type == "computer_dating":
        _route_computer(c, world, action, "computer_dating")
    elif action_type == "computer_job_search":
        _route_computer_job_search(c, world, action)
    elif action_type == "computer_apply_for_job":
        _route_computer_apply_for_job(c, world, action)
    elif action_type in ("computer_send_email", "computer_respond_email", "computer_check_email"):
        _route_computer_email(c, world, action)
    elif action_type == "browse_second_hand_marketplace":
        _route_browse_second_hand_marketplace(c, world, action)
    elif action_type == "sell_prop_item_second_hand":
        _route_sell_prop_item_second_hand(c, world, action)
    elif action_type == "buy_prop_item_second_hand":
        _route_buy_prop_item_second_hand(c, world, action)
    elif action_type == "estimate_avg_sell_value":
        _route_estimate_avg_sell_value(c, world, action)
    elif action_type == "browse_darknet_market":
        _route_browse_darknet_market(c, world, action)
    elif action_type == "order_darknet_listing":
        _route_order_darknet_listing(c, world, action)
    elif action_type == "write_diary":
        _route_write_diary(c, world, action)
    elif action_type == "computer_list_stocks":
        _route_computer_list_stocks(c, world, action)
    elif action_type == "computer_buy_stock":
        _route_computer_buy_stock(c, world, action)
    elif action_type == "computer_sell_stock":
        _route_computer_sell_stock(c, world, action)
    elif action_type == "computer_check_stock_value":
        _route_computer_check_stock_value(c, world, action)
    elif action_type == "computer_order_item":
        _route_computer_order_item(c, world, action)
    elif action_type == "computer_order_service":
        _route_computer_order_service(c, world, action)
    elif action_type == "social_browse_events":
        _route_social_browse_events(c, world, action)
    elif action_type == "social_event_rsvp":
        _route_social_event_rsvp(c, world, action)
    elif action_type == "social_event_comment":
        _route_social_event_comment(c, world, action)
    elif action_type == "social_event_attend":
        _route_social_event_attend(c, world, action)
    elif action_type == "social_event_plan":
        _route_social_event_plan(c, world, action)
    elif action_type == "organize_hobby_session":
        _route_organize_hobby_session(c, world, action)
    elif action_type == "plan_hobby_session":
        _route_plan_hobby_session(c, world, action)

    elif action_type == "leave_note":
        _route_leave_note(c, world, action)
    elif action_type == "give_excuse":
        _route_give_excuse(c, world, action)
    elif action_type == "announce_departure":
        _route_announce_departure(c, world, action)
    elif action_type == "apply_discipline":
        _route_apply_discipline(c, world, action)
    elif action_type == "apply_reward":
        _route_apply_discipline(c, world, action)   # same pipeline
    elif action_type == "negotiate_contract":
        _route_negotiate_contract(c, world, action)

    elif action_type in ("hug", "kiss", "kiss_peck", "kiss_deep", "cuddle", "hold_hands", "handshake", "high_five"):
        _route_propose_touch(c, world, action, action_type)
    elif action_type == "respond_touch":
        _route_respond_touch(c, world, action)

    elif action_type == "confront":
        _route_confront(c, world, action)
    elif action_type == "call_911":
        _route_call_911(c, world, action)
    elif action_type == "call_parent":
        _route_call_parent(c, world, action)
    elif action_type == "administer_first_aid":
        _route_administer_first_aid(c, world, action)
    elif action_type == "plant_seed":
        _route_plant_seed(c, world, action)
    elif action_type == "water":
        _route_water(c, world, action)
    elif action_type == "pull_weed":
        _route_pull_weed(c, world, action)
    elif action_type == "harvest":
        _route_harvest(c, world, action)
    elif action_type == "collect":
        _route_collect(c, world, action)
    elif action_type == "jog":
        _route_jog(c, world, action)
    elif action_type == "sit_ups":
        _route_sit_ups(c, world, action)
    elif action_type == "chin_ups":
        _route_chin_ups(c, world, action)
    elif action_type == "lift_weights":
        _route_lift_weights(c, world, action)
    elif action_type in ("grab_offensive", "hold", "punch", "kick", "shove", "threaten", "stab", "knock"):
        _route_hostile_action(c, world, action)
    elif action_type == "steal_from":
        _route_steal_from(c, world, action)
    elif action_type == "dodge":
        _route_dodge(c, world, action)
    elif action_type == "block":
        _route_block(c, world, action)
    elif action_type == "turn_and_run":
        _route_turn_and_run(c, world, action)
    elif action_type == "wrestle":
        _route_wrestle(c, world, action)
    elif action_type == "release_hold":
        _route_release_hold(c, world, action)
    elif action_type == "wield_item":
        _route_wield_item(c, world, action)

    elif action_type == "propose_chore":
        _route_propose_chore(c, world, action)
    elif action_type == "respond_chore":
        _route_respond_chore(c, world, action)
    elif action_type == "advance_chore_round":
        _route_advance_chore_round(c, world, action)
    elif action_type == "propose_recurring":
        _route_propose_recurring(c, world, action)

    elif action_type == "propose_social":
        _route_propose_social(c, world, action)
    elif action_type == "respond_social":
        # respond()/proposer_advance_round() (systems/proposals.py) are
        # already kind-agnostic — they look up by proposal_id, not kind —
        # so the same chore-proposal routers handle social_ask proposals
        # too rather than duplicating identical logic under a new name.
        _route_respond_chore(c, world, action)
    elif action_type == "advance_social_round":
        _route_advance_chore_round(c, world, action)

    elif action_type == "propose_rule":
        _route_propose_rule(c, world, action)
    elif action_type == "add_rule_exception":
        _route_add_rule_exception(c, world, action)
    elif action_type == "propose_request":
        _route_propose_request(c, world, action)
    elif action_type == "respond_request":
        # Same reuse trick as respond_social above — respond() dispatches
        # by proposal_id, not by the action-type string that invoked it.
        _route_respond_chore(c, world, action)
    elif action_type == "advance_request_round":
        _route_advance_chore_round(c, world, action)
    elif action_type == "propose_item_loan":
        _route_propose_item_loan(c, world, action)
    elif action_type == "respond_item_loan":
        _route_respond_chore(c, world, action)
    elif action_type == "advance_item_loan_round":
        _route_advance_chore_round(c, world, action)
    elif action_type == "propose_item_sale":
        _route_propose_item_sale(c, world, action)
    elif action_type == "respond_item_sale":
        _route_respond_chore(c, world, action)
    elif action_type == "advance_item_sale_round":
        _route_advance_chore_round(c, world, action)
    elif action_type == "post_social_media":
        _route_post_social_media(c, world, action)
    elif action_type == "like_social_post":
        _route_like_social_post(c, world, action)
    elif action_type == "unlike_social_post":
        _route_unlike_social_post(c, world, action)
    elif action_type == "comment_on_social_post":
        _route_comment_on_social_post(c, world, action)

    elif action_type == "breastfeed":
        _route_breastfeed(c, world, action)
    elif action_type == "bottle_feed":
        _route_bottle_feed(c, world, action)
    elif action_type == "hold_baby":
        _route_hold_baby(c, world, action)
    elif action_type == "put_baby_in_carriage":
        _route_put_baby_in_carriage(c, world, action)
    elif action_type == "feed_child":
        _route_feed_child(c, world, action)
    elif action_type == "remind_child":
        _route_remind_child(c, world, action)

    # ── Posture ──────────────────────────────────────────────────────────
    elif action_type == "sit_down":
        _route_sit_down(c, world, action)
    elif action_type == "stand_up":
        _route_stand_up(c, world, action)
    elif action_type == "lie_down":
        _route_lie_down(c, world, action)
    elif action_type == "lean_against_wall":
        _route_lean_against_wall(c, world, action)
    elif action_type == "push_off_wall":
        _route_push_off_wall(c, world, action)
    elif action_type == "add_to_stack":
        _route_add_to_stack(c, world, action)
    elif action_type == "put_down_stack":
        _route_put_down_stack(c, world, action)
    elif action_type == "search_stack":
        _route_search_stack(c, world, action)
    elif action_type == "take_from_stack":
        _route_take_from_stack(c, world, action)
    elif action_type == "pocket_item":
        _route_pocket_item(c, world, action)

# =========================================================
# SOCIAL CONTRACT HANDLERS
# =========================================================

def _route_announce_departure(c, world, action):
    """
    Character announces they are leaving.
    Sets _announced_departure flag and fires an incidental speech bubble.
    target_id: authority or authorized person to tell (optional — will find one)
    """
    target_id = action.get("target_id") or action.get("target")
    chars     = world.get("characters", {})

    # If no explicit target, find an authority in same location
    if not target_id:
        cur_loc = c.get("current_location") or c.get("building_id")
        for oid, other in chars.items():
            if oid == c["id"]:
                continue
            other_loc = other.get("current_location") or other.get("building_id")
            if other_loc != cur_loc:
                continue
            rel = c.get("relationships", {}).get(oid, {})
            if any(lbl in rel.get("labels", []) for lbl in ("parent","guardian","spouse","partner")):
                target_id = oid
                break

    try:
        from systems.incidental_speech import fire_incidental
        import random
        phrases = [
            "I'm heading out.",
            "Just letting you know I'm leaving.",
            "Going out — be back later.",
        ]
        fire_incidental(c, "announce", random.choice(phrases), world, target_id=target_id)
    except Exception:
        pass

    c["_announced_departure"] = True


def _route_apply_discipline(c, world, action):
    """
    Authority applies a disciplinary or reward method to a subject.
    action: {type: "apply_discipline", target_id: subject_id, method_id: "grounding"}
    """
    target_id = action.get("target_id") or action.get("target")
    method_id = action.get("method_id") or action.get("method")
    if not target_id or not method_id:
        return
    subject = world.get("characters", {}).get(target_id)
    if not subject:
        return

    try:
        from systems.conditioning import apply_discipline
        apply_discipline(subject, c, method_id, world)
        # Clear the intention that prompted this (see systems/child_care.py's
        # discipline_child_* intention, injected by _route_call_parent below)
        # -- same close-the-loop pattern feed_child/remind_child already use.
        _clear_parent_intention(c, f"discipline_child_{target_id}")
    except Exception:
        pass


def _route_leave_note(c, world, action):
    """
    Character writes and leaves a note on a message_surface prop.
    action: {type: "leave_note", text: "...", target_id: prop_id (optional)}
    """
    text = action.get("text") or action.get("message")
    try:
        from systems.excuses import leave_note
        leave_note(c, world, text=text)
    except Exception:
        c["_announced_departure"] = True
        c["_left_note_this_tick"] = True


def _route_give_excuse(c, world, action):
    """
    Character gives an explanation or excuse when confronted.
    action: {type: "give_excuse", target_id: authority_id, question_type: "who"|"where"|"what"|"when"}
    The system decides: vague truth → omission → lie, based on relationship + privacy.
    """
    target_id     = action.get("target_id") or action.get("target")
    question_type = action.get("question_type", "where")
    if not target_id:
        return
    authority = world.get("characters", {}).get(target_id)
    if not authority:
        return

    try:
        from systems.excuses import generate_excuse
        from systems.incidental_speech import fire_incidental
        result = generate_excuse(c, authority, question_type, world)
        fire_incidental(c, "inform", result["text"], world, target_id=target_id)
        # Log if it was a lie
        if result.get("is_lie"):
            c.setdefault("_recent_lie_to", {})[target_id] = result["lie_detail"]
        # Evasive but not an outright lie (vague deflection/refusal) —
        # weaker evidence than a caught lie, still noticed by the asker
        # who's already standing right here (systems/worries.py).
        elif result.get("vagueness", 0) > 0.5:
            from systems.worries import bump_suspicion
            bump_suspicion(
                authority, c["id"], 0.075, "evasive",
                f"{c.get('name', c['id'])} was evasive when asked about something",
                world,
            )
    except Exception:
        pass


def _route_negotiate_contract(c, world, action):
    """
    Subject proposes modification to an existing social contract.
    action: {type: "negotiate_contract", contract_id: "...",
             proposed_terms: {...}, exchange_offer: "..."}
    """
    contract_id    = action.get("contract_id")
    proposed_terms = action.get("proposed_terms", {})
    exchange_offer = action.get("exchange_offer", "")

    contract = world.get("social_contracts", {}).get(contract_id)
    if not contract:
        # Try to find active contract where c is subject
        for cid_loop in c.get("social_contract_ids", []):
            ct = world.get("social_contracts", {}).get(cid_loop, {})
            if ct.get("status") == "active" and ct.get("subject_id") == c["id"]:
                contract = ct
                break
    if not contract:
        return

    try:
        from systems.social_contracts import propose_contract_modification
        propose_contract_modification(contract, c["id"], proposed_terms,
                                      exchange_offer, world)
    except Exception:
        pass


# =========================================================
# TOUCH PROPOSAL HANDLERS
# =========================================================

def _route_propose_touch(c, world, action, template_id):
    """
    Character proposes a hug / kiss / cuddle to a target.
    Stores touch_negotiation state; recipient resolves on next tick.
    """
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    chars     = world.get("characters", {})
    recipient = chars.get(target_id)
    if not recipient:
        return
    # Must be at same location. building_id is the one live-maintained
    # spatial field (movement.py, room_assignment.py) — current_location
    # is never written anywhere, so comparing it always passed regardless
    # of real proximity.
    if c.get("building_id") != recipient.get("building_id"):
        return

    try:
        from systems.intimacy import propose_touch
        propose_touch(c, recipient, template_id, world)
    except Exception:
        pass


def _route_respond_touch(c, world, action):
    """
    Character manually responds to a pending touch proposal.
    Used when the player overrides the AI decision.
    action: {"type": "respond_touch", "target_id": proposer_id, "response": "accept"|"reject"}
    """
    proposer_id = action.get("target_id") or action.get("target")
    response    = action.get("response", "accept")
    if not proposer_id:
        return
    proposer = world.get("characters", {}).get(proposer_id)
    if not proposer:
        return

    try:
        from systems.intimacy import respond_to_touch_proposal
        respond_to_touch_proposal(c, proposer, response, world)
    except Exception:
        pass


# =========================================================
# HOSTILE INTENTIONS / EMERGENCY HANDLERS — see
# systems/conflict_pipeline.py and systems/emergency.py
# =========================================================

def _route_confront(c, world, action):
    """
    Character deliberately confronts another over accumulated grievances.
    action: {"type": "confront", "target_id": other_id}
    Hands off to the existing trait/dice-driven conflict state machine
    (systems/conflict_pipeline.py) — same formulaic resolution it already
    uses when triggered automatically via confrontation_desired. Only the
    decision to confront is the LLM's; everything after is the same
    non-fluid pipeline used everywhere else, per the user's explicit
    fluid-vs-scripted boundary.
    """
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    target = world.get("characters", {}).get(target_id)
    if not target:
        return
    # Locality — building_id is the one live-maintained spatial field,
    # same fix applied to every other locality gate this session.
    if c.get("building_id") != target.get("building_id"):
        return

    try:
        from systems.conflict_pipeline import start_conflict
        start_conflict(c["id"], target_id, world)
    except Exception:
        pass


def _route_call_911(c, world, action):
    """
    Character calls 911 about a specific incident they're aware of.
    action: {"type": "call_911", "target_id": incident_id}
    Lock-in: the first successful call reports the incident; later calls on
    the same incident are a harmless no-op (see emergency.py::resolve() /
    auto_report_incidents() for the rest of the already-wired dispatch
    chain — create_911_call() itself emits emergency_call_created, which
    core/event_handlers.py already subscribes to dispatch() on).
    """
    incident_id = action.get("target_id") or action.get("target")
    if not incident_id:
        return
    incident = next(
        (i for i in world.get("incidents", []) if i["id"] == incident_id),
        None,
    )
    if not incident or incident.get("reported"):
        return

    # Awareness gate: either a direct participant, or physically close
    # enough to have witnessed it — same Manhattan-4 radius
    # emergency.py::resolve() already uses for responder effect.
    loc = incident.get("location", {})
    is_participant = c["id"] in incident.get("participants", [])
    is_nearby = (
        "x" in loc and "y" in loc
        and abs(c.get("x", 0) - loc["x"]) + abs(c.get("y", 0) - loc["y"]) < 4
    )
    if not (is_participant or is_nearby):
        return

    from systems.emergency import INCIDENT_CALL_TYPE
    entry = INCIDENT_CALL_TYPE.get(incident.get("type"))
    emergency_type, report = (entry[0], entry[1]) if entry else ("police", "There's an emergency.")

    try:
        from systems.emergency import create_911_call
        create_911_call(world, c, emergency_type, report, incident_id=incident["id"])
        incident["reported"] = True
    except Exception:
        pass


def _route_call_parent(c, world, action):
    """
    Adult witness to a child's hostile act calls the child's parent(s)
    instead of 911 (see systems/hostile_actions.py's offender_is_minor/
    victim_injured incident tagging). Mirrors _route_call_911's incident
    lookup + awareness gate exactly; the extra gates below are specific to
    this action -- wrong incident shape, or a child trying to call on
    themselves, is a silent no-op, same style call_911 already uses.
    action: {"type": "call_parent", "target_id": incident_id}
    """
    if c.get("age_group") not in ("adult", "elderly"):
        return

    incident_id = action.get("target_id") or action.get("target")
    if not incident_id:
        return
    incident = next(
        (i for i in world.get("incidents", []) if i["id"] == incident_id),
        None,
    )
    if not incident or incident.get("reported"):
        return
    if not incident.get("offender_is_minor") or incident.get("victim_injured"):
        return

    loc = incident.get("location", {})
    is_participant = c["id"] in incident.get("participants", [])
    is_nearby = (
        "x" in loc and "y" in loc
        and abs(c.get("x", 0) - loc["x"]) + abs(c.get("y", 0) - loc["y"]) < 4
    )
    if not (is_participant or is_nearby):
        return

    offender = world.get("characters", {}).get(incident.get("offender_id"))
    if not offender:
        return

    try:
        from systems.child_care import _find_parents_for_child
        from brain.intentions import add_intention

        parents = _find_parents_for_child(offender, world)
        if not parents:
            return

        for parent in parents:
            add_intention(parent, {
                "type":     f"discipline_child_{offender['id']}",
                "category": "health",
                "priority": 85,
                "reason":   f"{offender.get('name', 'your child')} got into a fight and needs to be dealt with",
                "child_id": offender["id"],
            })
        incident["reported"] = True
    except Exception:
        pass


# =========================================================
# FIRST AID — see systems/health.py's per-bodypart damage rework
# (treat_body_part, Round 2). Same "immediate, no _scaffold activity"
# shape as confront/call_911/call_parent above -- resolves in a single
# tick rather than spawning an ongoing activity.
# =========================================================

_FIRST_AID_ITEM_TEMPLATES = ("first_aid_kit", "bandages")
_SEVERITY_RANK = {"severe": 3, "medium": 2, "low": 1}


def _worst_untreated_body_part(target):
    """Pick the body part with the highest-severity untreated hazard, so
    administer_first_aid can be called without the LLM having to name a
    specific body_part."""
    hs = target.get("health_state", {})
    best = None
    best_rank = -1
    for part, bp in hs.get("body_parts", {}).items():
        if not any(not h.get("treated") for h in bp.get("hazards", {}).values()):
            continue
        rank = _SEVERITY_RANK.get(bp.get("severity_level"), 0)
        if rank > best_rank:
            best, best_rank = part, rank
    return best


def _route_administer_first_aid(c, world, action):
    """
    Character applies first aid to a damaged body part -- their own, or a
    nearby other's. Requires a first_aid_kit or bandages item with
    uses > 0 in inventory; one use is consumed per attempt (mirrors
    containers.py's bucket["uses"] decrement pattern -- see
    systems/health.py::treat_body_part for what it actually does:
    marks treatable hazards on that part "treated" and reduces its pain,
    it doesn't cure them outright).
    action: {"type": "administer_first_aid", "target_id": char_id
             (optional, defaults to self), "body_part": one of
             health.BODY_PARTS (optional, defaults to the target's
             worst untreated part)}
    """
    from systems.personal_items import get_item_by_template, remove_item
    from systems.health import treat_body_part, BODY_PARTS

    target_id = action.get("target_id") or action.get("target") or c["id"]
    target = c if target_id == c["id"] else world.get("characters", {}).get(target_id)
    if not target:
        return
    if target is not c and c.get("building_id") != target.get("building_id"):
        return

    item = None
    for template_id in _FIRST_AID_ITEM_TEMPLATES:
        item = get_item_by_template(c, template_id)
        if item and item.get("uses", 0) > 0:
            break
        item = None
    if not item:
        return

    body_part = action.get("body_part")
    if body_part not in BODY_PARTS:
        body_part = _worst_untreated_body_part(target)
    if not body_part:
        return

    treated = treat_body_part(target, world, body_part, method="first_aid")

    item["uses"] = item.get("uses", 1) - 1
    if item["uses"] <= 0:
        remove_item(c, item["id"])

    if treated:
        try:
            from brain.memory import store_memory
            who = "myself" if target is c else target.get("name", "someone")
            store_memory(
                c, f"Gave first aid to {who}'s {body_part.replace('_', ' ')}.",
                0.6, ["health", "first_aid"], "health", world.get("tick", 0),
            )
        except Exception:
            pass


# =========================================================
# PLANTS — see systems/plants.py. Four simple, immediate interactions
# (no _scaffold/multi-tick activity machinery -- same shape as
# confront/call_911/call_parent above), each resolving a prop target and
# calling straight into plants.py.
# =========================================================

def _route_plant_seed(c, world, action):
    """
    action: {"type": "plant_seed", "plant_template_id": "...",
             "target_id": pot_prop_id}  -- plant into an existing empty pot
    OR      {"type": "plant_seed", "plant_template_id": "...",
             "x": ..., "y": ...}         -- new soil-grown plant at a tile
    """
    plant_template_id = action.get("plant_template_id")
    if not plant_template_id:
        return
    from systems.plants import plant_seed
    from systems.props import get_prop_by_id

    target_id = action.get("target_id") or action.get("target")
    if target_id:
        prop = get_prop_by_id(world, target_id)
        if not prop:
            return
        plant_seed(world, plant_template_id, target_prop=prop)
    else:
        x, y = action.get("x"), action.get("y")
        if x is None or y is None:
            return
        plant_seed(world, plant_template_id, x=x, y=y, household_id=c.get("household_id"))


def _route_water(c, world, action):
    """action: {"type": "water", "target_id": plant_prop_id} -- ad hoc,
    single-plant watering (the multi-stage "water_plants" household
    chore, systems/task_process.py, is the normal path for a whole
    round). Still requires a filled watering can (systems/containers.py's
    liquid-capacity helpers), consuming one use -- same capacity concept
    either way."""
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return
    from systems.chores import find_watering_can
    from systems.containers import water_uses_remaining, use_water
    can, _source = find_watering_can(c, world)
    if not can or water_uses_remaining(can) <= 0:
        return
    from systems.plants import water_plant
    if not water_plant(prop):
        return
    use_water(can)

    # Closes the loop on an accepted "water_plants" chore proposal
    # (systems/proposals.py) -- mirrors do_laundry_fill's _pending_chore
    # hand-off in activities.py, but consumed right here since watering
    # resolves immediately rather than through the multi-tick activity
    # completion pipeline laundry uses.
    household = world.get("households", {}).get(c.get("household_id"))
    if household:
        pending = household.get("_pending_chore")
        if pending and pending.get("chore_id") == "water_plants":
            household.pop("_pending_chore", None)


def _route_pull_weed(c, world, action):
    """action: {"type": "pull_weed", "target_id": plant_prop_id}"""
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return
    from systems.plants import pull_weed
    pull_weed(prop)


def _route_harvest(c, world, action):
    """action: {"type": "harvest", "target_id": plant_prop_id,
    "dest_id": optional carried/worn container to deposit into --
    defaults to held_stack, same as collect below}.
    Plant-specific sugar over the generic collect mechanic
    (systems/containers.py::collect_item) -- harvest is scoped to a
    plant's own fruit container; maturity gating is implicit, since
    nothing to collect exists until systems/plants.py's tick_plants
    populates that container at the growing->mature transition."""
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_id)
    if not prop or not prop.get("plant_state"):
        return
    from systems.containers import collect_item
    collect_item(c, world, prop, dest_id=action.get("dest_id"))


def _route_collect(c, world, action):
    """action: {"type": "collect", "source_id": container_id,
    "item_id": optional specific item, "dest_id": optional carried/worn
    container to deposit into -- defaults to held_stack ("stacked in
    hand")}. Generic version of harvest above: source can be any
    container -- storage furniture, a bag/basket, a worn backpack, or a
    plant's fruit container (see systems/containers.py)."""
    source_id = action.get("source_id") or action.get("target_id") or action.get("target")
    if not source_id:
        return
    from systems.containers import resolve_container, collect_item
    source = resolve_container(c, world, source_id)
    if not source:
        return
    collect_item(c, world, source, item_id=action.get("item_id"), dest_id=action.get("dest_id"))


# =========================================================
# EXERCISE — see systems/exercise.py (fitness_level, injury risk,
# attractiveness bonus, all pre-existing but never wired to a real
# trigger until now) and systems/body_composition.py (calorie burn).
# Duration `_scaffold` activities, not instant -- exercise takes time,
# same as eat/sleep. jog/sit_ups need no target; chin_ups/lift_weights
# require a nearby prop whose template declares the matching anchor
# interaction (do_pull_ups / lift_weights) -- pull_up_bar and
# weight_bench already exist with exactly these anchors.
# =========================================================

_EXERCISE_REQUIRED_INTERACTION = {
    "chin_ups":     "do_pull_ups",
    "lift_weights": "lift_weights",
}
_EXERCISE_DURATION_TICKS = 1800

def _route_exercise_activity(c, world, action, activity_type):
    target_id = action.get("target")
    required_interaction = _EXERCISE_REQUIRED_INTERACTION.get(activity_type)
    if required_interaction:
        if not target_id:
            return
        from systems.props import get_prop_by_id
        prop = get_prop_by_id(world, target_id)
        if not prop:
            return
        tpl = world.get("definitions", {}).get("prop_templates", {}).get(prop.get("template"), {})
        if not any(a.get("interaction") == required_interaction for a in tpl.get("anchors", [])):
            return

    c["activity"] = _scaffold(
        c, world, activity_type,
        target_id=target_id,
        interaction=activity_type,
        duration=_EXERCISE_DURATION_TICKS,
    )


def _route_jog(c, world, action):
    _route_exercise_activity(c, world, action, "jog")


def _route_sit_ups(c, world, action):
    _route_exercise_activity(c, world, action, "sit_ups")


def _route_chin_ups(c, world, action):
    _route_exercise_activity(c, world, action, "chin_ups")


def _route_lift_weights(c, world, action):
    _route_exercise_activity(c, world, action, "lift_weights")


# =========================================================
# HOSTILE ACTIONS — see systems/hostile_actions.py. Individual
# resolvable acts (punch/kick/shove/grab/hold/threaten), each pre-
# resolved hit/evaded/fumble in advance, plus the target's own
# dodge/block defensive stances and turn_and_run flight response.
# =========================================================

def _route_hostile_action(c, world, action):
    """
    action: {"type": "punch"|"kick"|"shove"|"grab_offensive"|"hold"|
             "threaten", "target_id": other_id}
    """
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    target = world.get("characters", {}).get(target_id)
    if not target:
        return
    if c.get("building_id") != target.get("building_id"):
        return

    try:
        from systems.hostile_actions import resolve_hostile_action
        resolve_hostile_action(c, target, action["type"], world)
    except Exception:
        pass


def _route_steal_from(c, world, action):
    """
    action: {"type": "steal_from", "target_id": other_id, "method":
             "pickpocket"|"snatch"|"demand_at_knifepoint"|
             "demand_at_gunpoint"} -- see interaction_templates
    ["steal_from"] (a real, previously-dead entry) and
    systems/crime.py::resolve_steal_from() for the actual resolution.
    A gunpoint demand needs the actor to actually be holding a real
    firearm; falls back to knifepoint otherwise.
    """
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    target = world.get("characters", {}).get(target_id)
    if not target:
        return
    if c.get("building_id") != target.get("building_id"):
        return

    method = action.get("method", "pickpocket")
    if method == "demand_at_gunpoint":
        from systems.personal_items import get_item_by_template
        if not (get_item_by_template(c, "firearm") or get_item_by_template(c, "rifle")):
            method = "demand_at_knifepoint"

    try:
        from systems.crime import resolve_steal_from
        resolve_steal_from(c, target, method, world)
    except Exception:
        pass


def _route_dodge(c, world, action):
    """Brace to evade an incoming attack — see hostile_actions.py's
    _evasion_chance(), which only grants a bonus while this stance is
    fresh (DEFENSE_STANCE_WINDOW_TICKS)."""
    c["defense_stance"] = {"type": "dodge", "tick": world.get("tick", 0)}


def _route_block(c, world, action):
    """Brace to block an incoming attack — smaller evasion bonus than
    dodge but still consumed the same way."""
    c["defense_stance"] = {"type": "block", "tick": world.get("tick", 0)}


def _route_turn_and_run(c, world, action):
    """
    action: {"type": "turn_and_run", "target_id": aggressor_id}
    Panic flight — move to a point away from the aggressor. Kept
    intentionally minimal (no code exists anywhere for panic/flee
    movement today): just relocate, flag the panic state for narrative
    flavor, nothing scripted beyond that.
    """
    if _movement_blocked(c):
        return

    aggressor_id = action.get("target_id") or action.get("target")
    aggressor = world.get("characters", {}).get(aggressor_id) if aggressor_id else None

    cx, cy = c.get("x", 0), c.get("y", 0)
    if aggressor:
        dx, dy = cx - aggressor.get("x", cx), cy - aggressor.get("y", cy)
        dist = (dx ** 2 + dy ** 2) ** 0.5 or 1
        flee_x = cx + (dx / dist) * 10
        flee_y = cy + (dy / dist) * 10
    else:
        import random
        flee_x = cx + random.uniform(-10, 10)
        flee_y = cy + random.uniform(-10, 10)

    c["_panic_fleeing"] = {"from_id": aggressor_id, "tick": world.get("tick", 0)}
    if plan_character_route(world, c, flee_x, flee_y):
        c["animation_state"] = "run"
        c["is_moving"] = True


# =========================================================
# GRAPPLE — see systems/grapple.py. wrestle/overtake: a repeatable
# hold, not a single resolved exchange like the other hostile actions.
# =========================================================

def _route_wrestle(c, world, action):
    """
    action: {"type": "wrestle", "target_id": other_id}
    The initial grab is resolved exactly like grab_offensive (one
    hit/evaded/fumble roll against catch_and_hold) — only a landed grab
    starts the persistent multi-round hold.
    """
    if c.get("grappled_by") or c.get("grappling"):
        return  # already mid-grapple

    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    target = world.get("characters", {}).get(target_id)
    if not target:
        return
    if c.get("building_id") != target.get("building_id"):
        return

    try:
        from systems.hostile_actions import resolve_hostile_action
        from systems.grapple import start_grapple
        outcome = resolve_hostile_action(c, target, "catch_and_hold", world)
        if outcome == "hit":
            start_grapple(c, target, world)
    except Exception:
        pass


def _route_release_hold(c, world, action):
    """The holder's own choice to let go — see systems/grapple.py::release_hold."""
    try:
        from systems.grapple import release_hold
        release_hold(c, world)
    except Exception:
        pass


# =========================================================
# WEAPONS — see systems/hostile_actions.py's stab/knock branch and
# systems/health.py's apply_injury().
# =========================================================

def _route_wield_item(c, world, action):
    """
    action: {"type": "wield_item", "target_id": item_id}
    Move an item already in inventory (pocket, etc.) directly to
    location="held" — the only existing path to "held" was the awkward
    drop -> add_to_stack -> take_from_stack chain (see
    _route_take_from_stack); this is the generic equip action that chain
    never provided.
    """
    from systems.personal_items import get_item_by_id
    item_id = action.get("target_id") or action.get("target") or action.get("item_id")
    if not item_id:
        return
    item = get_item_by_id(c, item_id)
    if item:
        item["location"] = "held"


# =========================================================
# CHORE PROPOSAL HANDLERS — see systems/proposals.py
# =========================================================

def _route_propose_chore(c, world, action):
    """
    Character proposes doing a household chore together.
    action: {"type": "propose_chore", "chore_id": "laundry_load", "params": {...}}
    """
    chore_id = action.get("chore_id")
    if not chore_id:
        return
    params = action.get("params", {})
    try:
        from systems.proposals import propose_chore_to_household
        propose_chore_to_household(c, world, chore_id, params)
    except Exception:
        pass


def _route_respond_chore(c, world, action):
    """
    Character responds to a pending chore proposal — accept, decline, or
    counter with different params (the AI decides which details, if any,
    it has an opinion on).
    action: {"type": "respond_chore", "proposal_id": ..., "response": "accept"|"decline"|"counter", "counter_params": {...}}
    """
    proposal_id = action.get("proposal_id")
    response    = action.get("response", "accept")
    if not proposal_id:
        return
    counter_params = action.get("counter_params")
    try:
        from systems.proposals import respond
        respond(c, world, proposal_id, response, counter_params)
    except Exception:
        pass


def _route_advance_chore_round(c, world, action):
    """
    The proposer mediates a round of counter-proposals: optionally
    revises the chore's params, then re-opens still-countering recipients
    for another round (up to the round cap).
    action: {"type": "advance_chore_round", "proposal_id": ..., "new_params": {...}}
    """
    proposal_id = action.get("proposal_id")
    if not proposal_id:
        return
    new_params = action.get("new_params")
    try:
        from systems.proposals import proposer_advance_round
        proposer_advance_round(c, world, proposal_id, new_params)
    except Exception:
        pass


def _route_propose_social(c, world, action):
    """
    Character proposes something directly to another character — a favor,
    money, forgiveness, plans — the conversation-level counterpart to
    propose_chore, with no household/building gate (see
    systems/proposals.py::propose_social_ask()).
    action: {"type": "propose_social", "target": character_id, "ask": "...", "params": {...}}
    """
    target_id = action.get("target")
    ask = action.get("ask")
    if not target_id or not ask:
        return
    recipient = world.get("characters", {}).get(target_id)
    if not recipient:
        return
    params = action.get("params", {})
    try:
        from systems.proposals import propose_social_ask
        propose_social_ask(c, recipient, world, ask, params)
    except Exception:
        pass


def _route_propose_recurring(c, world, action):
    """
    Offer to turn a just-completed joint chore into a recurring social
    contract. Only valid if this household has a completed joint chore
    (2+ participants) waiting — see task_process.py::finish_process().
    action: {"type": "propose_recurring", "days": [...], "start_hour": ..., "end_hour": ...}
    """
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    last = household.get("_last_completed_chore")
    if not last or len(last.get("participants", [])) < 2:
        return

    chars = world.get("characters", {})
    participants = [chars[pid] for pid in last["participants"] if pid in chars]
    schedule_params = {
        "days":       action.get("days", ["monday"]),
        "start_hour": action.get("start_hour", 18),
        "end_hour":   action.get("end_hour", 19),
    }
    try:
        from systems.proposals import offer_recurring
        offer_recurring(c, participants, world, last["chore_id"], schedule_params)
        household["_last_completed_chore"] = None   # consumed
    except Exception:
        pass


def _route_propose_rule(c, world, action):
    """
    Character authors a standing policy about what they'll allow others
    to do -- see systems/social_rules.py. Not a two-party contract: the
    owner is the only party, the other side is simply expected to know
    the rule applies to them.
    action: {"type": "propose_rule", "topic": "borrow_car", "scope": "individual"|"household",
             "target": character_id (required if scope=="individual"),
             "default": "allow"|"deny", "priority": 50, "reason": "..."}
    """
    topic = action.get("topic")
    scope = action.get("scope")
    if not topic or scope not in ("individual", "household"):
        return
    try:
        from systems.social_rules import create_rule
        create_rule(
            c, topic, scope,
            target_id=action.get("target"),
            default=action.get("default", "allow"),
            priority=action.get("priority", 50),
            reason=action.get("reason", ""),
            world=world,
        )
    except Exception:
        pass


def _route_add_rule_exception(c, world, action):
    """
    Character carves an individual exception into one of their own
    existing household-scope rules -- e.g. "not Alex, not for two more
    weeks, they crashed it." No-ops if the owner has no household rule
    for this topic yet (the base rule must exist before it can be
    excepted).
    action: {"type": "add_rule_exception", "topic": "borrow_car", "target": character_id,
             "override": "allow"|"deny", "priority": 70, "reason": "...",
             "duration_ticks": optional int}
    """
    topic = action.get("topic")
    target_id = action.get("target")
    override = action.get("override")
    if not topic or not target_id or override not in ("allow", "deny"):
        return
    try:
        from systems.social_rules import add_exception
        add_exception(
            c, topic, target_id, override,
            priority=action.get("priority", 70),
            reason=action.get("reason", ""),
            duration_ticks=action.get("duration_ticks"),
            world=world,
        )
    except Exception:
        pass


def _route_propose_request(c, world, action):
    """
    Character asks someone (nearby or not) for something. Checked
    immediately against the recipient's own social_rules -- if a rule
    cleanly resolves it (allow/deny), this auto-responds on the
    recipient's behalf right away, no LLM turn needed on their side.
    If no rule matches, the proposal stays open for real negotiation,
    exactly like propose_social.
    action: {"type": "propose_request", "target": character_id, "topic": "borrow_car",
             "situation": "...", "urgency": 0-100}
    """
    target_id = action.get("target")
    topic = action.get("topic")
    situation = action.get("situation", "")
    if not target_id or not topic:
        return
    recipient = world.get("characters", {}).get(target_id)
    if not recipient:
        return
    urgency = action.get("urgency", 30)
    try:
        urgency = max(0, min(100, int(urgency)))
    except (TypeError, ValueError):
        urgency = 30

    try:
        from systems.proposals import propose_request, respond
        from systems.social_rules import resolve_request

        result = propose_request(c, recipient, world, topic, situation, urgency)
        proposal = result["proposal"]

        outcome, reason = resolve_request(recipient, c, topic, urgency, world)
        if outcome is None:
            # No standing rule matched -- fast-path auto-decline only the
            # clearly one-sided case (low urgency + genuinely worn out),
            # mirroring this file's other one-sided-only auto-resolves;
            # everything else still goes to the recipient's own LLM turn,
            # now informed by _build_proposal_context()'s favor-fatigue hint.
            from systems.favors import is_favor_worn_out
            if urgency < 40 and is_favor_worn_out(recipient, c["id"]):
                outcome, reason = "deny", "worn out from unreciprocated favors"
        if outcome in ("allow", "deny"):
            respond(recipient, world, proposal["id"], "accept" if outcome == "allow" else "decline")
            proposal["auto_resolved"] = True
            proposal["auto_resolution_reason"] = reason
    except Exception:
        pass


def _route_propose_item_loan(c, world, action):
    """
    Character asks someone to borrow one of their items for a while.
    Ownership never changes -- only possession, until returned or the
    loan's due date passes (systems/personal_items.py::
    recall_overdue_loans() then returns it automatically).
    action: {"type": "propose_item_loan", "target": character_id,
             "item_id": ..., "duration_days": 7}
    """
    target_id = action.get("target")
    item_id = action.get("item_id")
    if not target_id or not item_id:
        return
    owner = world.get("characters", {}).get(target_id)
    if not owner:
        return
    try:
        duration_days = max(1, int(action.get("duration_days", 7)))
    except (TypeError, ValueError):
        duration_days = 7

    from core.tick_schedule import TICK_RATE_SECONDS
    duration_ticks = round(duration_days * 86400 / TICK_RATE_SECONDS)

    try:
        from systems.proposals import propose_item_loan
        propose_item_loan(c, owner, world, item_id, duration_ticks)
    except Exception:
        pass


def _route_propose_item_sale(c, world, action):
    """
    Character asks whether someone will sell one of their items -- an
    open inquiry (no offer_price) invites the owner to counter with an
    asking price; offer_item_id proposes a trade instead of/alongside
    cash.
    action: {"type": "propose_item_sale", "target": character_id,
             "item_id": ..., "offer_price": optional, "offer_item_id": optional}
    """
    target_id = action.get("target")
    item_id = action.get("item_id")
    if not target_id or not item_id:
        return
    owner = world.get("characters", {}).get(target_id)
    if not owner:
        return
    try:
        from systems.proposals import propose_item_sale
        propose_item_sale(c, owner, world, item_id,
                           offer_price=action.get("offer_price"),
                           offer_item_id=action.get("offer_item_id"))
    except Exception:
        pass


def _route_post_social_media(c, world, action):
    """
    action: {"type": "post_social_media", "text": "...",
             "media_description": optional str, "tags": optional [str]}
    media_description becomes a photo post's description (see
    systems/social_media.py's module docstring for why this is
    descriptive metadata, not an actual rendered image).
    """
    text = action.get("text")
    if not text:
        return
    media = None
    if action.get("media_description"):
        media = {"kind": "photo", "description": action["media_description"], "subjects": [c["id"]]}
    try:
        from systems.social_media import create_post
        create_post(c, world, text, media=media, tags=action.get("tags"))
    except Exception:
        pass


def _route_like_social_post(c, world, action):
    post_id = action.get("post_id")
    if not post_id:
        return
    try:
        from systems.social_media import like_post
        like_post(c, world, post_id)
    except Exception:
        pass


def _route_unlike_social_post(c, world, action):
    post_id = action.get("post_id")
    if not post_id:
        return
    try:
        from systems.social_media import unlike_post
        unlike_post(c, world, post_id)
    except Exception:
        pass


def _route_comment_on_social_post(c, world, action):
    post_id = action.get("post_id")
    text = action.get("text")
    if not post_id or not text:
        return
    try:
        from systems.social_media import comment_on_post
        comment_on_post(c, world, post_id, text)
    except Exception:
        pass


# =========================================================
# CHILDCARE HANDLERS
# =========================================================

def _route_breastfeed(c, world, action):
    """Mother nurses the baby. Baby must be at the same location."""
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    characters = world.get("characters", {})
    baby = characters.get(target_id)
    if not baby:
        return
    # Validate: baby must be at same location
    if baby.get("current_location") != c.get("current_location"):
        return
    # Validate: mother must not be weaned
    bf = baby.get("breastfeeding_state", {})
    if bf.get("weaned"):
        return

    c["activity"] = _scaffold(c, world, "breastfeed",
                               target_id=target_id,
                               interaction="breastfeed",
                               duration=30)

    # Immediately apply feed (interaction resolves at completion in activities.py,
    # but we also apply on initiation so needs don't stay critical)
    try:
        from systems.baby import do_breastfeed
        do_breastfeed(baby, c, world)
    except Exception:
        pass


def _route_bottle_feed(c, world, action):
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    baby = world.get("characters", {}).get(target_id)
    if not baby or baby.get("current_location") != c.get("current_location"):
        return

    c["activity"] = _scaffold(c, world, "bottle_feed",
                               target_id=target_id,
                               interaction="bottle_feed",
                               duration=25)
    # Apply feed
    needs = baby.setdefault("baby_needs", {})
    needs["hunger"]  = min(1.0, needs.get("hunger",  0) + 0.65)
    needs["comfort"] = min(1.0, needs.get("comfort", 0) + 0.15)
    # Clear cry if needs are met
    if min(needs.values()) >= 0.30:
        baby["is_crying"] = False


def _route_hold_baby(c, world, action):
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    baby = world.get("characters", {}).get(target_id)
    if not baby or baby.get("current_location") != c.get("current_location"):
        return

    c["activity"] = _scaffold(c, world, "hold_baby",
                               target_id=target_id,
                               interaction="hold_baby",
                               duration=20)
    needs = baby.setdefault("baby_needs", {})
    needs["comfort"] = min(1.0, needs.get("comfort", 0) + 0.55)
    if needs.get("comfort", 0) >= 0.30:
        baby["is_crying"] = False


def _route_put_baby_in_carriage(c, world, action):
    """Place baby in carriage and set pushed_prop_id on the parent."""
    target_id  = action.get("target_id") or action.get("target")
    prop_id    = action.get("prop_id")
    if not target_id or not prop_id:
        return
    from systems.props import get_prop_by_id
    from systems.templates import get_prop_template

    baby = world.get("characters", {}).get(target_id)
    prop = get_prop_by_id(world, prop_id)
    if not baby or not prop:
        return

    tpl = get_prop_template(world, prop) or {}
    if not tpl.get("pushable"):
        return

    # Seat baby in carriage
    baby["in_carriage"]        = prop_id
    baby["current_location"]   = c.get("current_location")  # follows parent
    # Parent starts pushing
    c["pushed_prop_id"] = prop_id
    c["activity"] = _scaffold(c, world, "put_baby_in_carriage",
                               target_id=target_id,
                               interaction="put_baby_in_carriage",
                               duration=5)


# =========================================================
# CHILD CARE — see systems/child_care.py. Parent-initiated response to a
# child's need notification (tick_child_needs). Locality uses building_id,
# the one live-maintained spatial field this session's other locality gates
# all use (not current_location, which baby.py's routes above use but
# nothing else in the live schema populates).
# =========================================================

def _clear_parent_intention(parent, intent_type):
    parent["active_intentions"] = [
        i for i in parent.get("active_intentions", [])
        if i.get("type") != intent_type
    ]


def _route_feed_child(c, world, action):
    """Parent feeds a hungry child who can't cook for themselves."""
    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    child = world.get("characters", {}).get(target_id)
    if not child or child.get("building_id") != c.get("building_id"):
        return
    if not child.get("_awaiting_caregiver"):
        return

    body = child.setdefault("body", {})
    body["hunger"] = max(0.0, body.get("hunger", 0) - 60)
    child.pop("_awaiting_caregiver", None)
    _clear_parent_intention(c, f"feed_child_{child['id']}")


def _route_remind_child(c, world, action):
    """Parent reminds a child to handle a need the child can manage
    themselves (toilet/sleep) once prompted."""
    from brain.intentions import add_intention

    target_id = action.get("target_id") or action.get("target")
    if not target_id:
        return
    child = world.get("characters", {}).get(target_id)
    if not child or child.get("building_id") != c.get("building_id"):
        return
    awaiting = child.get("_awaiting_reminder")
    if not awaiting:
        return

    need = awaiting.get("need")
    if need == "clean_room":
        add_intention(child, {
            "type":     "clean_zone",
            "category": "chores",
            "priority": 70,   # higher than a self-driven clean_zone (45) -- a parent just asked directly
            "reason":   "your parent just reminded you to clean your room",
            "zone_key": awaiting.get("zone_key"),
        })
    else:
        prompt_type = "go_to_sleep" if need == "fatigue" else "go_to_toilet"
        add_intention(child, {
            "type":     prompt_type,
            "category": "survival",
            "priority": 90,
            "reason":   f"your parent just reminded you about {need}",
        })
    child.pop("_awaiting_reminder", None)
    _clear_parent_intention(c, f"remind_child_{child['id']}")


# =========================================================
# PHONE HANDLERS
# =========================================================

def _require_phone(c):
    """Return phone item if usable, else None."""
    from systems.personal_items import get_phone, phone_is_usable
    phone = get_phone(c)
    if not phone or not phone_is_usable(c):
        return None
    return phone


def _require_phone_or_computer(c, world):
    """Gate for "online action" routes (computer_* below) -- previously
    ungated entirely (any character could browse/email/job-search with
    no device at all). Usable phone takes priority (battery-checked,
    same as _require_phone); a computer (personal_items.py::get_computer)
    has no battery model yet, so just needs to exist. Returns True if
    either is available."""
    phone = _require_phone(c)
    if phone:
        return True
    from systems.personal_items import has_computer
    return has_computer(c, world)


# Ear-hold (calls) vs screen-tap (text/check/read) -- two distinct loops
# per the animation-loops round. Substituted to the seated variant when
# already sitting (posture.py's "sitting_seat"); phones, unlike computer
# use below, aren't inherently a desk activity so this only applies when
# actually seated, not unconditionally.
_SIT_ANIMATION_MAP = {
    "phone": "sit_phone", "phone_gesture": "sit_phone",
    "phone_screen": "sit_phone_screen",
}


def _set_phone_animation(c, interaction):
    """_scaffold() starts phone/computer activities at phase "using"
    directly, skipping the walking->using transition that's the only
    place get_phase_animation() would otherwise get called -- same fix
    _route_interact already applies for regular prop interactions."""
    anim = get_phase_animation(interaction, "using")
    if c.get("posture") == "sitting_seat":
        anim = _SIT_ANIMATION_MAP.get(anim, anim)
    c["animation_state"] = anim


def _set_computer_animation(c, world):
    """The computer_* routes below are gated by _require_phone_or_computer,
    which accepts a phone as a substitute when no computer prop exists --
    but they used to unconditionally play "sit_work" (a seated-at-a-desk
    pose) even when the character has no computer and is actually just
    holding a phone. Falls back to the same phone_screen/sit_phone_screen
    animation phone_send_text/phone_check/phone_read_text already use in
    that case."""
    from systems.personal_items import has_computer
    if has_computer(c, world):
        c["animation_state"] = "sit_work"
        return
    anim = "phone_screen"
    if c.get("posture") == "sitting_seat":
        anim = _SIT_ANIMATION_MAP.get(anim, anim)
    c["animation_state"] = anim


def _route_phone_call(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    phone["location"] = "held"
    target_id = action.get("target_id") or action.get("target")
    c["activity"] = _scaffold(c, world, "phone_call",
                               target_id=target_id, interaction="phone_call")
    _set_phone_animation(c, "phone_call")


def _route_phone_answer(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    phone["location"] = "held"
    c["activity"] = _scaffold(c, world, "phone_answer", interaction="phone_answer")
    _set_phone_animation(c, "phone_answer")


def _route_order_taxi(c, world, action):
    """Order a taxi, walk to the pickup spot, and wait for it -- see
    activities.py's "order_taxi" phase block (ordering ->
    walking_to_pickup -> waiting_for_taxi), which does the actual
    order_taxi_by_phone_call/_app call once the activity starts ticking."""
    act = _scaffold(c, world, "order_taxi", interaction="order_taxi")
    act["phase"] = "ordering"
    act["params"] = {
        "method":      action.get("method", "phone_app"),
        "destination": action.get("destination"),
    }
    c["activity"] = act


def _route_order_taxi_by_phone_call(c, world, action):
    """Call the taxi company -- see systems/rideshare.py::request_pickup.
    Orders one to c's current position; action may optionally give a
    "destination" {"x","y"}."""
    phone = _require_phone(c)
    if not phone:
        return
    phone["location"] = "held"
    from systems.rideshare import request_pickup
    request_pickup(c, world, {"x": c.get("x"), "y": c.get("y")},
                    method="taxi", destination=action.get("destination"))
    _set_phone_animation(c, "phone_call")


def _route_order_taxi_by_phone_app(c, world, action):
    """Order via a rideshare/taxi app on the smartphone -- same
    dispatch as the phone-call route, gated on the phone actually
    offering this app (see personal_items.py::can_do_phone_action)."""
    from systems.personal_items import can_do_phone_action
    if not can_do_phone_action(c, "order_taxi_by_phone_app"):
        return
    phone = _require_phone(c)
    if phone:
        phone["location"] = "held"
    from systems.rideshare import request_pickup
    request_pickup(c, world, {"x": c.get("x"), "y": c.get("y")},
                    method="taxi", destination=action.get("destination"))
    _set_phone_animation(c, "phone_app")


def _route_phone_send_text(c, world, action):
    """Threads into the real conversation system (brain/conversations.py)
    via apply_speech, medium="text" -- was previously calling
    systems/social.py::send_message() directly, a separate flat log that
    never touched conversations.py at all (no tone/turn-taking/
    reflections, and the recipient never saw it in
    build_active_conversations()). Works via a phone or a household
    computer (_require_phone_or_computer) -- "send texts via computer
    too, to represent other applications."""
    phone = _require_phone(c)
    if phone:
        phone["location"] = "held"
    elif not _require_phone_or_computer(c, world):
        return
    target_id = action.get("target_id") or action.get("target")
    message   = action.get("message", "")
    if target_id and message:
        speech = {
            "target":       target_id,
            "utterance":    message,
            "speech_act":   action.get("speech_act", "smalltalk"),
            "topic":        action.get("topic", "general"),
            "medium":       "text",
        }
        apply_speech(c, world, speech)
    c["activity"] = _scaffold(c, world, "phone_send_text", interaction="phone_send_text")
    _set_phone_animation(c, "phone_send_text")


def _route_phone_check(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    phone["location"] = "held"
    c["activity"] = _scaffold(c, world, "phone_check", interaction="phone_check")
    # Expose missed calls/messages count in activity data -- reads the
    # real shared inbox (systems/inbox.py); world["messages"] and
    # c["social"]["missed_calls"] were both permanently empty (nothing
    # ever wrote to either), so this always read 0 before.
    from systems.inbox import get_character_inbox, unread_count
    inbox = get_character_inbox(c)
    missed = unread_count(inbox, "voicemail")
    unread = unread_count(inbox)
    c["activity"]["phone_check_result"] = {"missed_calls": missed, "unread_messages": unread}
    _set_phone_animation(c, "phone_check")
    _maybe_notice_snooping(c, phone, world)


def _maybe_notice_snooping(c, phone, world):
    """~25% chance, once per snoop, that checking a phone someone else
    used while it was left out (systems/worries.py's check_device)
    raises this owner's suspicion of the snooper -- the other half of
    the "behavior-based trust cuts both ways" loop."""
    snooper_id = phone.get("_last_snooped_by")
    if not snooper_id:
        return
    phone["_last_snooped_by"] = None
    phone["_last_snooped_tick"] = None
    if random.random() < 0.25:
        from systems.worries import bump_suspicion
        snooper = world.get("characters", {}).get(snooper_id)
        bump_suspicion(
            c, snooper_id, 0.2, "phone_tampered",
            "your phone feels like someone's been using it"
            + (f" — maybe {snooper['name']}" if snooper else ""),
            world,
        )


def _route_phone_read_text(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    phone["location"] = "held"
    msg_id = action.get("message_id") or action.get("target")
    if msg_id:
        from systems.inbox import get_character_inbox
        for m in get_character_inbox(c):
            if m.get("id") == msg_id:
                m["read"] = True
    c["activity"] = _scaffold(c, world, "phone_read_text", interaction="phone_read_text")
    _set_phone_animation(c, "phone_read_text")


# Placeholder split for "assumed nobody would pick up, wrote an email
# instead" on purely-online businesses -- a flat constant for now, per
# the plan; a future refinement could weight this by how urgent the
# character's reason is instead of a coin flip.
_ONLINE_BUSINESS_EMAIL_SHORTCUT_CHANCE = 0.5


def _route_contact_business(c, world, action):
    """Generic customer-support contact -- deliveries, complaints, general
    questions, or a business someone was told to call back
    (waiting_for={"kind":"business",...}, see systems/waiting.py). Always
    lands as a message in the business's inbox; the real tailored
    response/excuse/solution is generated later by
    systems/business_support.py's background job during the business's
    phone hours, not synchronously here -- that's an LLM call, and this
    route runs inside a character's synchronous per-tick agent turn."""
    business_key = action.get("target")
    reason = action.get("reason", "")
    if not business_key:
        return

    from core.definitions import load_definitions
    defs = load_definitions("default")
    business = (defs.get("company_templates") or {}).get(business_key)
    if not business:
        return

    from systems.inbox import get_business_inbox, add_message as add_inbox_message
    tick = world.get("tick", 0)
    inbox = get_business_inbox(world, business_key)
    metadata = {"reason": reason, "caller_name": c.get("name") or c["id"]}

    if (business.get("presence") == "online"
            and random.random() < _ONLINE_BUSINESS_EMAIL_SHORTCUT_CHANCE):
        add_inbox_message(inbox, "email", c["id"], business_key, reason, tick, metadata)
        c["activity"] = _scaffold(c, world, "contact_business", interaction="contact_business", duration=60)
        return

    phone = _require_phone(c)
    if not phone:
        return

    from systems.business_hours import is_open
    kind = "call" if is_open(business, world, "phone") else "voicemail"
    add_inbox_message(inbox, kind, c["id"], business_key, reason, tick, metadata)

    c["activity"] = _scaffold(c, world, "contact_business", interaction="contact_business", duration=60)
    _set_phone_animation(c, "phone_call")


def _route_book_appointment(c, world, action):
    """Book a service-business appointment -- resolves immediately
    (deterministic slot pick, no LLM) if the business's phone line is
    currently open; otherwise falls through to a voicemail request,
    same as contact_business, for the background job to follow up on."""
    business_key = action.get("target")
    reason = action.get("reason", "")
    if not business_key:
        return

    from core.definitions import load_definitions
    defs = load_definitions("default")
    business = (defs.get("company_templates") or {}).get(business_key)
    if not business or business.get("business_kind") != "service":
        return

    phone = _require_phone(c)
    if not phone:
        return

    from systems.business_hours import is_open
    tick = world.get("tick", 0)

    if is_open(business, world, "phone"):
        from systems.appointments import book
        appt = book(c, world, business_key, business, reason)
        c["activity"] = _scaffold(c, world, "book_appointment", interaction="book_appointment", duration=60)
        c["activity"]["state"]["appointment"] = appt
    else:
        from systems.inbox import get_business_inbox, add_message as add_inbox_message
        add_inbox_message(
            get_business_inbox(world, business_key), "voicemail", c["id"], business_key,
            reason, tick,
            {"reason": reason, "wants_appointment": True, "caller_name": c.get("name") or c["id"]},
        )
        c["activity"] = _scaffold(c, world, "book_appointment", interaction="book_appointment", duration=60)

    _set_phone_animation(c, "phone_call")


def _route_check_device(c, world, action):
    """
    Character checks someone else's phone, left unattended, while
    suspicious of them (systems/worries.py). Reveals recent text/call/
    email conversation content via build_active_conversations() -- the
    real, live message store post phone-system-phase-2, NOT the flat
    world["messages"] log (that's only system notices like
    call_parent now). Phones only -- laptops have no stable per-item
    owner in this codebase today. Full gate re-validated here, not
    just trusted from build_available_actions() (owner could have
    walked back in between the action being offered and executed).
    action: {"type": "check_device", "target": item_id}
    """
    item_id = action.get("target")
    if not item_id:
        return
    item = world.get("placed_items", {}).get(item_id)
    if not item or item.get("object_type") != "phone":
        return
    owner_id = item.get("owner_id")
    if not owner_id or owner_id == c["id"]:
        return
    owner = world.get("characters", {}).get(owner_id)
    if not owner:
        return

    # Owner must actually be elsewhere -- "left it out of sight", not
    # just briefly out of arm's reach.
    phone_state = owner.get("phone_state") or {}
    loc = phone_state.get("last_known_location")
    if not loc or loc.get("prop_id") != item_id:
        return
    if owner.get("building_id") == loc.get("building_id"):
        return

    # Observer must physically be right here, near the phone.
    if c.get("building_id") != loc.get("building_id"):
        return
    d = abs(c.get("x", 0) - item.get("x", 0)) + abs(c.get("y", 0) - item.get("y", 0))
    if d > 3:
        return

    worry = c.get("worries", {}).get(owner_id)
    if not worry or worry.get("suspicion_level", 0) <= 0.3:
        return

    try:
        from brain.context_builder import build_active_conversations
        convs = [
            conv for conv in build_active_conversations(owner, world)
            if conv.get("medium") in ("text", "call", "email")
        ]
    except Exception:
        convs = []

    c["activity"] = _scaffold(c, world, "check_device", interaction="check_device")
    c["activity"]["snooped_conversations"] = convs[:3]

    item["_last_snooped_by"] = c["id"]
    item["_last_snooped_tick"] = world.get("tick", 0)


def _route_answer_about_pattern(c, world, action):
    """c (the person who was asked) answers -- writes into the ASKER's
    own tracked pattern (systems/behavior_patterns.py), found by c's id
    + the named activity. c's own LLM turn chooses the actual text,
    honest or not -- this just routes it into the right slot, and
    still says it out loud as a real conversational line."""
    asker_id = action.get("target")
    activity = action.get("activity")
    answer = action.get("answer", "")
    if not asker_id or not activity or not answer:
        return
    asker = world.get("characters", {}).get(asker_id)
    if not asker:
        return

    from systems.behavior_patterns import answer_pattern
    answer_pattern(asker, c["id"], activity, answer)

    apply_speech(c, world, {
        "target": asker_id, "speech_act": "supportive",
        "topic": "pattern_answer", "utterance": answer,
    })


def _route_check_computer_history(c, world, action):
    """
    Household computer has no stable single "owner" the way a phone does
    (see _route_check_device's own docstring) -- gated on household
    co-residency + physical proximity instead of owner-suspicion.
    Reveals systems/personal_items.py::get_computer()'s logged
    "states.history" entries (see activities.py's watch_porn completion
    hook). Discovering an entry nudges the discoverer's opinion of the
    viewer -- see systems/intimate_item_discovery.py's shared
    "creeped_out" effect.
    """
    from systems.personal_items import get_computer
    computer = get_computer(c, world)
    if not computer:
        return
    history = computer.get("states", {}).get("history", [])
    if not history:
        return

    d = abs(c.get("x", 0) - computer.get("x", c.get("x", 0))) + \
        abs(c.get("y", 0) - computer.get("y", c.get("y", 0)))
    if d > 3:
        return

    c["activity"] = _scaffold(c, world, "check_computer_history", interaction="check_computer_history")
    c["activity"]["computer_history"] = history[-5:]

    from systems.intimate_item_discovery import apply_creeped_out
    for entry in history[-5:]:
        viewer_id = entry.get("viewer")
        if viewer_id and viewer_id != c["id"]:
            apply_creeped_out(c, viewer_id, world)


def _route_form_theory(c, world, action):
    """
    Character voices a theory about what's going on with someone
    they're suspicious of -- deliberately the LLM's own judgment, not
    a system-generated guess, so it can be wrong (systems/worries.py).
    action: {"type": "form_theory", "target": subject_id, "false_belief": "...",
             "suspicion_of": optional other_char_id to blame instead}
    """
    subject_id = action.get("target")
    false_belief = action.get("false_belief")
    if not subject_id or not false_belief:
        return
    worry = c.get("worries", {}).get(subject_id)
    if not worry:
        return
    worry["false_belief"] = false_belief
    suspicion_of = action.get("suspicion_of")
    if suspicion_of:
        worry["suspicion_of"] = suspicion_of


def _co_present_characters(c, world):
    """Everyone else physically here right now -- room_id match
    preferred, building_id fallback -- mirrors
    core/event_handlers.py:159-163's same_room/same_building idiom.
    Used to broadcast an argument's effect to bystanders, not just the
    named target (see _route_make_argument)."""
    room_id = c.get("room_id")
    building_id = c.get("building_id")
    if not room_id and not building_id:
        return []
    result = []
    for other_id, other in world.get("characters", {}).items():
        if other_id == c["id"] or other.get("alive") is False:
            continue
        if room_id and other.get("room_id") == room_id:
            result.append(other)
        elif not room_id and building_id and other.get("building_id") == building_id:
            result.append(other)
    return result


def _relationship_credibility(listener, speaker_id):
    """0..1 -- how much weight this listener gives the speaker, blending
    trust and respect (same terms systems/influence.py's daily value-
    influence resolver uses for its own relationship-quality weight)."""
    rel = listener.get("relationships", {}).get(speaker_id, {})
    return max(0.0, min(1.0, (rel.get("trust", 0) + rel.get("respect", 0)) / 200.0))


def _topic_resistance(listener, relevant_values):
    """0..1 -- how hard this listener's OWN values make them to move on
    this topic (mirrors brain/beliefs.py's resistance=1-certainty
    concept, adapted: high personal importance in the topic's relevant
    value categories = harder to move)."""
    if not relevant_values:
        return 0.3  # mild default when the topic isn't tied to a known category
    values = listener.get("values", {})
    importances = [values.get(cat, {}).get("importance", 0.5) for cat in relevant_values]
    return sum(importances) / len(importances)


def _route_make_argument(c, world, action):
    """
    action: {"type": "make_argument", "target": character_id, "topic": "..."}

    Counters the target's last "argue" message on this topic if there's
    one live in their conversation, otherwise introduces a new
    supporting point for the speaker's own stance -- see
    llm/opinion_formation.py's argument_mode. Resolution (does anyone's
    opinion actually shift) runs independently per co-present listener,
    INCLUDING the named target, using THEIR OWN values/opinion state,
    never the speaker's -- "this goes for anyone in the room," scored
    and tested separately per character.
    """
    from brain.conversations import find_conversation
    from brain.opinions import get_current_opinion, update_opinion, shift_opinion
    from llm.opinion_formation import generate_opinion
    from llm.llm_gate import run_llm_call

    target_id = action.get("target")
    topic = action.get("topic")
    if not target_id or not topic:
        return
    target = world.get("characters", {}).get(target_id)
    if not target:
        return

    tick = world.get("tick", 0)

    conv = find_conversation(world, [c["id"], target_id])
    prior_argument = None
    argument_mode = "new_point"
    if conv:
        for msg in reversed(conv.get("history", [])):
            if msg.get("speech_act") == "argue" and msg.get("speaker") == target_id:
                prior_argument = msg.get("utterance")
                argument_mode = "counter"
                break

    session = c.setdefault("llm_session", {"history": []})
    context = {
        "reason":         f"Discussing this with {target.get('name', 'someone')}.",
        "prior_stance":   get_current_opinion(c, topic),
        "argument_mode":  argument_mode,
        "prior_argument": prior_argument,
        "speaker_name":   target.get("name"),
    }

    result = run_llm_call(generate_opinion(c, topic, context, world, session))
    if not result:
        return

    speaker_stance = result.get("stance", 0)
    relevant_values = result.get("relevant_values", [])
    update_opinion(
        c, topic, speaker_stance, result.get("confidence", 0.4),
        result.get("reasoning", ""), relevant_values, tick,
    )

    argument_text = (result.get("argument_text") or result.get("reasoning") or "").strip()
    if not argument_text:
        return
    argument_strength = max(0.0, min(1.0, result.get("argument_strength", 0.5)))

    # Threads into the real conversation + fires the speech bubble --
    # also what triggers apply_speech's own form_opinion scheduling for
    # any listener who doesn't have an opinion on this topic yet.
    apply_speech(c, world, {
        "target": target_id, "utterance": argument_text,
        "speech_act": "argue", "topic": topic,
    })

    for listener in _co_present_characters(c, world):
        listener_opinion = get_current_opinion(listener, topic)
        if listener_opinion is None:
            continue  # nothing to shift yet -- apply_speech above already
                      # scheduled them a form_opinion reflection
        credibility = _relationship_credibility(listener, c["id"])
        resistance = _topic_resistance(listener, relevant_values)
        persuasion = credibility * argument_strength * (1 - resistance)
        delta = (speaker_stance - listener_opinion["stance"]) * persuasion
        if delta == 0:
            continue
        shift_opinion(
            listener, topic, delta, tick,
            reasoning=f"Heard {c.get('name', 'someone')}'s argument.",
            relevant_values=relevant_values,
        )


def _route_retrieve_phone(c, world, action):
    """action: {"type": "retrieve_phone"}. Goes and re-acquires a phone
    that was set down (systems/phone.py::maybe_set_phone_down) or
    forgotten in another building -- same immediate-pickup shape as the
    pre-existing _route_pick_up_item (no distance/pathfinding gate
    there either), scaffolded as a short duration activity since this
    represents an actual "go find it" trip, not an instant action."""
    from systems.phone import ensure_phone_state
    state = ensure_phone_state(c)
    loc = state.get("last_known_location")
    if not loc:
        return
    c["activity"] = _scaffold(
        c, world, "retrieve_phone",
        target_id=loc.get("prop_id"),
        interaction="retrieve_phone",
        duration=_INTERACTION_DURATIONS.get("retrieve_phone", 300),
    )


# =========================================================
# DEVICE CHARGING
# =========================================================

def _route_charge_device(c, world, action):
    """
    Start charging. systems/power.py::charge_device() is called each tick
    by sim_loop while activity interaction == "charge", reading
    activity["device_item_id"] to know which item to charge and its
    matching charger (systems/power.py::CHARGER_BY_OBJECT_TYPE) --
    generalized from the old phone-only version so any battery-powered
    item (phone, laptop, ...) works the same way. Requires a matching
    charger in inventory AND the target actually being a wall_socket
    prop -- neither was checked at all before the phone round (any prop
    was accepted as a charging target).
    action: {"type": "charge", "target": wall_socket_prop_id,
             "device": optional item_id -- defaults to the phone}
    """
    from systems.personal_items import get_phone, get_item_by_id
    device_item_id = action.get("device")
    device = get_item_by_id(c, device_item_id) if device_item_id else get_phone(c)
    if not device:
        return
    from systems.power import find_charger_for
    if not find_charger_for(c, device):
        return

    target_prop_id = action.get("target") or action.get("prop_id")
    if not target_prop_id:
        return
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_prop_id)
    if not prop:
        return
    tpl = world.get("definitions", {}).get("prop_templates", {}).get(prop.get("template"), {})
    if "wall_socket" not in tpl.get("tags", []):
        return
    c["activity"] = _scaffold(c, world, "charge", target_id=target_prop_id,
                               interaction="charge",
                               duration=_INTERACTION_DURATIONS.get("charge", 60))
    c["activity"]["device_item_id"] = device["id"]


# =========================================================
# POSTURE
# =========================================================

def _route_sit_down(c, world, action):
    from systems.posture import set_posture
    from systems.props import get_prop_by_id
    from systems.occupancy import find_free_anchor, reserve_anchor

    target_id = action.get("target")
    c["activity"] = _scaffold(c, world, "sit_down_seat",
                               target_id=target_id,
                               interaction="sit_down_seat")
    set_posture(c, world, "sitting_seat")

    # Anchor onto the seat prop (if any) so the frontend snaps the
    # character's position/facing to the chair's anchor_sit node, the same
    # anchor-reservation dance _execute_use_seat() does for the queue-based
    # seating flow — see updateIK() in main.js, which reads c.seat_prop_id.
    prop = get_prop_by_id(world, target_id) if target_id else None
    if prop:
        anchor = find_free_anchor(prop, "sit")
        if anchor:
            reserve_anchor(c, prop, anchor)
        c["seat_prop_id"] = target_id


def _route_stand_up(c, world, action):
    from systems.posture import set_posture
    from systems.occupancy import release_anchor
    set_posture(c, world, "standing")
    release_anchor(c, world)
    c.pop("seat_prop_id", None)
    act = c.get("activity", {})
    if act.get("interaction") in ("sit_down_seat", "lie_down", "sleep"):
        c["activity"] = None


def _route_lie_down(c, world, action):
    from systems.posture import set_posture
    c["activity"] = _scaffold(c, world, "lie_down",
                               target_id=action.get("target"),
                               interaction="lie_down")
    set_posture(c, world, "lying")


def _route_lean_against_wall(c, world, action):
    """
    Lean against a nearby wall.

    Does NOT touch c["activity"] — ongoing conversations, negotiations,
    and touch proposals continue uninterrupted.
    """
    from systems.posture import set_posture
    from systems.walls import find_leanable_wall
    wall_id = action.get("target") or action.get("wall_id")
    if not wall_id:
        result = find_leanable_wall(c, world)
        if not result:
            return
        wall_id = result["wall_id"]
    set_posture(c, world, "leaning_wall")
    c["leaning_wall_id"] = wall_id


def _route_push_off_wall(c, world, action):
    """Stand back up from leaning — does not touch activity."""
    from systems.posture import set_posture
    set_posture(c, world, "standing")
    c["leaning_wall_id"] = None


# =========================================================
# TRANSPORT
# =========================================================

def _route_drive_car_to(c, world, action):
    destination = action.get("destination") or action.get("target")
    c["activity"] = _scaffold(c, world, "drive_car_to",
                               target_id=action.get("target"),
                               interaction="drive_car_to",
                               duration=_INTERACTION_DURATIONS.get("drive", 120))
    c["activity"]["destination"] = destination
    # Mark as offgrid so sim_loop can skip position updates
    c["offgrid"] = True
    c["offgrid_destination"] = destination


# =========================================================
# COMPUTER — generic scaffold
# =========================================================

def _route_computer(c, world, action, interaction_id):
    if not _require_phone_or_computer(c, world):
        return
    c["activity"] = _scaffold(c, world, interaction_id,
                               target_id=action.get("target"),
                               interaction=interaction_id)
    _set_computer_animation(c, world)


# ─── wikipedia research ───────────────────────────────────────────────────────

def _route_computer_wiki_research(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    keyword = action.get("keyword") or action.get("args", {}).get("keyword", "")
    c["activity"] = _scaffold(c, world, "computer_wiki_research",
                               interaction="computer_wiki_research")
    c["activity"]["research_keyword"] = keyword
    _set_computer_animation(c, world)

    if not keyword:
        return

    # Live Wikipedia API call — store result in character memory
    try:
        import urllib.request, urllib.parse, json as _json
        params  = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "extracts",
            "exintro": True, "explaintext": True, "redirects": True,
            "titles": keyword,
        })
        url = f"https://en.wikipedia.org/w/api.php?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Holosims/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
        pages = data.get("query", {}).get("pages", {})
        page  = next(iter(pages.values()), {})
        extract = (page.get("extract") or "")[:800]
        if extract:
            c.setdefault("knowledge", []).append({
                "topic":   keyword,
                "summary": extract,
                "tick":    world.get("tick", 0),
            })
            c["knowledge"] = c["knowledge"][-30:]
            c["activity"]["research_result"] = extract[:200]
    except Exception:
        pass   # silently ignore network failures in sim tick


# ─── news (see systems/curiosity.py -- only offered to curious characters) ────

def _route_computer_news(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    c["activity"] = _scaffold(c, world, "computer_news", interaction="computer_news")
    _set_computer_animation(c, world)

    curiosity_scale = c.get("curiosity", 50) / 100.0
    n_headlines = max(1, round(1 + curiosity_scale * 4))  # 1-5 headlines
    headlines = [n.get("headline") for n in world.get("news", [])[-n_headlines:] if n.get("headline")]
    if not headlines:
        return

    seen = c.setdefault("_seen_headlines", [])
    seen.extend(h for h in headlines if h not in seen)
    c["_seen_headlines"] = seen[-20:]
    c["activity"]["headlines"] = headlines


# ─── recurring news reading (physical newspaper / phone) ──────────────────────
# Distinct from computer_news above (one-shot headline dump from a
# desktop computer) -- these keep picking a fresh item every few minutes
# for as long as the activity continues, and can escalate into a real
# debate. See systems/reading_process.py.

def _route_read_newspaper(c, world, action):
    from systems.personal_items import get_item_by_template
    if not get_item_by_template(c, "newspaper"):
        return
    c["activity"] = _scaffold(c, world, "read_newspaper", interaction="read")
    from systems.reading_process import start_reading_news
    start_reading_news(c, world, medium="paper")


def _route_browse_news(c, world, action):
    if not _require_phone(c):
        return
    c["activity"] = _scaffold(c, world, "browse_news", interaction="phone")
    from systems.reading_process import start_reading_news
    start_reading_news(c, world, medium="phone")


# ─── job search / apply ───────────────────────────────────────────────────────

def _route_computer_job_search(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    listings = world.get("job_listings", [])
    c["activity"] = _scaffold(c, world, "computer_job_search", interaction="computer_job_search")
    c["activity"]["job_listings"] = listings[:10]
    _set_computer_animation(c, world)


def _route_computer_apply_for_job(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    from systems.jobs import apply_for_job
    job_id = action.get("job_id") or action.get("target")
    c["activity"] = _scaffold(c, world, "computer_apply_for_job",
                               interaction="computer_apply_for_job")
    _set_computer_animation(c, world)
    if job_id:
        apply_for_job(c, job_id, world)


# ─── email ────────────────────────────────────────────────────────────────────

def _route_computer_email(c, world, action):
    """Threads into the same conversation system as phone_send_text,
    medium="email" -- was previously its own disconnected list
    (world["emails"]), read by nothing else in the codebase (not even
    computer_check_email itself, which had zero data behavior beyond
    scaffolding the activity). Retired in favor of the same
    apply_speech/conversations.py path everything else now uses."""
    if not _require_phone_or_computer(c, world):
        return
    atype = action.get("type", "computer_check_email")
    c["activity"] = _scaffold(c, world, atype, interaction=atype)
    _set_computer_animation(c, world)

    if atype == "computer_send_email":
        to   = action.get("to", "")
        subj = action.get("subject", "")
        body = action.get("body", "")
        if to and body:
            speech = {
                "target":     to,
                "utterance":  body,
                "speech_act": action.get("speech_act", "smalltalk"),
                "topic":      subj or action.get("topic", "general"),
                "medium":     "email",
            }
            apply_speech(c, world, speech)

    elif atype in ("computer_check_email", "computer_respond_email"):
        # Surface email-medium threads waiting on a reply, mirroring
        # phone_check's missed-calls/unread pattern -- "unread" here is
        # "your_turn" (the other side sent the last message).
        from brain.context_builder import build_active_conversations
        email_threads = [
            conv for conv in build_active_conversations(c, world)
            if conv.get("medium") == "email"
        ]
        c["activity"]["email_threads"] = email_threads
        c["activity"]["unread_email_count"] = sum(
            1 for t in email_threads if t.get("your_turn")
        )


# ─── second-hand marketplace (systems/marketplace.py) ─────────────────────────
# Sims sell/buy household furniture props to/from each other. Reachable from
# phone or computer, same gating shape as every other online action above.

def _route_browse_second_hand_marketplace(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    from systems.marketplace import browse_listings
    listings = browse_listings(world, exclude_household_id=c.get("household_id"))
    c["activity"] = _scaffold(c, world, "browse_second_hand_marketplace",
                               interaction="browse_second_hand_marketplace")
    c["activity"]["marketplace_listings"] = listings
    _set_computer_animation(c, world)


def _route_sell_prop_item_second_hand(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    prop_id = action.get("prop_id") or action.get("target")
    if not prop_id:
        return
    asking_price = action.get("asking_price")
    from systems.marketplace import list_prop_for_sale
    listing = list_prop_for_sale(c, world, prop_id, asking_price=asking_price)
    c["activity"] = _scaffold(c, world, "sell_prop_item_second_hand",
                               interaction="sell_prop_item_second_hand")
    c["activity"]["listing"] = listing
    _set_computer_animation(c, world)


def _route_buy_prop_item_second_hand(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    listing_id = action.get("listing_id") or action.get("target")
    if not listing_id:
        return
    from systems.marketplace import buy_marketplace_listing
    result = buy_marketplace_listing(c, world, listing_id)
    c["activity"] = _scaffold(c, world, "buy_prop_item_second_hand",
                               interaction="buy_prop_item_second_hand")
    c["activity"]["purchase_result"] = result
    _set_computer_animation(c, world)


def _route_estimate_avg_sell_value(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    template_id = action.get("template_id") or action.get("target")
    if not template_id:
        prop_id = action.get("prop_id")
        prop = next((p for p in world.get("props", []) if p.get("id") == prop_id), None)
        template_id = prop.get("template") if prop else None
    if not template_id:
        return
    from systems.marketplace import estimate_avg_sell_value
    estimate = estimate_avg_sell_value(world, template_id)
    c["activity"] = _scaffold(c, world, "estimate_avg_sell_value",
                               interaction="estimate_avg_sell_value")
    c["activity"]["estimated_value"] = estimate
    _set_computer_animation(c, world)


# ─── darknet marketplace (systems/darknet.py) ──────────────────────────────────
# Reachable from phone or computer, same gating shape as the second-hand
# marketplace above.

def _route_browse_darknet_market(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    from systems.darknet import browse_darknet_listings
    listings = browse_darknet_listings(world, category=action.get("category"))
    c["activity"] = _scaffold(c, world, "browse_darknet_market",
                               interaction="browse_darknet_market")
    c["activity"]["darknet_listings"] = listings
    _set_computer_animation(c, world)


def _route_order_darknet_listing(c, world, action):
    if not _require_phone_or_computer(c, world):
        return
    listing_id = action.get("listing_id") or action.get("target")
    if not listing_id:
        return
    target_id = action.get("target_id")
    from systems.darknet import order_darknet_listing
    result = order_darknet_listing(c, world, listing_id, target_id=target_id)
    c["activity"] = _scaffold(c, world, "order_darknet_listing",
                               interaction="order_darknet_listing")
    c["activity"]["order_result"] = result
    _set_computer_animation(c, world)


# ─── diary (systems/diary.py) ──────────────────────────────────────────────────

def _route_write_diary(c, world, action):
    """A directly player/LLM-chosen write -- the automatic day-end
    version is systems/diary.py::maybe_write_diary(), same underlying
    generation function either way."""
    from systems.personal_items import get_item_by_template
    if not get_item_by_template(c, "diary"):
        return
    c["activity"] = _scaffold(c, world, "write_diary", interaction="write_diary")
    from systems.diary import write_diary_entry
    entry = write_diary_entry(c, world)
    c["activity"]["diary_entry"] = entry


# ─── stocks ───────────────────────────────────────────────────────────────────

def _route_computer_list_stocks(c, world, action):
    portfolio = c.get("portfolio", {})
    from systems.stock_market import get_stock_price
    summary = {}
    for ticker, pos in portfolio.items():
        price = get_stock_price(world, ticker)
        shares = pos.get("shares", 0)
        avg    = pos.get("avg_buy_price", price)
        summary[ticker] = {
            "shares": shares,
            "current_price": price,
            "avg_buy_price": avg,
            "gain_pct": round((price - avg) / avg * 100, 1) if avg else 0,
            "value": round(shares * price, 2),
        }
    c["activity"] = _scaffold(c, world, "computer_list_stocks",
                               interaction="computer_list_stocks")
    c["activity"]["portfolio"] = summary


def _route_computer_buy_stock(c, world, action):
    from systems.investments import buy_stock
    from systems.stock_market import get_stock_price
    ticker     = (action.get("ticker") or action.get("target", "")).upper()
    shares     = int(action.get("shares", 1))
    c["activity"] = _scaffold(c, world, "computer_buy_stock",
                               interaction="computer_buy_stock")
    if ticker:
        price      = get_stock_price(world, ticker)
        cash_amount = shares * price
        result     = buy_stock(c, world, ticker, cash_amount)
        c["activity"]["transaction_result"] = result


def _route_computer_sell_stock(c, world, action):
    from systems.investments import sell_stock
    ticker = (action.get("ticker") or action.get("target", "")).upper()
    shares = int(action.get("shares", 0)) or None
    c["activity"] = _scaffold(c, world, "computer_sell_stock",
                               interaction="computer_sell_stock")
    if ticker:
        result = sell_stock(c, world, ticker, shares)
        c["activity"]["transaction_result"] = result


def _route_computer_check_stock_value(c, world, action):
    from systems.stock_market import get_stock_price
    ticker = (action.get("ticker") or action.get("target", "")).upper()
    c["activity"] = _scaffold(c, world, "computer_check_stock_value",
                               interaction="computer_check_stock_value")
    if ticker:
        price = get_stock_price(world, ticker)
        c["activity"]["stock_price"] = {"ticker": ticker, "price": price}


# ─── order item / service ─────────────────────────────────────────────────────

def _route_computer_order_item(c, world, action):
    template_id = action.get("template_id") or action.get("target", "")
    quantity    = int(action.get("quantity", 1))
    c["activity"] = _scaffold(c, world, "computer_order_item",
                               interaction="computer_order_item")
    if template_id:
        # Use schedule_delivery_item via catalog_id lookup
        from systems.procurement import schedule_delivery_item
        household = world.get("households", {}).get(c.get("household_id"))
        if household:
            try:
                schedule_delivery_item(household, template_id, world)
                c["activity"]["order_result"] = {"success": True, "template_id": template_id}
            except Exception as e:
                c["activity"]["order_result"] = {"success": False, "error": str(e)}


def _route_computer_order_service(c, world, action):
    # service_id maps to service_type; use first subtype by default
    service_type = action.get("service_id") or action.get("service_type") or action.get("target", "")
    c["activity"] = _scaffold(c, world, "computer_order_service",
                               interaction="computer_order_service")
    if service_type:
        from systems.services import request_service
        # request_service(c, world, service_type, subtype, details, quantity=1)
        subtype = action.get("subtype", "")
        details = action.get("details", {})
        try:
            result = request_service(c, world, service_type, subtype, details)
            c["activity"]["service_result"] = result
        except Exception as e:
            c["activity"]["service_result"] = {"success": False, "error": str(e)}


def _route_computer_list_service_options(c, world, action):
    from data.services import SERVICE_CATALOG
    service_type = (action.get("service_type") or action.get("args", {}).get("service_type") or "").lower()
    c["activity"] = _scaffold(c, world, "computer_list_service_options",
                               interaction="computer_list_service_options")
    options = {}
    for sid, svc in SERVICE_CATALOG.items():
        if not service_type or service_type in sid or service_type in svc.get("category","").lower():
            options[sid] = {"name": svc.get("name", sid), "price": svc.get("price_per_hour", 0)}
    c["activity"]["service_options"] = options


# =========================================================
# UNIVERSAL ITEM ACTIONS
# =========================================================

def _route_drop_item(c, world, action):
    """Drop an item at the character's current position."""
    from systems.personal_items import drop_item, get_item_by_id, get_phone
    item_id = action.get("item_id") or action.get("target")
    if not item_id:
        return
    drop_item(c, item_id, world)


def _route_put_down_item(c, world, action):
    """Place an item at a specific position."""
    from systems.personal_items import place_item
    item_id = action.get("item_id") or action.get("target")
    x = int(action.get("x", c.get("x", 0)))
    y = int(action.get("y", c.get("y", 0)))
    if item_id:
        place_item(c, item_id, x, y, world)


def _route_give_item(c, world, action):
    """Give an item to another character."""
    from systems.personal_items import give_item
    item_id   = action.get("item_id") or action.get("item")
    target_id = action.get("target")
    receiver  = world.get("characters", {}).get(target_id)
    if item_id and receiver:
        give_item(c, receiver, item_id, world)


def _route_pick_up_item(c, world, action):
    """Pick up an item that is placed in the world."""
    from systems.personal_items import pick_up_item
    item_id = action.get("item_id") or action.get("target")
    if item_id:
        pick_up_item(c, item_id, world)


def _route_break_item(c, world, action):
    """Destroy an item — removes from inventory or world."""
    from systems.personal_items import break_item
    item_id = action.get("item_id") or action.get("target")
    if item_id:
        break_item(c, item_id, world)


# =========================================================
# ITEM STACK ACTIONS  (see systems/item_stack.py)
# =========================================================

def _route_add_to_stack(c, world, action):
    """Add a placed item to the character's held stack — rejected outright
    if the item's stack_position is 'not_stackable'."""
    from systems.item_stack import add_to_held_stack, play_item_action_once
    item_id = action.get("item_id") or action.get("target")
    if not item_id:
        return
    placed = world.setdefault("placed_items", {})
    item = placed.get(item_id)
    if not item or item.get("stack_position", "not_stackable") == "not_stackable":
        return
    del placed[item_id]
    item.pop("x", None)
    item.pop("y", None)
    item.pop("placed_by", None)
    item.pop("placed_at_tick", None)
    add_to_held_stack(c, item)
    play_item_action_once(c, world, "add_to_stack")


def _route_put_down_stack(c, world, action):
    """Break the stack apart — each item becomes an ordinary placed item
    at the character's current position."""
    from systems.item_stack import play_item_action_once
    stack = c.get("held_stack", [])
    if not stack:
        return
    x, y, tick = c.get("x", 0), c.get("y", 0), world.get("tick", 0)
    placed = world.setdefault("placed_items", {})
    for item in stack:
        item["location"]        = "placed"
        item["x"]               = x
        item["y"]               = y
        item["placed_by"]       = c.get("id")
        item["placed_at_tick"]  = tick
        placed[item["id"]] = item
    c["held_stack"] = []
    play_item_action_once(c, world, "put_down_stack")


def _route_search_stack(c, world, action):
    """Cosmetic only — no data mutation. Stack contents are already
    surfaced to the LLM via build_available_actions()'s held_stack_names
    (see context_builder.py); this is just the rummaging animation beat."""
    from systems.item_stack import play_item_action_once
    play_item_action_once(c, world, "search_stack")


def _route_take_from_stack(c, world, action):
    """Extract a specific item from the stack into the character's free
    hand — held there (location='held') until put down/given/pocketed."""
    from systems.item_stack import remove_from_held_stack, play_item_action_once
    from systems.personal_items import add_item
    item_id = action.get("item_id") or action.get("target")
    if not item_id:
        return
    item = remove_from_held_stack(c, item_id)
    if not item:
        return
    item["location"] = "held"
    add_item(c, item)
    play_item_action_once(c, world, "take_from_stack")


def _route_pocket_item(c, world, action):
    """Stow a location='held' item into the pocket — the 4th disposal path
    for an item taken from the stack (the other 3 — put down / give /
    place — already work unmodified via the existing item routes above,
    since they operate on any inventory item regardless of location)."""
    from systems.personal_items import get_item_by_id
    item_id = action.get("item_id") or action.get("target")
    if not item_id:
        return
    item = get_item_by_id(c, item_id)
    if item and item.get("location") == "held":
        item["location"] = "pocket"


# =========================================================
# SOCIAL EVENTS
# =========================================================

def _route_social_browse_events(c, world, action):
    """Discover events while browsing social media or scrolling phone."""
    from systems.social_events import maybe_discover_events
    channel = action.get("channel", "social_media")
    found   = maybe_discover_events(c, world, channel=channel)
    if found:
        c["last_discovered_events"] = found


def _route_social_event_rsvp(c, world, action):
    """RSVP to an event: yes / no / maybe."""
    from systems.social_events import rsvp, _hard_conflict
    event_id  = action.get("event_id") or action.get("args", {}).get("event_id")
    response  = action.get("response") or action.get("args", {}).get("response", "yes")
    decide_ts = action.get("decide_ts") or action.get("args", {}).get("decide_ts")
    if not (event_id and response in ("yes", "no", "maybe")):
        return
    if response == "yes":
        # One-sided fast-path override (see social_events.py
        # ::evaluate_attendance_tradeoff's docstring) -- mirrors
        # _route_social_event_attend's unaffordability check below.
        conflict = _hard_conflict(c, world)
        if conflict:
            response = "no"
            c.setdefault("notifications", []).append({
                "type": "event_conflict_declined", "event_id": event_id,
                "conflict": conflict, "ts": time.time(),
            })
    rsvp(c, world, event_id, response, decide_ts=decide_ts)


def _route_social_event_comment(c, world, action):
    """Comment or react to an event post."""
    from systems.social_events import add_comment, react_comment, get_event
    event_id = action.get("event_id") or action.get("args", {}).get("event_id")
    text     = action.get("text") or action.get("args", {}).get("text", "")
    reaction = action.get("reaction") or action.get("args", {}).get("reaction")
    if not event_id:
        return
    if text:
        add_comment(c, world, event_id, text)
    if reaction in ("like", "dislike"):
        evt = get_event(world, event_id)
        if evt and evt.get("comments"):
            idx = action.get("comment_idx", len(evt["comments"]) - 1)
            react_comment(c, world, event_id, idx, reaction)


def _route_social_event_attend(c, world, action):
    """Character attends an event — goes off-grid for the event duration."""
    from systems.social_events import get_event, rsvp, _hard_conflict
    event_id = action.get("event_id") or action.get("args", {}).get("event_id")
    if not event_id:
        return
    evt = get_event(world, event_id)
    if not evt or evt["status"] != "published":
        return
    conflict = _hard_conflict(c, world)
    if conflict:
        c.setdefault("notifications", []).append({
            "type": "event_conflict_declined", "event_id": event_id,
            "conflict": conflict, "ts": time.time(),
        })
        return
    cost = evt.get("cost_per_person", 0.0)
    if cost > 0:
        for item in c.get("inventory", []):
            if item.get("object_type") == "wallet":
                cash = item.get("cash", 0.0)
                if cash < cost:
                    c.setdefault("notifications", []).append({
                        "type": "event_cant_afford",
                        "event_id": event_id,
                        "title": evt["title"],
                        "cost": cost,
                        "ts": time.time(),
                    })
                    return
                item["cash"] = round(cash - cost, 2)
                break
    rsvp(c, world, event_id, "yes")
    # duration in ticks, not off_grid_until (a real timestamp nothing ever
    # read) -- process_return() only waits on return_tick.
    now            = time.time()
    end_ts         = evt.get("end_ts") or (evt.get("start_ts", now) + 3 * 3600)
    duration_ticks = max(1, int((end_ts - now) / TICK_RATE_SECONDS))
    send_offgrid(c, world, f"event:{event_id}", duration_ticks)


def _route_social_event_plan(c, world, action):
    """Create a new social event draft."""
    from systems.social_events import create_event_draft
    args = action.get("args") or action
    create_event_draft(
        c, world,
        title           = args.get("title", "My Event"),
        category        = args.get("category", "party"),
        description     = args.get("description", ""),
        location        = args.get("location", ""),
        location_type   = args.get("location_type", "venue"),
        start_ts        = args.get("start_ts"),
        end_ts          = args.get("end_ts"),
        co_organizers   = args.get("co_organizers") or [],
        max_attendees   = args.get("max_attendees"),
        cost_per_person = float(args.get("cost_per_person", 0.0)),
        min_age         = args.get("min_age"),
        max_age         = args.get("max_age"),
        popularity      = int(args.get("popularity", 50)),
        tags            = args.get("tags") or [],
        visible_to      = args.get("visible_to") or [],
    )

def _route_organize_hobby_session(c, world, action):
    """
    Character goes to computer or phone to organise a hobby session.
    Surfaces hobby-compatible contacts so the LLM can decide who to invite.
    This is the 'browsing/outreach' step before plan_hobby_session.
    """
    from systems.hobbies import find_hobby_contacts, inject_organize_intention
    hobby_id = action.get("hobby_id") or action.get("args", {}).get("hobby_id")
    if not hobby_id:
        return
    contacts = find_hobby_contacts(c, world, hobby_id, max_results=8)
    chars    = world.get("characters", {})
    c.setdefault("hobby_contacts_found", {})[hobby_id] = [
        {"id": cid, "name": chars[cid]["name"]}
        for cid in contacts if cid in chars
    ]


def _route_plan_hobby_session(c, world, action):
    """
    Create a social event for a group hobby session.
    Guests who share the hobby are invited first; if location_type==home
    and the event is published, guests will be spawned as temporary NPCs.
    """
    from systems.hobbies import plan_hobby_session
    hobby_id = (
        action.get("hobby_id")
        or action.get("args", {}).get("hobby_id")
    )
    start_offset = int(
        action.get("start_offset_hours")
        or action.get("args", {}).get("start_offset_hours", 48)
    )
    if hobby_id:
        plan_hobby_session(c, world, hobby_id, start_offset_hours=start_offset)
