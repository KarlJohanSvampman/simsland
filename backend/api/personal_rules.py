"""
/admin/rules -- a character's personal rules (systems/personal_rules.py), for VR "Personal rules"
(frontend/src/vrRules.js):

    GET  /admin/rules/{id}                 rules by status, notes waiting to be turned into rules, whether the model is
                                           working on it, what came of the last try
    POST /admin/rules/{id}/ask             propose rules from the notes so far, now
    POST /admin/rules/{id}/add   {text}    a rule written by the director (approved straight away)
    POST /admin/rules/{id}/{rule_id}  {action: approve | reject | retire | edit, text?}
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import load_world, save_world, world_lock

router = APIRouter(prefix="/admin/rules", tags=["rules"])


class TextIn(BaseModel):
    text: str


class DecideIn(BaseModel):
    action: str
    text: str | None = None


def _char(world, cid):
    c = (world.get("characters") or {}).get(cid)
    if not c:
        raise HTTPException(404, f"no character '{cid}'")
    return c


def _save(sim_id, world, cid):
    from sim_loop import _mark_dirty
    _mark_dirty(world, char_ids=[cid])
    save_world(sim_id, world)


def _view(c, world):
    from systems.personal_rules import rules, _notes_waiting, MIN_NOTES
    notes = {n["id"]: n for n in c.get("dialogue_feedback") or []}

    def row(r):
        return dict(r, notes=[{"utterance": notes[i].get("utterance"), "verdict": notes[i].get("verdict"),
                               "comment": notes[i].get("comment"), "suggestion": notes[i].get("suggestion")}
                              for i in r.get("from_notes") or [] if i in notes])
    return {"char_id": c["id"], "name": c.get("name"), "tick": world.get("tick", 0),
            "proposed": [row(r) for r in rules(c, "proposed")], "approved": [row(r) for r in rules(c, "approved")],
            "rejected": [row(r) for r in rules(c, "rejected")][-10:], "retired": [row(r) for r in rules(c, "retired")][-10:],
            "notes_waiting": len(_notes_waiting(c)), "min_notes": MIN_NOTES,
            "asking": bool(c.get("_rules_ask")), "due": c.get("_rules_due"), "last": c.get("_rules_last")}


@router.get("/{char_id}")
def get_rules(char_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    return _view(_char(world, char_id), world)


@router.post("/{char_id}/ask")
def ask(char_id: str, sim_id: str = "default"):
    from systems.personal_rules import ask_now
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, char_id)
        if not ask_now(c, world):
            raise HTTPException(400, "no notes waiting -- like / dislike a line, say why or suggest a better one first")
        _save(sim_id, world, char_id)
        return _view(c, world)


@router.post("/{char_id}/add")
def add_rule(char_id: str, body: TextIn, sim_id: str = "default"):
    from systems.personal_rules import add
    if not body.text.strip():
        raise HTTPException(400, "empty rule")
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, char_id)
        add(c, world, body.text, source="director")
        _save(sim_id, world, char_id)
        return _view(c, world)


@router.post("/{char_id}/{rule_id}")
def decide_rule(char_id: str, rule_id: str, body: DecideIn, sim_id: str = "default"):
    from systems.personal_rules import decide
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, char_id)
        try:
            r = decide(c, world, rule_id, body.action, body.text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if r is None:
            raise HTTPException(404, "no such rule")
        _save(sim_id, world, char_id)
        return _view(c, world)
