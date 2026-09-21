from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    st = request.app.state
    sim_ok, sim_err = True, None
    try:
        await st.sim.list_characters()
    except Exception as e:  # noqa: BLE001 -- report, don't crash
        sim_ok, sim_err = False, str(e)
    ping = getattr(st.llm, "ping", None)
    llm_ok = await ping() if ping else None
    return {"status": "ok" if sim_ok and llm_ok is not False else "degraded",
            "simsland": {"ok": sim_ok, "error": sim_err},
            "llm": {"ok": llm_ok},
            "runner": {"running": st.runner.running, "last_error": st.runner.last_error}}
