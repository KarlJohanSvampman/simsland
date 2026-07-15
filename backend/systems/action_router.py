# =========================================================
# ACTION ROUTER
# Translates LLM action + speech output into world state
# changes. Called from agent_loop.process_decision.
# =========================================================

import time
import random

from systems.activities import get_phase_animation, get_clean_animation
from systems.navigation import plan_character_route


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

    c["current_speech"] = {
        "utterance":      utterance,
        "speech_act":     speech_act,
        "topic":          topic,
        "target":         target_id,
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

    if listener:

        from brain.conversations import get_or_create_conversation, add_message
        from systems.reactions import push_conversation_reaction
        from brain.relationships import apply_interaction
        from systems.conversation_analysis import analyze_message, should_schedule_reflection

        conv = get_or_create_conversation(
            world, c["id"], target_id, topic=topic or "general"
        )

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

        if should_schedule_reflection(result):
            listener.setdefault("pending_reflections", []).append({
                "type":           "conversation",
                "target_id":      c["id"],
                "reason":         speech_act,
                "scheduled_tick": tick + random.randint(50, 300),
                "observations":   result.get("observations", []),
            })


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

def _route_move(c, world, action):
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
            c["animation_state"] = "walk"
            c["is_moving"]       = True
        return

    props = world.get("props", {})
    if target_id in props:
        p = props[target_id]
        c["move_target"] = {
            "x": p.get("x", 0),
            "y": p.get("y", 0),
            "target_id": target_id,
            "target_type": "prop",
        }
        if plan_character_route(world, c, p.get("x", 0), p.get("y", 0)):
            c["animation_state"] = "walk"
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
# ROUTE WAIT
# =========================================================

def _route_wait(c, world, action):
    ticks = action.get("duration", 120)
    c["activity"] = _scaffold(
        c, world, "wait",
        interaction="wait",
        duration=ticks,
    )


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
    from systems.prop_movement import get_move_capacity, play_prop_action_once

    target_id = action.get("target")
    if not target_id:
        return
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return
    if get_move_capacity(prop) not in (1, 2):
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

def route_action(c, world, action, speech, definitions=None):
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

    elif action_type == "wait":
        _route_wait(c, world, action)

    elif action_type == "work":
        c["activity"] = _scaffold(c, world, "work", interaction="work")

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
    elif action_type == "phone_send_text":
        _route_phone_send_text(c, world, action)
    elif action_type in ("phone_check", "call", "text"):
        _route_phone_check(c, world, action)
    elif action_type == "phone_read_text":
        _route_phone_read_text(c, world, action)

    # ── Computer ───────────────────────────────────────────────────────────────
    elif action_type == "computer_social_media":
        _route_computer(c, world, action, "computer_social_media")
    elif action_type == "computer_videos":
        _route_computer(c, world, action, "computer_videos")
    elif action_type == "computer_game":
        _route_computer(c, world, action, "computer_game")
    elif action_type == "computer_wiki_research":
        _route_computer_wiki_research(c, world, action)
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
    elif action_type in ("grab_offensive", "hold", "punch", "kick", "shove", "threaten"):
        _route_hostile_action(c, world, action)
    elif action_type == "dodge":
        _route_dodge(c, world, action)
    elif action_type == "block":
        _route_block(c, world, action)
    elif action_type == "turn_and_run":
        _route_turn_and_run(c, world, action)

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

    elif action_type == "breastfeed":
        _route_breastfeed(c, world, action)
    elif action_type == "bottle_feed":
        _route_bottle_feed(c, world, action)
    elif action_type == "hold_baby":
        _route_hold_baby(c, world, action)
    elif action_type == "put_baby_in_carriage":
        _route_put_baby_in_carriage(c, world, action)

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


# Incident type → (emergency call type, default report text). Mirrors the
# mapping auto_report_incidents() (systems/emergency.py) already uses for
# domestic_disturbance/injury; extended here with assault/fire so a
# character-initiated call knows what to say for the new incident types
# this round adds.
_INCIDENT_CALL_TYPE = {
    "domestic_disturbance": ("police",  "There is a serious disturbance."),
    "assault":              ("police",  "Someone was just physically attacked."),
    "crime":                ("police",  "A crime is in progress."),
    "injury":               ("medical", "Someone is injured and needs help."),
    "fire":                 ("fire",    "There's a fire!"),
}


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

    emergency_type, report = _INCIDENT_CALL_TYPE.get(
        incident.get("type"), ("police", "There's an emergency.")
    )

    try:
        from systems.emergency import create_911_call
        create_911_call(world, c, emergency_type, report, incident_id=incident["id"])
        incident["reported"] = True
    except Exception:
        pass


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
# PHONE HANDLERS
# =========================================================

def _require_phone(c):
    """Return phone item if usable, else None."""
    from systems.personal_items import get_phone, phone_is_usable
    phone = get_phone(c)
    if not phone or not phone_is_usable(c):
        return None
    return phone


def _route_phone_call(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    target_id = action.get("target_id") or action.get("target")
    c["activity"] = _scaffold(c, world, "phone_call",
                               target_id=target_id, interaction="phone_call")


def _route_phone_answer(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    c["activity"] = _scaffold(c, world, "phone_answer", interaction="phone_answer")


def _route_phone_send_text(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    target_id = action.get("target_id") or action.get("target")
    message   = action.get("message", "")
    if target_id and message:
        from systems.social import send_message
        target = world.get("characters", {}).get(target_id)
        if target:
            send_message(c, target, message, world)
    c["activity"] = _scaffold(c, world, "phone_send_text", interaction="phone_send_text")


def _route_phone_check(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    c["activity"] = _scaffold(c, world, "phone_check", interaction="phone_check")
    # Expose missed calls/messages count in activity data
    missed = len(c.get("social", {}).get("missed_calls", []))
    unread = sum(1 for m in world.get("messages", [])
                 if m.get("to_id") == c["id"] and not m.get("read"))
    c["activity"]["phone_check_result"] = {"missed_calls": missed, "unread_messages": unread}


def _route_phone_read_text(c, world, action):
    phone = _require_phone(c)
    if not phone:
        return
    msg_id = action.get("message_id") or action.get("target")
    if msg_id:
        for m in world.get("messages", []):
            if m.get("id") == msg_id and m.get("to_id") == c["id"]:
                m["read"] = True
    c["activity"] = _scaffold(c, world, "phone_read_text", interaction="phone_read_text")


# =========================================================
# DEVICE CHARGING
# =========================================================

def _route_charge_device(c, world, action):
    """
    Start charging. The phone.charge_phone() is called each tick by phone.py
    while activity interaction == "charge". Requires phone_charger in inventory.
    """
    from systems.personal_items import has_item_template
    if not has_item_template(c, "phone_charger"):
        return
    target_prop_id = action.get("target") or action.get("prop_id")
    c["activity"] = _scaffold(c, world, "charge", target_id=target_prop_id,
                               interaction="charge",
                               duration=_INTERACTION_DURATIONS.get("charge", 60))


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
    c["activity"] = _scaffold(c, world, interaction_id,
                               target_id=action.get("target"),
                               interaction=interaction_id)


# ─── wikipedia research ───────────────────────────────────────────────────────

def _route_computer_wiki_research(c, world, action):
    keyword = action.get("keyword") or action.get("args", {}).get("keyword", "")
    c["activity"] = _scaffold(c, world, "computer_wiki_research",
                               interaction="computer_wiki_research")
    c["activity"]["research_keyword"] = keyword

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


# ─── job search / apply ───────────────────────────────────────────────────────

def _route_computer_job_search(c, world, action):
    listings = world.get("job_listings", [])
    c["activity"] = _scaffold(c, world, "computer_job_search", interaction="computer_job_search")
    c["activity"]["job_listings"] = listings[:10]


def _route_computer_apply_for_job(c, world, action):
    from systems.jobs import apply_for_job
    job_id = action.get("job_id") or action.get("target")
    c["activity"] = _scaffold(c, world, "computer_apply_for_job",
                               interaction="computer_apply_for_job")
    if job_id:
        apply_for_job(c, job_id, world)


# ─── email ────────────────────────────────────────────────────────────────────

def _route_computer_email(c, world, action):
    atype = action.get("type", "computer_check_email")
    c["activity"] = _scaffold(c, world, atype, interaction=atype)
    if atype == "computer_send_email":
        # Queue email as a world message
        to   = action.get("to", "")
        subj = action.get("subject", "")
        body = action.get("body", "")
        world.setdefault("emails", []).append({
            "from_id":  c["id"],
            "to":       to,
            "subject":  subj,
            "body":     body,
            "tick":     world.get("tick", 0),
            "read":     False,
        })


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
    from systems.social_events import rsvp
    event_id  = action.get("event_id") or action.get("args", {}).get("event_id")
    response  = action.get("response") or action.get("args", {}).get("response", "yes")
    decide_ts = action.get("decide_ts") or action.get("args", {}).get("decide_ts")
    if event_id and response in ("yes", "no", "maybe"):
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
    import time
    from systems.social_events import get_event, rsvp
    event_id = action.get("event_id") or action.get("args", {}).get("event_id")
    if not event_id:
        return
    evt = get_event(world, event_id)
    if not evt or evt["status"] != "published":
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
    c["off_grid"]       = True
    c["off_grid_reason"] = f"event:{event_id}"
    c["off_grid_until"] = evt.get("end_ts") or (evt.get("start_ts", time.time()) + 3 * 3600)


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
