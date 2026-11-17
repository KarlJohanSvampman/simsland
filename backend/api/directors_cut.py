"""
Director Mode's STOP and Director's Cut (systems/directors_cut.py), for VR (frontend/src/vrDirector.js):

    GET  /director/stop                      is time stopped; where the director stood; who is looking at them
    POST /director/stop    {x, y, radius?}   "STOP!" -- time stops; everyone within the radius looks at the director
    POST /director/resume                    "Action!"
    GET  /director/cut/{id}                  what can be changed: areas, their traits / quirks / ... and facts now,
                                             what they chose last, their past cuts
    POST /director/cut/{id}  {instead?, why?, changes: [{area, key?, action, value?, old?}], keep_as_rule?}
    POST /director/cut/{id}/{cut_id}/undo
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import load_world, save_world, world_lock
from core.commands import command
from systems import directors_cut as dc

router = APIRouter(prefix="/director", tags=["director"])


# A note or a rule can hand work to the background LLM (systems/bg_work.py), which arms its duty's timer.
_BG_WORK = [("key", "_bg_work"), ("key", "timers"), ("key", "_timer_seq")]


class StopIn(BaseModel):
    x: float
    y: float
    radius: float | None = None


class CutIn(BaseModel):
    instead: str | None = ""
    why: str | None = ""
    changes: list[dict] = []
    keep_as_rule: bool = False


def _char(world, cid):
    c = (world.get("characters") or {}).get(cid)
    if not c:
        raise HTTPException(404, f"no character '{cid}'")
    return c


def _save(sim_id, world, cids=()):
    from sim_loop import _mark_dirty
    if cids:
        _mark_dirty(world, char_ids=list(cids))
    save_world(sim_id, world)


@router.get("/stop")
def get_stop(sim_id: str = "default"):
    world = load_world(sim_id)
    return {"tick": world.get("tick", 0), **(world.get("director_stop") or {"active": False})}


@router.post("/stop")
@command("directors_cut.stop", entities="world")          # everyone within the radius
def stop(body: StopIn, sim_id: str = "default"):
    with world_lock():
        world = load_world(sim_id)
        st = dc.stop_time(world, body.x, body.y, body.radius or dc.STOP_RADIUS)
        _save(sim_id, world)
        return {"ok": True, **st}


@router.post("/resume")
@command("directors_cut.resume", entities=lambda a: [("key", "director_stop"), ("key", "director_log")])
def resume(sim_id: str = "default"):
    with world_lock():
        world = load_world(sim_id)
        st = dc.resume_time(world)
        _save(sim_id, world)
        return {"ok": True, **st}


def _view(c, world):
    return {"char_id": c["id"], "name": c.get("name"), "stopped": dc.is_stopped(world), "areas": dc.areas(),
            "lists": {k: list(c.get(v[0]) or []) for k, v in dc.LIST_AREAS.items()},
            "facts": c.get("character_facts") or {}, "last_choice": dc.last_choice(c),
            "cuts": list(reversed(c.get("directors_cuts") or []))[:20]}


@router.get("/cut/{char_id}")
def get_cut(char_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    return _view(_char(world, char_id), world)


@router.post("/cut/{char_id}")
@command("directors_cut.cut", entities="world")            # interrupting the activity can free a prop's anchor
def cut(char_id: str, body: CutIn, sim_id: str = "default"):
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, char_id)
        try:
            made = dc.apply_cut(c, world, body.instead, body.why, body.changes, body.keep_as_rule)
        except ValueError as e:
            raise HTTPException(400, str(e))
        _save(sim_id, world, [char_id])
        return {"ok": True, "cut": made, **_view(c, world)}


@router.post("/cut/{char_id}/{cut_id}/undo")
@command("directors_cut.undo", entities=lambda a: [("characters", a["char_id"]), ("key", "director_log")] + _BG_WORK)
def undo(char_id: str, cut_id: str, sim_id: str = "default"):
    with world_lock():
        world = load_world(sim_id)
        c = _char(world, char_id)
        if not dc.undo_cut(c, world, cut_id):
            raise HTTPException(404, "no such cut (or already undone)")
        _save(sim_id, world, [char_id])
        return {"ok": True, **_view(c, world)}
