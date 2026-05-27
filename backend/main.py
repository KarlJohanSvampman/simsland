import asyncio, os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from core.redis_queue import enqueue
from db import load_world, save_world, init_db, conn, update_world_tick
from sim_loop import tick
from systems.economy import household_economy
from llm.llm_client import call_llm,call_llm_safe
from api.view import router as view_router
from fastapi.staticfiles import StaticFiles
from api.assets import router as assets_router
from api.editor import router as editor_router
from api.editor import load_definitions, save_definitions
from api.view import get_view
from api.props import router as props_router
from systems.schema_defaults import (
    ensure_world_defaults
)
app = FastAPI(title="Simsland")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # your frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/resources", StaticFiles(directory="/resources"), name="resources")
clients = []
app.include_router(view_router)
app.include_router(assets_router, prefix="/api")
app.include_router(props_router, prefix="/api")
SIM_ID = "default"

frontend_dir = Path(__file__).parent / "frontend"
app.include_router(
    editor_router,
    prefix="/api/editor"
)
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


async def loop():

    while True:

        world = load_world(SIM_ID)

        ensure_world_defaults(
            world
        )
        world["definitions"] = load_definitions(
            SIM_ID
        )

        tick(world)

        update_world_tick(
            SIM_ID,
            world["tick"]
        )
        for c in list(
            world.get("characters", {}).values()
        ):

            enqueue({
                "type": "agent_tick",
                "simulation_id": SIM_ID,
                "character_id": c["id"]
            })

        dead = []

        for ws in clients:

            try:
                view_state = get_view(
                    sim_id=SIM_ID,
                    cx=0,
                    cy=0,
                    zoom=1
                )

                await ws.send_json(view_state)
            except Exception:
                dead.append(ws)

        for ws in dead:

            if ws in clients:
                clients.remove(ws)

        await asyncio.sleep(
            float(
                os.getenv(
                    "TICK_RATE_SECONDS",
                    "1.0"
                )
            )
        )



@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(loop())


@app.get("/")
def index():
    path = Path(__file__).parent / "frontend" / "index.html"
    return FileResponse(path) if path.exists() else {"ok": True, "message": "frontend not found"}


# 🔥 API now reads from DB
@app.get("/api/state")
def state():
    return load_world(SIM_ID)


@app.get("/api/household/{household_id}")
def household(household_id: str):
    world = load_world(SIM_ID)
    return household_economy(world, household_id) or {"error": "not found"}


@app.post("/api/config/environment")
def update_environment(payload: dict):
    world = load_world(SIM_ID)
    world.setdefault("environment", {}).update(payload)
    save_world(SIM_ID, world)
    return world["environment"]


@app.get("/api/llm/logs")
def llm_logs():
    world = load_world(SIM_ID)
    return world.get("llm_logs", [])


@app.delete("/api/llm/logs")
def clear_llm_logs():
    world = load_world(SIM_ID)
    world["llm_logs"] = []
    save_world(SIM_ID, world)
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients:
            clients.remove(ws)