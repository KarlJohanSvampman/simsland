# =========================================================
# ACTION ROUTER
# Translates LLM action + speech output into world state
# changes. Called from agent_loop.process_decision.
# =========================================================

import time

from systems.activities import get_phase_animation


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

    # "call" / "text" are future — for now just log
    elif action_type in ("c