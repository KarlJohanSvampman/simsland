"""
main.py — FastAPI entry point

Key changes vs. original:
  - Per-client viewport: WS clients send {"type":"viewport","cx":X,"cy":Y,"zoom":Z}
    messages; each connection gets a snapshot filtered to their own view.
  - Delta broadcasting: only changed characters/props are sent each tick;
    clients receive a full snapshot on first connect, then patches.
  - World is loaded once at startup and kept in the Redis cache; load_world()
    in the tick loop hits the cache almost exclusively.
  - Agent ticks are offloaded to the Redis queue (unchanged from before).
"""

import asyncio, os, json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.redis_queue import enqueue
from db import load_world, save_world, init_db, update_world_tick
from sim_loop import tick, collect_dirty
from api.view import get_view, in_view
from api.editor import load_definitions, save_definitions
from systems.economy import household_economy
from systems.schema_defaults import ensure_world_defaults
from api.assets  import router as assets_router
from api.editor  import router as editor_router
from api.props   import router as props_router
from api.meshbank import router as meshbank_router
from api.view    import router as view_router

app = FastAPI(title="Simsland")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/resources", StaticFiles(directory="/resources"), name="resources")

app.include_router(view_router)
app.include_router(assets_router, prefix="/api")
app.include_router(props_router,  prefix="/api")
app.include_router(meshbank_router, prefix="/api")
app.include_router(editor_router,   prefix="/api/editor")

frontend_dir = Path(__file__).parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

SIM_ID = "default"

# =========================================================
# CLIENT REGISTRY
# Each entry: {"ws": WebSocket, "cx": int, "cy": int,
#              "zoom": int, "needs_full": bool}
# =========================================================

_clients: list[dict] = []


def _view_radius(zoom: int) -> int:
    return {1: 25, 2: 15, 3: 8}.get(zoom, 15)


def _build_full_snapshot(world, definitions, cx, cy, zoom):
    """Full world slice for a given viewport — sent on first connect."""
    radius = _view_radius(zoom)
    return get_view(sim_id=SIM_ID, cx=cx, cy=cy, zoom=zoom)


def _build_delta(dirty: dict, cx: int, cy: int, zoom: int) -> dict | None:
    """
    Filter the dirty entities to only what falls within this client's viewport.
    Returns None if nothing in the delta is visible to this client.
    """
    radius = _view_radius(zoom)

    visible_chars = {
        cid: c for cid, c in dirty["chars"].items()
        if in_view(c.get("x", 0), c.get("y", 0), cx, cy, radius)
    }
    visible_props = {
        pid: p for pid, p in dirty["props"].items()
        if in_view(p.get("x", 0), p.get("y", 0), cx, cy, radius)
    }

    if not visible_chars and not visible_props:
        return None

    return {
        "type":       "delta",
        "characters": visible_chars,
        "props":      visible_props,
    }


# =========================================================
# MAIN LOOP
# =========================================================

async def loop():
    tick_rate = float(os.getenv("TICK_RATE_SECONDS", "1.0"))
    definitions = load_definitions(SIM_ID)

    while True:
        world = load_world(SIM_ID)
        ensure_world_defaults(world)
        world["definitions"] = definitions

        tick(world)

        update_world_tick(SIM_ID, world["tick"])

        # Offload LLM-heavy agent work to Redis queue
        for c in list(world.get("characters", {}).values()):
            enqueue({
                "type":          "agent_tick",
                "simulation_id": SIM_ID,
                "character_id":  c["id"],
            })

        # Collect what changed this tick
        dirty = collect_dirty(world)

        # Broadcast to each client
        dead = []
        for client in _clients:
            ws   = client["ws"]
            cx   = client.get("cx", 0)
            cy   = client.get("cy", 0)
            zoom = client.get("zoom", 2)
            try:
                if client.get("needs_full"):
                    snapshot = _build_full_snapshot(world, definitions, cx, cy, zoom)
                    snapshot["type"] = "snapshot"
                    await ws.send_json(snapshot)
                    client["needs_full"] = False
                else:
                    delta = _build_delta(dirty, cx, cy, zoom)
                    if delta:
                        await ws.send_json(delta)
            except Exception:
                dead.append(client)

        for client in dead:
            if client in _clients:
                _clients.remove(client)

        await asyncio.sleep(tick_rate)


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(loop())


# =========================================================
# WEBSOCKET ENDPOINT
# Clients should send JSON messages to update their viewport:
#   {"type": "viewport", "cx": 12, "cy": 8, "zoom": 2}
# =========================================================

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    client = {"ws": ws, "cx": 0, "cy": 0, "zoom": 2, "needs_full": True}
    _clients.append(client)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            if msg.get("type") == "viewport":
                new_cx   = int(msg.get("cx",   client["cx"]))
                new_cy   = int(msg.get("cy",   client["cy"]))
                new_zoom = int(msg.get("zoom", client["zoom"]))

                # If viewport moved meaningfully, request a fresh full snapshot
                if (new_cx != client["cx"] or new_cy != client["cy"]
                        or new_zoom != client["zoom"]):
                    client["cx"]         = new_cx
                    client["cy"]         = new_cy
                    client["zoom"]       = new_zoom
                    client["needs_full"] = True

    except WebSocketDisconnect:
        if client in _clients:
            _clients.remove(client)


# =========================================================
# REST ENDPOINTS
# =========================================================

@app.get("/")
def index():
    path = Path(__file__).parent / "frontend" / "index.html"
    return FileResponse(path) if path.exists() else {"ok": True, "message": "frontend not found"}


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
