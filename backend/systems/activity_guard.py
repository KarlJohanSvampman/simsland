"""
systems/activity_guard.py -- an activity that has to be finished is not replaced by a late answer from the model.

The model's answer comes back a minute or two after the question was asked (brain/cognition_actor.py), by which time the character
has often started something else on their own: the chore their intention called for. Applying the stale answer on top replaced the
chore a couple of minutes in, every time, so a five-minute "take out the trash" never ended (live: wash dishes, throw away trash,
take out trash, sit and relax, take out trash ... each cut off at exactly 120 ticks by the answer to an old question).

    defer_reason(c, world, action) -> a sentence saying what they keep doing and why, or None when the answer may go ahead

An activity is committed while it has time left and is a chore, upkeep, food, hygiene, errand or work activity, or is flagged not
interruptible. Leisure and the open-ended ones (sitting, relaxing) are never committed. An urgent need (an intention flagged
"interrupts": food at 88, a bladder at 95) always goes through, and so do the actions that do not start an activity at all (speech,
phone, proposals, looking around).
"""

COMMITTED_CATEGORIES = {"chore", "maintenance", "domestic", "food", "hygiene", "self_care", "errand", "errands", "work", "appearance"}
PASS_THROUGH_TYPES = {"speak", "wait", "examine", "look_around", "focus", "describe", "recall", "list_available_actions", "stand_up"}
PASS_THROUGH_PREFIXES = ("phone_", "respond_", "propose_", "advance_", "social_event_", "contact_", "book_appointment")
PASS_THROUGH_GROUPS = {"phone", "proposal", "social_event"}


def _config(act_type):
    from systems.activities import ACTIVITIES
    return ACTIVITIES.get(act_type) or {}


def committed_remaining(c, world):
    """(activity, ticks left) when the character is part way through something they should finish, else None."""
    act = c.get("activity")
    if not act or not act.get("type"):
        return None
    cfg = _config(act["type"])
    if cfg.get("interruptible", True) and cfg.get("category") not in COMMITTED_CATEGORIES:
        return None
    duration = act.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return None
    if act.get("phase") == "using":
        left = duration - (world.get("tick", 0) - act.get("phase_started_tick", 0))
    else:
        left = duration
    return (act, int(left)) if left > 0 else None


def _starts_an_activity(action):
    kind = str(action.get("type") or "")
    if kind in PASS_THROUGH_TYPES or kind.startswith(PASS_THROUGH_PREFIXES):
        return False
    from systems.action_registry import ACTION_SPECS
    group = (ACTION_SPECS.get(kind) or {}).get("group")
    return group not in PASS_THROUGH_GROUPS


def has_urgent_need(c):
    return any(i.get("interrupts") and (i.get("strength", 1) or 0) > 0 for i in c.get("active_intentions", []))


def defer_reason(c, world, action):
    held = committed_remaining(c, world)
    if not held or not action or not _starts_an_activity(action):
        return None
    if has_urgent_need(c):
        return None
    act, left = held
    doing = str(act["type"]).replace("_", " ")
    minutes = max(1, round(left / 60))
    return (f"Kept at {doing} (about {minutes} min left) instead of switching to {str(action.get('type')).replace('_', ' ')}: "
            f"it has to be finished first and nothing more urgent was open")
