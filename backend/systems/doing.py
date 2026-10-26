"""
systems/doing.py -- what a character is doing right now, in plain words.

Used where something checks in on a character -- an intention that has gone unanswered past its deadline records what they were
doing at that moment (brain/intentions.py::check_intention_deadlines), and the prompt then asks them why that was more important
(brain/context_builder.py::_sec_pressing_intentions).
"""

VERBS = {
    "sleep": "asleep", "nap": "napping", "work": "working", "eat": "eating", "drink_water": "getting a drink of water",
    "use_toilet": "in the bathroom", "use_toilet_bowels": "in the bathroom", "take_shower": "taking a shower",
    "brush_teeth": "brushing their teeth", "cook_recipe": "cooking", "roam": "wandering about", "jog": "out for a jog",
    "reflect": "lost in thought", "dust_and_wipe": "cleaning", "wait": "waiting around", "relax": "relaxing",
    "socialize": "talking", "watch_tv": "watching TV", "read": "reading", "check_on_kids": "checking on the kids",
    "computer_social_media": "scrolling social media", "work_type": "working at the computer", "meditate": "meditating",
    "homework": "doing homework", "play": "playing",
}


def _name(world, cid):
    c = (world.get("characters") or {}).get(cid)
    return (c or {}).get("name")


def describe_doing(c, world):
    """e.g. 'cooking at the kitchen counter', 'talking with Marta', 'away at school', 'doing nothing in particular'."""
    if c.get("off_grid"):
        reason = str(c.get("off_grid_reason") or "somewhere").replace("_", " ")
        return f"away ({reason})"
    act = c.get("activity") or {}
    kind = act.get("type")
    if kind:
        text = VERBS.get(kind, str(kind).replace("_", " "))
        other = _name(world, act.get("target_id"))
        if other and kind in ("socialize", "check_on_kids"):
            text = f"{text} with {other}" if kind == "socialize" else f"{text} ({other})"
        where = act.get("anchor_name")
        if where and kind not in ("sleep", "socialize"):
            text += f" at the {str(where).replace('_', ' ')}"
        return text
    if c.get("conversation"):
        return "in the middle of a conversation"
    if c.get("is_moving"):
        return "walking somewhere"
    room = str(c.get("room_id") or "").split(":")[-1].replace("_", " ")
    return "doing nothing in particular" + (f" in the {room}" if room else "")
