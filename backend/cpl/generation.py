"""
cpl/generation.py -- how a turn is generated (docs/cpl_implementation_plan.md section 10, phase 5).

    choose_mode(world, c, block) -> "A" | "B" | "C"
        A  structured: no model call -- a factual question CPL can answer from the character's own state (where they
           are, what they're doing, whether they're home, whether they've eaten) AND nothing emotional about it: the
           question has no edge ("weren't you supposed to..."), they are not upset, they get on with the asker, and
           nothing else is waiting on them. Only when EVERY condition holds; anything uncertain is B.
        B  natural: the default -- one model call
        C  reasoning: a request or proposal waiting on them, a conflict, persuasion -- the full context matters
    structured_decision(world, c, block) -> a decision (brain/agent_loop.py's shape) answering in mode A, or None

The spec's own warning case -- "are you home? you were supposed to pick up the kids" -- is B (an edge), not A.
"""

import re

_FACTUAL = [
    ("where", re.compile(r"\bwhere (are|r) (you|u)\b|\bwhere you at\b", re.I)),
    ("doing", re.compile(r"\bwhat (are|r) (you|u) (doing|up to)\b|\bwhat'?s up\b", re.I)),
    ("home", re.compile(r"\b(are|r) (you|u) (at )?home\b", re.I)),
    ("eaten", re.compile(r"\b(have|did) (you|u) (eat(en)?|had (lunch|dinner|breakfast))\b", re.I)),
]
_EDGE = re.compile(r"supposed to|why (didn'?t|haven'?t|aren'?t|weren'?t)|you (never|always)|again\?|\bseriously\b|!",
                   re.I)
_UPSET = {"angry", "furious", "upset", "sad", "anxious", "scared", "hurt", "jealous", "ashamed", "humiliated"}


def _question_for_me(world, c, block):
    """The single open item waiting on c, if it is a question; else None."""
    from cpl import store
    conv = store.get(world, block.get("conversation_id"))
    if conv is None:
        return None, None
    mine = []
    for label, iid in (block.get("labels") or {}).items():
        if label.startswith("Q"):
            q = (conv.get("questions") or {}).get(iid) or {}
            if q.get("to_id") == c["id"]:
                mine.append((label, q))
        else:
            r = (world.get("cpl_requests") or {}).get(iid) or {}
            if r.get("recipient_id") == c["id"]:
                return None, conv                      # a request is waiting: not a mode-A turn
    return (mine[0] if len(mine) == 1 else None), conv


def choose_mode(world, c, block):
    if not block:
        return "B"
    from cpl import store
    conv = store.get(world, block.get("conversation_id")) or {}
    if conv.get("purpose") in ("conflict", "persuasion", "negotiation"):
        return "C"
    for label, iid in (block.get("labels") or {}).items():
        if not label.startswith("Q") and ((world.get("cpl_requests") or {}).get(iid) or {}).get("recipient_id") == c["id"]:
            return "C"
    item, _conv = _question_for_me(world, c, block)
    if item is None or block.get("interrupted") or block.get("winding_down"):
        return "B"
    label, q = item
    text = q.get("text") or ""
    kind = next((k for k, rx in _FACTUAL if rx.search(text)), None)
    if kind is None or _EDGE.search(text):
        return "B"
    mood = ((c.get("emotion") or {}).get("primary") or (c.get("mood") or {}).get("label") or "").lower()
    if mood in _UPSET or (c.get("stress") or 0) >= 60:
        return "B"
    rel = (c.get("relationships") or {}).get(q.get("asker_id")) or {}
    if (rel.get("trust", 0.5) or 0) < 0.2 or rel.get("grudge") or (c.get("grudges") or {}).get(q.get("asker_id")):
        return "B"
    if any(cl.get("status") == "disputed" for cl in (conv.get("claims") or {}).values()):
        return "B"
    return "A"


def _place(world, c):
    room = c.get("current_room") or c.get("room_name")
    if c.get("building_id"):
        home = c.get("home_building_id") or ((world.get("households") or {}).get(c.get("household_id")) or {}).get(
            "home_id")
        where = "at home" if home and home == c.get("building_id") else "inside"
        return f"{where}{', in the ' + str(room).replace('_', ' ') if room else ''}"
    return "outside"


def _answer(world, c, kind):
    act = (c.get("activity") or {}).get("type")
    doing = str(act).replace("_", " ") if act else "nothing much"
    if kind == "where":
        return f"I'm {_place(world, c)}."
    if kind == "doing":
        return "Not much, just taking it easy." if not act else f"Just {doing}."
    if kind == "home":
        at_home = _place(world, c).startswith("at home")
        return "Yes, I'm home." if at_home else f"No, I'm {_place(world, c)}."
    if kind == "eaten":
        hunger = (c.get("body") or {}).get("hunger", 50)
        return "Yes, I've eaten." if hunger < 40 else "Not yet, actually."
    return None


def structured_decision(world, c, block):
    """Mode A: the answer, as a decision, with no model call -- or None if this turn isn't mode A."""
    if choose_mode(world, c, block) != "A":
        return None
    item, conv = _question_for_me(world, c, block)
    label, q = item
    kind = next(k for k, rx in _FACTUAL if rx.search(q.get("text") or ""))
    line = _answer(world, c, kind)
    if not line:
        return None
    asker = ((world.get("characters") or {}).get(q.get("asker_id")) or {}).get("name") or ""
    return {"thought": "", "intention": None, "reflection": None,
            "action": {"type": "speak", "target_description": asker},
            "speech": {"utterance": line, "speech_act": "answer", "topic": "", "target": q.get("asker_id"),
                       "cpl": f"ANSWERS: {label} answer\nACT: statement\nNEXT: continue"},
            "cpl_mode": "A"}
