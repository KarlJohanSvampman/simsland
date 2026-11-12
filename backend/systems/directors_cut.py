"""
systems/directors_cut.py -- Director Mode's STOP and Director's Cut.

STOP  (stop_time / resume_time)
    "STOP!": time stops for everyone (main.py skips ticks while world["director_stop"]["active"]), and everyone within
    the radius of the director is noted, with where the director stands, so the viewer turns them to look at the
    director. Nobody is interrupted: on "Action!" the world carries on from exactly where it stopped.

DIRECTOR'S CUT  (apply_cut / undo_cut)
    On any character, with or without time stopped:
      instead / why   change what they chose -- what they do instead and why that's more like them. They drop what
                      they're doing and think again with it in mind (wake "directors_cut"), so the next decision
                      follows it. "why" can also be kept as a personal rule (approved: systems/personal_rules.py).
      changes         key -> value changes, flexible:
                        {"area": <one of AREAS>, "key": <what about, for areas that have one>, "action": "set" |
                         "add" | "remove" | "replace", "value": <text>, "old": <for replace>}
                      List areas (traits, speech quirks, insecurities, confidence sources) change those lists;
                      every other area is a fact about them kept in c["character_facts"][area][key] = value and put in
                      their prompt (prompt_lines) -- opinions, values, principles, preferences (food, products,
                      people to socialise with...), hobbies and interests, routines, intentions, expectations (of
                      relationships, others, themselves), their ideal partner, what they want out of life, how bound
                      they are by parents' / society's expectations, temperament, patience, manners, generosity...
    Every cut is recorded, with what each change replaced, in c["directors_cuts"] so it can be undone.
"""

import uuid

LIST_AREAS = {
    "trait": ("traits", "Trait"),
    "quirk": ("speech_quirks", "Speech quirk"),
    "insecurity": ("insecurities", "Insecurity"),
    "confidence": ("confidence_sources", "Confidence source"),
}
FACT_AREAS = {
    "opinion": "Opinion", "value": "Value", "principle": "Principle",
    "preference": "Preference",                 # food, products, who they like to socialise with, views...
    "hobby": "Hobby / interest", "routine": "Routine", "intention": "Intention",
    "relationship_expectation": "Expects of relationships", "expectation_of_others": "Expects of others",
    "expectation_of_self": "Expects of themselves",
    "ideal_partner": "Ideal partner", "life_goal": "Wants out of life", "social_pressure": "Bound by expectations (parents / society)",
    "temperament": "Temperament", "patience": "Patience", "manners": "Manners", "generosity": "Generosity",
    "other": "Other",
}
CUTS_KEPT = 100
STOP_RADIUS = 8.0


def areas():
    return ([{"id": k, "label": v[1], "kind": "list", "field": v[0]} for k, v in LIST_AREAS.items()] +
            [{"id": k, "label": v, "kind": "fact"} for k, v in FACT_AREAS.items()])


# ---- STOP ----------------------------------------------------------------------------------------------------------

def stop_time(world, x, y, radius=STOP_RADIUS):
    chars = world.get("characters") or {}
    near = []
    for c in chars.values():
        if c.get("alive") is False or c.get("off_grid") or c.get("x") is None:
            continue
        if ((c["x"] - x) ** 2 + (c["y"] - y) ** 2) ** 0.5 <= radius:
            near.append(c["id"])
    world["director_stop"] = {"active": True, "x": x, "y": y, "radius": radius, "char_ids": near,
                              "tick": world.get("tick", 0)}
    _log(world, None, "stop", {"x": x, "y": y, "radius": radius, "affected": near})
    return world["director_stop"]


def resume_time(world):
    st = world.get("director_stop") or {}
    world["director_stop"] = {"active": False, "last": {k: st.get(k) for k in ("x", "y", "radius", "char_ids", "tick")}}
    _log(world, None, "resume", {})
    return world["director_stop"]


def is_stopped(world):
    return bool((world.get("director_stop") or {}).get("active"))


def _log(world, char_id, op, detail):
    from systems.director_mode import _log as dlog
    try:
        dlog(world, char_id, op, detail)
    except Exception:
        pass


# ---- DIRECTOR'S CUT ------------------------------------------------------------------------------------------------

def last_choice(c):
    log = c.get("choice_log") or []
    e = log[-1] if log else None
    act = c.get("activity") or {}
    return {"chosen": (e or {}).get("chosen"), "tick": (e or {}).get("tick"), "tags": (e or {}).get("significant") or [],
            "doing_now": act.get("type"), "thought": (c.get("thought_bubble") or {}).get("text") if isinstance(c.get("thought_bubble"), dict) else c.get("thought_bubble")}


def _apply_change(c, world, ch, why):
    area = ch.get("area")
    action = ch.get("action") or "set"
    value = str(ch.get("value") or "").strip()
    rec = {"area": area, "action": action, "value": value, "key": (ch.get("key") or "").strip(), "old": ch.get("old")}
    if area in LIST_AREAS:
        field = LIST_AREAS[area][0]
        before = list(c.get(field) or [])
        new = list(before)
        if action == "add" and value and value not in new:
            new.append(value)
        elif action == "remove":
            new = [t for t in new if t != (value or ch.get("old"))]
        elif action == "replace" and ch.get("old") in new and value:
            new = [value if t == ch.get("old") else t for t in new]
        elif action not in ("add", "remove", "replace"):
            raise ValueError(f"{area}: use add, remove or replace, not {action!r}")
        rec["before"] = before
        if field == "traits":
            from systems.personality_profile import set_traits
            set_traits(c, world, new, why=f"director's cut: {why}" if why else "director's cut")
        else:
            c[field] = new
        return rec
    if area in FACT_AREAS:
        key = rec["key"] or "general"
        facts = c.setdefault("character_facts", {}).setdefault(area, {})
        rec["key"] = key
        rec["before"] = facts.get(key)
        if action == "remove" or not value:
            facts.pop(key, None)
        else:
            facts[key] = value
        if not facts:
            c["character_facts"].pop(area, None)
        return rec
    raise ValueError(f"unknown area {area!r}")


def apply_cut(c, world, instead="", why="", changes=(), keep_as_rule=False):
    instead, why = (instead or "").strip(), (why or "").strip()
    if not instead and not changes and not (keep_as_rule and why):
        raise ValueError("nothing to change -- say what they do instead, or add a change")
    cut = {"id": f"cut_{uuid.uuid4().hex[:8]}", "tick": world.get("tick", 0), "choice_before": last_choice(c),
           "instead": instead, "why": why, "changes": [], "rule_id": None, "undone": False}
    for ch in changes or []:
        cut["changes"].append(_apply_change(c, world, ch, why))
    if keep_as_rule and why:
        from systems.personal_rules import add
        cut["rule_id"] = add(c, world, why, source="director")["id"]
    if instead:
        from systems.occupancy import interrupt_activity
        from brain.cognition_scheduler import wake_character
        try:
            interrupt_activity(c, world)
        except Exception:
            pass
        wake_character(c, world, "directors_cut", {"instead": instead, "why": why or "it's more like you"})
    log = c.setdefault("directors_cuts", [])
    log.append(cut)
    del log[:-CUTS_KEPT]
    _log(world, c["id"], "directors_cut", {"cut_id": cut["id"], "instead": instead, "changes": len(cut["changes"])})
    return cut


def undo_cut(c, world, cut_id):
    cut = next((x for x in c.get("directors_cuts") or [] if x.get("id") == cut_id), None)
    if not cut or cut.get("undone"):
        return None
    for rec in reversed(cut["changes"]):
        if rec["area"] in LIST_AREAS:
            field = LIST_AREAS[rec["area"]][0]
            if field == "traits":
                from systems.personality_profile import set_traits
                set_traits(c, world, rec["before"], why="director's cut undone")
            else:
                c[field] = list(rec["before"])
        else:
            facts = c.setdefault("character_facts", {}).setdefault(rec["area"], {})
            if rec["before"] is None:
                facts.pop(rec["key"], None)
            else:
                facts[rec["key"]] = rec["before"]
            if not facts:
                c["character_facts"].pop(rec["area"], None)
    if cut.get("rule_id"):
        from systems.personal_rules import decide
        decide(c, world, cut["rule_id"], "retire")
    cut["undone"] = True
    cut["undone_tick"] = world.get("tick", 0)
    _log(world, c["id"], "directors_cut_undone", {"cut_id": cut_id})
    return cut


def prompt_lines(c):
    """The facts set in Director's Cuts, for the character's prompt (brain/context_builder.py)."""
    facts = c.get("character_facts") or {}
    parts = []
    for area, label in FACT_AREAS.items():
        for key, value in (facts.get(area) or {}).items():
            parts.append(f"{label}{'' if key == 'general' else f' ({key})'}: {value}")
    return [f"About you: {'; '.join(parts)}."] if parts else []
