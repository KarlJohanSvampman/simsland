"""
brain/plans.py

A character's THEN line -- what they mean to do next -- becomes intentions, one per step.

"try to talk to Kathleen and see if she wants to play, then think about how to actually apologize to Dad and make it
right" is two plans. It used to be matched as one: the whole line became the reason of whichever activity it happened to
match (live, 2026-11-01: an "apologize" intention whose reason was mostly about playing with Kathleen). Now each step
(brain/llm_brain.py::_then_steps) becomes its own intention:

  - a plan with someone, where the step names a character ("Kathleen", "Susan Moreau", or for a child "Dad"/"Mom"):
    play -> play_with_friend, call -> call_person, hang out -> hangout, talk/visit/see/ask -> visit_person,
    with that character as target_id;
  - anything else: the activity it matches (llm_brain._match_intention_type), as before -- "apologize", "take_shower";
    a person named in it still becomes its target ("apologize to Dad" -> Steven).

A step that matches neither gives no intention (free-text intention types pile up and resolve to nothing; see
_match_intention_type's docstring).
"""

import re

FIRST_PRIORITY = 40          # the immediate next plan (what a single THEN intention always got)
LATER_PRIORITY = 35          # the plans after it

# (pattern, intention type) for plans that are about a person -- only used when the step names one.
_PERSON_PLANS = (
    (r"\bplay(?:ing)?\b", "play_with_friend"),
    (r"\b(?:call|phone|ring)\b", "call_person"),
    (r"\b(?:hang out|spend time)\b", "hangout"),
    (r"\b(?:talk|chat|speak|visit|see|ask|tell|go (?:over )?to|check on|catch up)\b", "visit_person"),
)

_PARENT_WORDS = {
    "male": r"\b(?:dad|daddy|father|papa|pa)\b",
    "female": r"\b(?:mom|mommy|mum|mummy|mother|mama|ma)\b",
}


def _named_person(c, world, step):
    """The character a step names: a full or first name (longest first), or -- for a child or teen -- "Dad"/"Mom" as
    an adult of that sex in their own household."""
    text = f" {step.lower()} "
    chars = world.get("characters") or {}
    names = []
    for cid, o in chars.items():
        if cid == c.get("id") or o.get("alive") is False:
            continue
        for n in (o.get("name"), o.get("first_name")):
            if n:
                names.append((n.lower(), cid))
    for n, cid in sorted(names, key=lambda t: -len(t[0])):
        if re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", text):
            return cid
    if c.get("age_group") in ("child", "teen") or (c.get("age") or 99) < 18:
        household = (world.get("households") or {}).get(c.get("household_id")) or {}
        for sex, pattern in _PARENT_WORDS.items():
            if not re.search(pattern, text):
                continue
            adults = [chars[m] for m in household.get("members") or []
                      if m in chars and m != c.get("id") and chars[m].get("sex") == sex
                      and (chars[m].get("age") or 0) >= 18]
            if adults:
                return max(adults, key=lambda o: o.get("age") or 0)["id"]
    return None


# "ask Brenda for permission to make food", "ask Mom if I can make a sandwich": asking leave to feed yourself.
_ASK_LEAVE = re.compile(r"\b(?:ask|permission|allowed|okay|ok)\b|\bif i (?:can|could|may)\b|\bwhether i (?:can|could|may)\b")
_FOOD = re.compile(r"\b(?:food|eat|eating|cook|cooking|make (?:something|a|some|me|myself)|fix (?:something|a|me|myself)|"
                   r"snack|sandwich|meal|dinner|lunch|breakfast|kitchen|stove|oven|microwave|fridge|toast|noodles|pasta|"
                   r"cereal|soup|eggs?)\b")


def _asks_leave_to_eat(c, step):
    """Someone old enough to cook (systems/food_habits.can_cook: 13+) planning to ask leave to make themselves food. Live
    (2026-11): Carol (14) kept meaning to "ask Brenda for permission to make food"; the plan became a visit to Brenda, who
    didn't answer, and Carol stayed hungry. She doesn't need anyone's say-so: the plan is to eat."""
    from systems.food_habits import can_cook
    low = step.lower()
    return can_cook(c) and bool(_ASK_LEAVE.search(low)) and bool(_FOOD.search(low))


def intentions_from_plan(c, world, steps):
    """[intention, ...] for a THEN line's steps, in order (see the module docstring)."""
    from brain.llm_brain import _match_intention_type
    out, seen = [], set()
    for step in steps:
        if _asks_leave_to_eat(c, step):
            if "eat_food" not in seen and not any(i.get("type") == "eat_food" for i in c.get("active_intentions") or []):
                seen.add("eat_food")
                out.append({"type": "eat_food", "reason": "make myself something to eat", "source": "own_plan",
                            "priority": FIRST_PRIORITY if not out else LATER_PRIORITY})
            continue
        person = _named_person(c, world, step)
        kind = None
        if person:
            low = step.lower()
            kind = next((k for pattern, k in _PERSON_PLANS if re.search(pattern, low)), None)
            if kind == "play_with_friend" and kind in seen:
                kind = None
        kind = kind or _match_intention_type(step)
        if not kind or kind in seen:          # add_intention keeps one per type: the first step of a type wins
            continue
        seen.add(kind)
        intention = {"type": kind, "reason": step, "source": "own_plan",
                     "priority": FIRST_PRIORITY if not out else LATER_PRIORITY,
                     "category": "social" if person and kind in ("play_with_friend", "call_person", "hangout",
                                                                 "visit_person") else None}
        if intention["category"] is None:
            intention.pop("category")
        if person:
            intention["target_id"] = person
        out.append(intention)
    return out
