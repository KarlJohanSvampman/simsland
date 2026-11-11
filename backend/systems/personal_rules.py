"""
systems/personal_rules.py -- personal rules a character keeps, learned from the director's notes on their lines
(systems/dialogue_feedback.py) and approved by the director before they count.

    c["personal_rules"] = [{id, text, status, source, from_notes: [note ids], created_tick, decided_tick}]
        status   "proposed"  -- written by the model from the notes, waiting for the director
                 "approved"  -- in the character's prompt from now on (brain/context_builder.py, identity section)
                 "rejected"  -- turned down (kept so the model doesn't propose it again)
                 "retired"   -- was approved, taken out again
        source   "notes" (the model, from notes) | "director" (written by the director: approved straight away)

How proposals happen: a note with something in it (a dislike, a reason, a better line) that hasn't been used yet makes
the character due (c["_rules_due"]); systems/calendar_handlers.py's background services call service() every few
seconds, which -- once MIN_NOTES unused notes have piled up, or straight away when the director asks ("Propose from
notes now") -- sends them to the model (llm/personal_rules.py, on a bg_llm worker) and adds what comes back as
proposed rules. The notes it used are marked used. If the model doesn't answer, the notes stay unused for next time.
"""

import uuid

MIN_NOTES = 3              # unused notes before rules are proposed on their own (the director can ask sooner)
MAX_NOTES_PER_ASK = 12
ASK_TIMEOUT_TICKS = 600
REJECTED_SHOWN = 10


def _notes_waiting(c):
    return [n for n in c.get("dialogue_feedback") or []
            if not n.get("used") and (n.get("verdict") == "dislike" or n.get("comment") or n.get("suggestion"))]


def note_given(c):
    """A note was made or changed (api/dialogue_feedback.py)."""
    if _notes_waiting(c):
        c["_rules_due"] = c.get("_rules_due") or "notes"


def ask_now(c):
    """The director asked for rules from the notes so far."""
    if not _notes_waiting(c):
        return False
    c["_rules_due"] = "asked"
    return True


def rules(c, status=None):
    return [r for r in c.get("personal_rules") or [] if status is None or r.get("status") == status]


def add(c, world, text, source="director", status=None, from_notes=()):
    r = {"id": f"rule_{uuid.uuid4().hex[:8]}", "text": str(text).strip()[:200], "source": source,
         "status": status or ("approved" if source == "director" else "proposed"),
         "from_notes": list(from_notes), "created_tick": world.get("tick", 0), "decided_tick": None}
    if source == "director":
        r["decided_tick"] = r["created_tick"]
    c.setdefault("personal_rules", []).append(r)
    return r


def decide(c, world, rule_id, action, text=None):
    """approve / reject / retire / edit (a proposed or approved rule's wording)."""
    r = next((x for x in c.get("personal_rules") or [] if x.get("id") == rule_id), None)
    if not r:
        return None
    if action == "edit":
        if text and text.strip():
            r["text"] = text.strip()[:200]
        return r
    new = {"approve": "approved", "reject": "rejected", "retire": "retired"}.get(action)
    if not new:
        raise ValueError(f"unknown action {action!r}")
    r["status"] = new
    r["decided_tick"] = world.get("tick", 0)
    return r


def prompt_lines(c):
    """What the character is told (brain/context_builder.py)."""
    ok = [r["text"] for r in rules(c, "approved")]
    return [f"Your own rules for yourself (keep to them): {' '.join(t if t.endswith(('.', '!', '?')) else t + '.' for t in ok)}"] if ok else []


def _key(c):
    return f"rules:{c['id']}:{c.get('_rules_ask', {}).get('n', 0)}"


def service(c, world):
    due = c.get("_rules_due")
    ask = c.get("_rules_ask")
    if not due and not ask:
        return
    from systems import bg_llm
    tick = world.get("tick", 0)
    if not ask:
        notes = _notes_waiting(c)[:MAX_NOTES_PER_ASK]
        if not notes or (due != "asked" and len(notes) < MIN_NOTES):
            if not notes:
                c.pop("_rules_due", None)
            return
        from systems.personality_profile import effective_traits
        from llm.personal_rules import build_prompt, propose
        prompt = build_prompt(c.get("name") or c["id"], c.get("age"), effective_traits(c), c.get("speech_quirks") or [],
                              [r["text"] for r in rules(c, "approved") + rules(c, "proposed")],
                              [r["text"] for r in rules(c, "rejected")][-REJECTED_SHOWN:], notes)
        ask = c["_rules_ask"] = {"n": (c.get("_rules_seq") or 0) + 1, "tick": tick, "note_ids": [n["id"] for n in notes],
                                 "prompt": prompt}
        c["_rules_seq"] = ask["n"]
        c.pop("_rules_due", None)
        bg_llm.submit(_key(c), propose, prompt, len(notes), c["id"])
        return
    ready, result = bg_llm.take(_key(c))
    if not ready:
        if tick - ask["tick"] > ASK_TIMEOUT_TICKS:
            c.pop("_rules_ask", None)               # never came back: the notes stay unused, try again later
            c["_rules_due"] = "notes"
        elif not bg_llm.is_pending(_key(c)):        # lost (restart): send it again
            from llm.personal_rules import propose
            bg_llm.submit(_key(c), propose, ask["prompt"], len(ask["note_ids"]), c["id"])
        return
    c.pop("_rules_ask", None)
    if result is None:                              # the model didn't answer: try again later
        c["_rules_due"] = "notes"
        c["_rules_last"] = {"tick": tick, "outcome": "the model didn't answer -- will try again"}
        return
    by_id = {n["id"]: n for n in c.get("dialogue_feedback") or []}
    for nid in ask["note_ids"]:
        if nid in by_id:
            by_id[nid]["used"] = True
    known = {r["text"].strip().lower() for r in c.get("personal_rules") or []}
    added = 0
    for p in result:
        if p["text"].strip().lower() in known:
            continue
        add(c, world, p["text"], source="notes", from_notes=[ask["note_ids"][i] for i in p.get("from") or [] if i < len(ask["note_ids"])])
        added += 1
    c["_rules_last"] = {"tick": tick, "outcome": f"{added} rule{'s' if added != 1 else ''} proposed from {len(ask['note_ids'])} notes"
                        if added else f"no new rule from {len(ask['note_ids'])} notes"}


def service_all(world):
    for c in (world.get("characters") or {}).values():
        if c.get("_rules_due") or c.get("_rules_ask"):
            try:
                service(c, world)
            except Exception as exc:
                print(f"[personal_rules] {c.get('id')}: {exc!r}")
