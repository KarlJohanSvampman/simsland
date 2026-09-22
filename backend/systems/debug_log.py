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


DEBUG_EVENT_DEDUPE_TICKS = 120


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


def _resolve_target_name(world, target_id):
    """A real, human-readable label for a target id -- a character's name,
    a prop's template name, or the raw id as a last resort -- so a memory/
    debug line reads as "Action: interact (fridge_a)" instead of a bare,
    unexplained "Action: interact". Per the user's explicit ask: every
    action/activity should carry its real target, not just its type."""
    if not target_id:
        return None
    chars = world.get("characters", {})
    if target_id in chars:
        return chars[target_id].get("name") or target_id
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_id)
    if prop:
        return (prop.get("template") or target_id).replace("_", " ")
    return target_id


def log_debug_event(c, world, category, text, target_id=None, target_name=None,
                    action_type=None, activity_type=None):
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

    # The same trace line firing several times inside a few seconds (an
    # activity started/completed/restarted in a loop) is one event to a
    # reader, not five memories all stamped with the same minute.
    last = c.setdefault("_debug_event_last", {})
    if tick - last.get(text, -10**9) < DEBUG_EVENT_DEDUPE_TICKS:
        return
    last[text] = tick
    if len(last) > 40:
        for k in sorted(last, key=last.get)[:20]:
            last.pop(k, None)

    # Structured fields alongside the text -- so the Memory tab can render a
    # real detail popup (target, action/activity type) instead of only the
    # flattened sentence, which is all the old version stored.
    extra = {}
    if target_id:
        extra["target_id"] = target_id
    if target_name:
        extra["target_name"] = target_name
    if action_type:
        extra["action_type"] = action_type
    if activity_type:
        extra["activity_type"] = activity_type

    from brain.memory import store_memory
    store_memory(
        c, text, importance=0.15,
        tags=["debug_event", category],
        kind="debug_event",
        tick=tick,
        **extra,
    )


def log_action(c, world, action_type, detail="", target_id=None):
    category = _category_for_action(action_type, c)
    label = action_type.replace("_", " ")
    target_name = _resolve_target_name(world, target_id)
    shown = detail or target_name
    text = f"Action: {label}" + (f" ({shown})" if shown else "")
    log_debug_event(c, world, category, text, target_id=target_id,
                    target_name=target_name, action_type=action_type)


def log_activity(c, world, activity_type, event, target_id=None):
    """event: "started" | "completed" | "interrupted" | "timed out" """
    category = _category_for_activity(activity_type)
    label = activity_type.replace("_", " ")
    target_name = _resolve_target_name(world, target_id)
    text = f"Activity {event}: {label}" + (f" ({target_name})" if target_name else "")
    log_debug_event(c, world, category, text, target_id=target_id,
                    target_name=target_name, activity_type=activity_type)


def log_reaction(c, world, reaction_type, detail=""):
    text = f"Reaction: {reaction_type.replace('_', ' ')}" + (f" ({detail})" if detail else "")
    log_debug_event(c, world, "reaction", text)
