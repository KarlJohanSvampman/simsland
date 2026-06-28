# =========================================================
# ACTION ROUTER
# Translates LLM action + speech output into world state
# changes. Called from agent_loop.process_decision.
# =========================================================

import time

from systems.activities import get_phase_animation, get_clean_animation


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

    c["current_speech"] = {
        "utterance":      utterance,
        "speech_act":     speech.get("speech_act", "speak"),
        "topic":          speech.get("topic", ""),
        "target":         speech.get("target"),
        "expires_at_tick": tick + SPEECH_BUBBLE_TICKS,
    }

    # Store in conversation log too
    c.setdefault("speech_log", [])
    c["speech_log"].append({
        "tick":      tick,
        "utterance": utterance,
        "target":    speech.get("target"),
    })
    c["speech_log"] = c["speech_log"][-20:]   # keep last 20


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
    target_id = action.get("target")
    c["activity"] = _scaffold(
        c, world, "sleep",
        target_id=target_id,
        interaction="sleep",
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
    c["is_moving"] = True
    c["activity"] = act
    c["animation_state"] = "walk"


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

    # "call" / "text" are future — for now just log
    elif action_type in ("call", "text"):
        c.setdefault("pending_comms", []).append(action)

    # ── Hobby actions: run the planner first ──────────────
    # If the action maps to a hobby with requirements, build
    # the full prerequisite queue instead of starting directly.
    elif action_type in _HOBBY_ACTION_TYPES:
        _route_hobby(c, world, action_type)
        return  # planner sets c["activity_queue"]; queue processor takes it from here

    # Set animation state — specific handlers set their own; only fall back for generic types
    _NO_GENERIC_ANIM = {"interact", "examine", "search", "trash", "destroy",
                        "carry", "clean", "wear", "undress"}
    if action_type not in _NO_GENERIC_ANIM:
        anim = _ACTION_ANIMATION.get(action_type, "idle")
        c["animation_state"] = anim


# =========================================================
# HOBBY ROUTING
# =========================================================

from systems.hobby_requirements import ACTIVITY_TO_HOBBY

_HOBBY_ACTION_TYPES = set(ACTIVITY_TO_HOBBY.keys())


def _route_hobby(c, world, action_type):
    """Intercept a hobby action and run the prerequisite planner."""
    from systems.hobby_planner import plan_hobby

    hobby_name = ACTIVITY_TO_HOBBY.get(action_type)
    if not hobby_name:
        # No special requirements — fall through to direct start
        from systems.activities import start_activity
        start_activity(c, world, action_type)
        return

    # Clear any stale queue before planning
    if not c.get("activity_queue"):
        queued = plan_hobby(c, world, hobby_name)
        if not queued:
            # Planner couldn't build queue (e.g. missing prop); desires already added
            pass
