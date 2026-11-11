"""
/admin/panels -- debug panels (widgets) for any entity (systems/debug_panels.py), for the panel designer
(frontend/panels.html) and the VR debugging interface (frontend/src/vrDebug.js).

    GET    /admin/panels                               every template, the types and states there are
    PUT    /admin/panels/templates/{id}                create or replace a template (the body; its "id" must match)
    DELETE /admin/panels/templates/{id}                remove it (and from every layout)
    GET    /admin/panels/for/{kind}/{id}               the templates that apply to that entity, its layouts and states
    PUT    /admin/panels/for/{kind}/{id}               save its layouts: {"active", "layouts": {name: {"panels": {tid: state}}}}
    GET    /admin/panels/data/{kind}/{id}?path=&limit= the value at a path into the entity, as the simulation has it
    GET    /admin/panels/fields/{kind}/{id}?path=      an outline of the data under a path, for picking one
    GET    /admin/panels/entities?kind=                the entities of a kind (id and name), for picking one

Kinds: character, prop, household, building, item. Data is read from the world as saved (the gateways' replica), so a
panel can show what the browser is never sent (logs, history, memories).
"""

from fastapi import APIRouter, HTTPException

from db import load_world
from systems import debug_panels as dp

router = APIRouter(prefix="/admin/panels", tags=["panels"])
MAX_LIST = 2000


@router.get("")
def everything(sim_id: str = "default"):
    data = dp.load(sim_id)
    return {"templates": data["templates"], "types": list(dp.TYPES), "states": list(dp.STATES), "kinds": list(dp.KINDS),
            "max_alternatives": dp.MAX_ALTERNATIVES}


@router.put("/templates/{tid}")
def put_template(tid: str, body: dict, sim_id: str = "default"):
    if body.get("id") != tid:
        raise HTTPException(400, "the body's id must match the address")
    probs = dp.check_template(body)
    if probs:
        raise HTTPException(400, "; ".join(probs))
    data = dp.load(sim_id)
    t = dp.put_template(data, body)
    dp.save(data, sim_id)
    return {"ok": True, "template": t}


@router.delete("/templates/{tid}")
def delete_template(tid: str, sim_id: str = "default"):
    data = dp.load(sim_id)
    dp.delete_template(data, tid)
    dp.save(data, sim_id)
    return {"ok": True}


def _check_kind(kind):
    if kind not in dp.KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(dp.KINDS)}")


@router.get("/for/{kind}/{eid}")
def for_entity(kind: str, eid: str, sim_id: str = "default"):
    _check_kind(kind)
    return dp.for_entity(dp.load(sim_id), kind, eid)


@router.put("/for/{kind}/{eid}")
def set_layouts(kind: str, eid: str, body: dict, sim_id: str = "default"):
    _check_kind(kind)
    data = dp.load(sim_id)
    probs = dp.set_layouts(data, kind, eid, body)
    if probs:
        raise HTTPException(400, "; ".join(probs))
    dp.save(data, sim_id)
    return dp.for_entity(data, kind, eid)


def _entity(kind, eid, sim_id):
    _check_kind(kind)
    ent = dp.find_entity(load_world(sim_id), kind, eid)
    if ent is None:
        raise HTTPException(404, f"no {kind} '{eid}'")
    return ent


@router.get("/data/{kind}/{eid}")
def data(kind: str, eid: str, path: str = "", limit: int = 500, sim_id: str = "default"):
    value = dp.data_at(_entity(kind, eid, sim_id), path)
    total = None
    if isinstance(value, list):
        total = len(value)
        value = value[-max(1, min(limit, MAX_LIST)):]       # the newest entries
    return {"path": path, "value": value, "total": total}


@router.get("/fields/{kind}/{eid}")
def fields(kind: str, eid: str, path: str = "", depth: int = 2, sim_id: str = "default"):
    root = dp.data_at(_entity(kind, eid, sim_id), path) if path else _entity(kind, eid, sim_id)
    if isinstance(root, list):
        root = root[-1] if root else {}
    return {"path": path, "fields": dp.fields(root, depth=max(1, min(depth, 4)))}


@router.get("/entities")
def entities(kind: str = "character", sim_id: str = "default"):
    _check_kind(kind)
    w = load_world(sim_id)
    if kind == "character":
        rows = [{"id": i, "name": c.get("name") or i} for i, c in (w.get("characters") or {}).items() if not c.get("is_workplace_npc")]
    elif kind == "household":
        rows = [{"id": i, "name": h.get("name") or i} for i, h in (w.get("households") or {}).items()]
    elif kind == "prop":
        rows = [{"id": p.get("id"), "name": f"{p.get('template') or 'prop'} ({p.get('building_id') or 'outside'})"} for p in w.get("props") or []]
    elif kind == "building":
        rows = [{"id": b.get("id"), "name": b.get("address") or b.get("id")} for b in w.get("buildings") or []]
    else:
        rows = []
    return {"kind": kind, "entities": rows[:1000]}
