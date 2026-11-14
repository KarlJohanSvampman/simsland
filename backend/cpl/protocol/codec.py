"""
cpl/protocol/codec.py -- the model's compact lines <-> structured decisions (docs/cpl_implementation_plan.md
section 6.1, C3).

The model writes a few short lines; CPL builds everything else. It never sees or writes an id: open items are shown
as labels (Q1 a question, R1 a request, P1 a proposal), mapped back here.

    labels(world, conv)                 {"Q1": question id, "R1": request id, ...} for the items still open
    parse_turn(text, labels)            -> (TurnDecision dict, errors)
    parse_initiate(text)                -> (InitiateIntent dict, errors)
    fallback(decision)                  what an invalid turn becomes after the one corrective retry: its line, as a
                                        plain statement, answering nothing -- never an invented accept or reject
                                        (spec invariant 16); a NEXT that parsed (leave, pause) still stands
    to_event(decision, character_id)    the state-machine event for it (cpl/state_machine.py)

Turn:
    ANSWERS: R1 conditional      <label> accept|reject|counter|conditional|defer|clarify|partial|acknowledge|answer|
                                 cant_answer
    ACT: statement               statement|question|request|proposal|argument|feeling
    STANCE: reluctant
    FEELING: tired 0.3
    SAY: You can take it, but have it back before midnight.
    CONDITION: back before midnight          (with conditional / counter)
    NEXT: continue               continue | wrap_up | leave:<excuse|angry|busy> | pause | let_join:<name>

Initiate:
    TALK_TO: Ana    PURPOSE: request    ABOUT: borrow the car    APPROACH: friendly    FEELING: anxious 0.4
    SAY: ...  (optional)    CHANNEL: call  (only when not face to face)
"""

import re

from cpl.model.enums import Channel, Purpose, ResponseType

ACTS = {"statement", "question", "request", "proposal", "argument", "feeling"}
ACT_TO_TYPE = {"statement": "statement", "question": "question", "request": "request", "proposal": "proposal",
               "argument": "argument", "feeling": "emotional_statement"}
NEXT_SIMPLE = {"continue", "wrap_up", "pause"}
LEAVE_REASONS = {"excuse", "angry", "busy"}
APPROACHES = {"friendly", "direct", "careful", "urgent", "hostile"}
_LINE = re.compile(r"^\s*([A-Z_]+)\s*:\s*(.*?)\s*$")
_FEELING = re.compile(r"^([a-zA-Z_ -]+?)\s*(?:\(?\s*([01](?:\.\d+)?|\.\d+)\s*\)?)?$")


def labels(world, conv):
    """Q1.. / R1.. / P1.. for the conversation's open items, in the order they were raised."""
    out = {}
    items = conv.get("open_items") or {}
    for prefix, key in (("Q", "questions"), ("R", "requests"), ("P", "proposals")):
        for n, iid in enumerate(items.get(key) or [], 1):
            out[f"{prefix}{n}"] = iid
    return out


def _fields(text):
    out = {}
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if m:
            key, val = m.group(1).upper(), m.group(2).strip().strip('"')
            if key == "SAY" and "SAY" in out:          # a second SAY line continues the first
                out["SAY"] += " " + val
            else:
                out.setdefault(key, val)
    return out


def _feeling(val):
    if not val:
        return None
    m = _FEELING.match(val.strip())
    if not m:
        return {"primary": val.strip().lower(), "intensity": 0.5}
    return {"primary": m.group(1).strip().lower(), "intensity": max(0.0, min(1.0, float(m.group(2)))) if m.group(2)
            else 0.5}


def parse_turn(text, label_map):
    f = _fields(text)
    errors = []
    d = {"answers": None, "act": None, "stance": (f.get("STANCE") or "").lower() or None,
         "emotion": _feeling(f.get("FEELING")), "say": f.get("SAY") or None,
         "condition": f.get("CONDITION") or None, "next": {"action": "continue"}}

    act = (f.get("ACT") or "statement").lower()
    if act not in ACTS:
        errors.append(f"ACT must be one of {sorted(ACTS)}, not {act!r}")
        act = "statement"
    d["act"] = act
    d["message_type"] = ACT_TO_TYPE[act]

    if f.get("ANSWERS"):
        parts = f["ANSWERS"].split()
        label = parts[0].upper().rstrip(",:") if parts else ""
        rtype = parts[1].lower() if len(parts) > 1 else ""
        if label not in label_map:
            errors.append(f"ANSWERS names {label!r}, which is not open (open: {sorted(label_map) or 'nothing'})")
        elif rtype not in {r.value for r in ResponseType}:
            errors.append(f"ANSWERS {label}: {rtype!r} is not an answer")
        else:
            d["answers"] = {"label": label, "item_id": label_map[label], "response_type": rtype}
            if rtype in ("conditional", "counter") and not d["condition"]:
                errors.append(f"{rtype} needs a CONDITION line")
            if rtype in ("conditional", "counter"):
                d["answers"]["condition"] = d["condition"]

    if act in ("request", "proposal", "question") and not d["say"]:
        errors.append(f"ACT {act} needs a SAY line saying what is asked")

    nxt = (f.get("NEXT") or "continue").strip().lower()
    if nxt in NEXT_SIMPLE:
        d["next"] = {"action": nxt}
    elif nxt.startswith("leave"):
        reason = nxt.split(":", 1)[1].strip() if ":" in nxt else "excuse"
        if reason not in LEAVE_REASONS:
            errors.append(f"leave:{reason} -- the reason is excuse, angry or busy")
            reason = "excuse"
        d["next"] = {"action": "leave", "reason": reason}
    elif nxt.startswith("let_join"):
        d["next"] = {"action": "let_join", "who": nxt.split(":", 1)[1].strip() if ":" in nxt else None}
    else:
        errors.append(f"NEXT {nxt!r} is not continue, wrap_up, leave:<reason>, pause or let_join:<name>")

    if not d["say"] and not d["answers"] and d["next"]["action"] == "continue":
        errors.append("nothing said and nothing answered")
    return d, errors


def fallback(decision):
    """After the corrective retry also failed: the line it had, as a plain statement; nothing answered for them."""
    return {"answers": None, "act": "statement", "message_type": "statement", "stance": decision.get("stance"),
            "emotion": decision.get("emotion"), "say": decision.get("say"), "condition": None,
            "next": decision.get("next") or {"action": "continue"}, "fallback": True}


def to_event(decision, character_id, addressed=None):
    """The state-machine event for a parsed turn."""
    nxt = decision.get("next") or {}
    ev = {"type": "turn", "by": character_id, "addressed": addressed, "said": bool(decision.get("say")),
          "requires_response": decision.get("message_type") in ("question", "request", "proposal"),
          "raises_item": decision.get("message_type") in ("question", "request", "proposal"),
          "wrap_up": nxt.get("action") == "wrap_up"}
    if nxt.get("action") == "leave":
        ev.update(control="leave", leave_reason="angry" if nxt.get("reason") == "angry" else
                  ("busy" if nxt.get("reason") == "busy" else "excuse"))
    elif nxt.get("action") == "pause":
        ev["control"] = "pause"
    ans = decision.get("answers") or {}
    if ans.get("response_type") in ("reject", "defer") and nxt.get("action") == "leave":
        ev["leave_reason"] = ev.get("leave_reason", "excuse")
    return ev


def parse_initiate(text):
    f = _fields(text)
    errors = []
    who = f.get("TALK_TO")
    if not who:
        errors.append("TALK_TO names who to talk to")
    purpose = (f.get("PURPOSE") or "social").lower()
    if purpose not in {p.value for p in Purpose}:
        errors.append(f"PURPOSE {purpose!r} is not one of {sorted(p.value for p in Purpose)}")
        purpose = "social"
    approach = (f.get("APPROACH") or "friendly").lower()
    if approach not in APPROACHES:
        approach = "friendly"
    channel = (f.get("CHANNEL") or "in_person").lower().replace(" ", "_").replace("face_to_face", "in_person")
    if channel not in {c.value for c in Channel}:
        errors.append(f"CHANNEL {channel!r} is not one of {sorted(c.value for c in Channel)}")
        channel = "in_person"
    return {"talk_to": who, "purpose": purpose, "about": f.get("ABOUT") or "", "approach": approach,
            "emotion": _feeling(f.get("FEELING")), "say": f.get("SAY") or None, "channel": channel,
            "urgent": approach == "urgent"}, errors
