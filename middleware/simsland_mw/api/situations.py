from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["situations"])


def _reg(request: Request):
    return request.app.state.engine.situations


@router.get("/situations")
async def list_situations(request: Request):
    return [{"id": s.id, "category": s.category, "priority": s.priority,
             "cooldown_ticks": s.cooldown_ticks,
             "triggers": [t.type for t in s.triggers],
             "required_data": list(s.required_data),
             "options": [{"id": o.id, "kind": "gap" if o.gap else "noop" if o.noop else "action",
                          "gap": o.gap, "speaks": o.speaks} for o in s.options]}
            for s in _reg(request).all()]


@router.get("/situations/capabilities")
async def capabilities(request: Request):
    """Options that name backend capabilities Simsland does not have yet."""
    return _reg(request).capability_report()


@router.get("/situations/{sid}")
async def one(sid: str, request: Request):
    try:
        s = _reg(request).get(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown situation")
    return {"id": s.id, "notes": s.notes, "options": [o.id for o in s.options]}
