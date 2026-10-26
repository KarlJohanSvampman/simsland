"""
systems/todo.py -- a character's intentions and expectations as one priority list.

What a character has to do (survival and health needs, the schedule, an expectation to meet, a child to look after) and what they
would like to do (a hobby, a creative outlet, time alone, a compliment, some gossip) are not the same kind of thing. The first are
PRESSING: they have to be attended to, in order, before anything else. The second are for WHEN THERE IS TIME: they are what a
character does once nothing pressing is open, and never instead of it. Expectations already appear among the active intentions
(`expectation:*`), so one list covers both.

    todo_list(c)       -> {"pressing": [intentions, most pressing first], "when_free": [intentions, most wanted first]}
    tier(i)            -> "pressing" | "when_free"

An intention is pressing when it is a survival, health or schedule matter; or a household, chore or social matter that is
important (priority >= PRESSING_PRIORITY) or that has already gone unanswered through a check-in (stage >= 1); anything else
(leisure, identity, impulse, and the less important rest) is for when there is time. The order inside each tier is the existing
brain/intentions.py::final_priority.
"""

from brain.intentions import final_priority

PRESSING_CATEGORIES = {"survival", "health", "schedule"}
CONDITIONAL_CATEGORIES = {"household", "chores", "social"}
PRESSING_PRIORITY = 70
PRESSING_TYPES = {"relieve_worry"}          # a worry that is crowding out their focus is seen to as a need, whatever its category


def tier(i):
    if i.get("type") in PRESSING_TYPES:
        return "pressing"
    category = i.get("category")
    if category in PRESSING_CATEGORIES:
        return "pressing"
    if category in CONDITIONAL_CATEGORIES and ((i.get("priority") or 0) >= PRESSING_PRIORITY or (i.get("stage") or 0) >= 1):
        return "pressing"
    return "when_free"


def todo_list(c):
    pressing, when_free = [], []
    for i in c.get("active_intentions", []):
        if (i.get("strength", 1) or 0) <= 0:
            continue
        (pressing if tier(i) == "pressing" else when_free).append(i)
    key = lambda i: -final_priority(i, c)
    return {"pressing": sorted(pressing, key=key), "when_free": sorted(when_free, key=key)}


def has_pressing(c):
    return any(tier(i) == "pressing" for i in c.get("active_intentions", []) if (i.get("strength", 1) or 0) > 0)
