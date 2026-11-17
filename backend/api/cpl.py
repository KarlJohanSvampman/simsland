"""
/admin/cpl -- read-only views of the conversation protocol layer (docs/cpl_implementation_plan.md):

    GET /admin/cpl/metrics              how turns were generated (A/B/C), model calls, how conversations ended
    GET /admin/cpl/conversations        the live ones: who, state, purpose, what is open
    GET /admin/cpl/conversations/{id}   one, in full (participants, messages, requests, claims, the record)
    GET /admin/cpl/shadow               the shadow's comparison with the legacy lifecycle
"""

from fastapi import APIRouter, HTTPException

from db import load_world

router = APIRouter(prefix="/admin/cpl", tags=["cpl"])


@router.get("/metrics")
def metrics(sim_id: str = "default"):
    from cpl import config, metrics as M
    world = load_world(sim_id)
    return dict(M.report(world), mode=config.mode(world))


@router.get("/conversations")
def conversations(sim_id: str = "default"):
    from cpl import store
    world = load_world(sim_id)
    out = []
    for c in store.live(world):
        out.append({"id": c["id"], "state": c["state"], "purpose": c.get("purpose"), "channel": c.get("channel"),
                    "participants": {p: d.get("status") for p, d in c["participants"].items()},
                    "lines": c.get("lines", 0), "open": c.get("open_items"), "summary": c["context"].get("summary")})
    return {"conversations": out}


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, sim_id: str = "default"):
    from cpl import record, store
    world = load_world(sim_id)
    c = store.get(world, conversation_id)
    if not c:
        raise HTTPException(404, "no such conversation (finished ones leave the world an hour after they end)")
    reqs = [r for r in (world.get("cpl_requests") or {}).values() if r.get("conversation_id") == conversation_id]
    return {"conversation": c, "requests": reqs, "record": record.lines(world, c)}


@router.get("/shadow")
def shadow(sim_id: str = "default"):
    from cpl import shadow as S
    return S.compare(load_world(sim_id))
