"""
systems/debug_log.py

Per the user's explicit ask: a visible, colored debug bubble above a
character's head whenever an action/activity/reaction actually executes,
completes, is interrupted, or times out -- green for actions/activities,
red for reactions, purple for violent/illegal ones -- gated by a
client-side settings toggle (default off, see main.js's _debugSettings).

Also commits a real (low-importance) memory entry for every event, per
the broader "store everything a character does" ask -- these are
routine execution-trace events, not a character's own notable
recollections, so they're kept out of brain/memory.py's importance-
ranked pool crowding anything meaningful out (low importance = first to
fall off store_memory()'s 150-entry cap).
"""

VIOLENT_OR_ILLEGAL_ACTIONS = {
    "steal_from", "wrestle", "release_hold",
    "order_darknet_listing", "browse_darknet_market",
    "confront", "apply_discipline",
}

VIOLENT_OR_ILLEGAL_ACTIVITIES = {
    "fight", "wrestle", "flee", "hostile_action", "use_toilet_bowels",
}


def _category_for_action(action_type, c=None):
    if action_type in VIOLENT_OR_ILLEGAL_ACTIONS:
        return "violation"
    if c and (c.get("job") or {}).get("illegal") and c.get("off_grid"):
        return "violation"
    return "action"


def _category_for_activity(activity_type):
    if activity_type in VIOLENT_OR_ILLEGAL_ACTIVITIES:
        return "violation"
    return "activity"


def log_debug_event(c, world, category, text):
    """category: "action" | "activity" | "reaction" | "violation" """
    text = (text or "").strip()
    if not text:
        return

    tick = world.get("tick", 0)
    c["current_debug_event"] = {
        "text":            text,
        "category":        category,
        "expires_at_tick": tick + 6,
    }

    from brain.memory import store_memory
    store_memory(
        c, text, importance=0.15,
        tags=["debug_event", category],
        kind="debug_event",
        tick=tick,
    )


def log_action(c, world, action_type, detail=""):
    category = _category_for_action(action_type, c)
    label = action_type.replace("_", " ")
    text = f"Action: {label}" + (f" ({detail})" if detail else "")
    log_debug_event(c, world, category, text)


def log_activity(c, world, activity_type, event):
    """event: "started" | "completed" | "interrupted" | "timed out" """
    category = _category_for_activity(activity_type)
    label = activity_type.replace("_", " ")
    log_debug_event(c, world, category, f"Activity {event}: {label}")


def log_reaction(c, world, reaction_type, detail=""):
    text = f"Reaction: {reaction_type.replace('_', ' ')}" + (f" ({detail})" if detail else "")
    log_debug_event(c, world, "reaction", text)
