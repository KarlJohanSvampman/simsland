"""
/admin/feedback -- the director's notes on lines of dialogue (systems/dialogue_feedback.py):

    POST   /admin/feedback/{speaker_id}          {conv_id, tick, utterance, verdict?, comment?, suggestion?}
    GET    /admin/feedback/{speaker_id}          their notes, newest first
    DELETE /admin/feedback/{speaker_id}/{id}
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import load_world, save_world, world_lock

router = APIRouter(prefix="/admin/feedback", tags=["feedback"])

class NoteIn(BaseModel):
    conv_id: str
    tick: int
    utterance: str
    verdict: str | None = "__unset__"
    comment: str | None = None
    suggestion: str | None = None


def _save(sim_id, world, cid):
    from sim_loop import _mark_dirty
    _mark_dirty(world, char_ids=[cid])
    save_world(sim_id, world)


def _char(world, cid):
    c = (world.get("characters") or {}).get(cid)
    if not c:
        raise HTTPException(404, f"no character '{cid}'")
    return c


@router.post("/{speaker_id}")
def give_note(speaker_id: str, body: NoteIn, sim_id: str = "default"):
    from systems.dialogue_feedback import give
    changes = {}
    if body.verdict != "__unset__":
        changes["verdict"] = body.verdict or None
    if body.comment is not None:
        changes["comment"] = body.comment
    if body.suggestion is not None:
        changes["suggestion"] = body.suggestion
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, speaker_id)
        try:
            note = give(c, world, body.conv_id, body.tick, body.utterance, **changes)
        except ValueError as e:
            raise HTTPException(400, str(e))
        from systems.personal_rules import note_given
        note_given(c)
        _save(sim_id, world, speaker_id)
    return {"ok": True, "note": note}


@router.get("/{speaker_id}")
def list_notes(speaker_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    c = _char(world, speaker_id)
    return {"speaker_id": speaker_id, "name": c.get("name"), "notes": list(reversed(c.get("dialogue_feedback") or []))}


@router.delete("/{speaker_id}/{fb_id}")
def delete_note(speaker_id: str, fb_id: str, sim_id: str = "default"):
    from systems.dialogue_feedback import remove
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, speaker_id)
        if not remove(c, fb_id):
            raise HTTPException(404, "no such note")
        _save(sim_id, world, speaker_id)
    return {"ok": True}
