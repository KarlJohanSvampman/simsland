from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..cognition.decisions import PROFILES
from ..simulation.client import SimError

router = APIRouter(tags=["characters"])


def _eng(request: Request):
    return request.app.state.engine


@router.get("/characters")
async def list_characters(request: Request):
    try:
        return await request.app.state.sim.list_characters()
    except SimError as e:
        raise HTTPException(status_code=502, detail=str(e))


class EnableReq(BaseModel):
    enabled: bool = True


@router.post("/characters/{char_id}/enable")
async def enable(char_id: str, req: EnableReq, request: Request):
    """Hand this character's decisions to (or take them back from) the middleware."""
    try:
        return await request.app.state.sim.set_external_brain(char_id, req.enabled)
    except SimError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/characters/{char_id}/preview")
async def preview(char_id: str, request: Request, wake_reason: Optional[str] = None,
                  profile: Optional[str] = None):
    """Build the prompt and option list exactly as a decision would, without calling the LLM."""
    if profile and profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"unknown profile; choose from {sorted(PROFILES)}")
    try:
        p = await _eng(request).prepare(char_id, wake_reason, profile)
    except SimError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"profile": p.profile, "waves": p.resolution.waves, "errors": p.resolution.errors,
            "options": [o.public() for o in p.options], "prompt": p.messages}


@router.post("/characters/{char_id}/decide")
async def decide(char_id: str, request: Request, dry_run: bool = True,
                 wake_reason: Optional[str] = None, profile: Optional[str] = None):
    """Run one full decision. Defaults to dry_run so poking it by hand can't change the world."""
    try:
        rec = await _eng(request).decide(char_id, wake_reason, dry_run=dry_run, profile=profile)
    except SimError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return rec.to_dict()


@router.get("/characters/{char_id}/session")
async def session(char_id: str, request: Request):
    return _eng(request).sessions.get(char_id).to_dict()


@router.get("/decisions")
async def decisions(request: Request):
    return list(request.app.state.runner.history)


@router.get("/data-types")
async def data_types(request: Request):
    reg = _eng(request).resolver.registry
    return [{"type": t, "depends_on": list(reg.get(t).depends_on), "sections": list(reg.get(t).sections),
             "ttl": reg.get(t).ttl} for t in reg.types()]


@router.get("/runner")
async def runner_state(request: Request):
    r = request.app.state.runner
    return {"running": r.running, "last_error": r.last_error, "recent": len(r.history)}


@router.post("/runner/{action}")
async def runner_control(action: str, request: Request):
    r = request.app.state.runner
    if action == "start":
        r.start()
    elif action == "stop":
        await r.stop()
    else:
        raise HTTPException(status_code=404, detail="use /runner/start or /runner/stop")
    return {"running": r.running}
