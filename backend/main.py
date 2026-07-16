"""
main.py — FastAPI entry point

Key changes vs. original:
  - Per-client viewport: WS clients send {"type":"viewport","cx":X,"cy":Y,"zoom":Z}
    messages; each connection gets a snapshot filtered to their own view.
  - Delta broadcasting: only changed characters/props are sent each tick;
    clients receive a full snapshot on first connect, then patches.
  - World is loaded once at startup and kept in the Redis cache; load_world()
    in the tick loop hits the cache almost exclusively.
  - Every character's LLM decision runs in-process, inside tick()'s own
    agent pool (sim_loop.py) — there used to also be a separate `sim-worker`
    container re-running the same decisions a second time via a Redis
    queue, unsynchronized with this process's world-mutation lock; it was
    removed (redundant LLM cost, and a second silent data-loss path).
"""

import asyncio, os, json, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.cache import set_world_cache
from db import load_world, save_world, init_db, update_world_tick, world_lock, _world_lock, _STATIC_WORLD_KEYS
from sim_loop import tick, collect_dirty
from api.view import get_view, in_view
# core.definitions (not api.editor's own separate, uncached duplicate of
# the same name) — this is the one with the process-local cache that
# api/editor.py's save_definitions() actually invalidates on edit, so the
# tick loop and every API route agree on the same fresh-vs-stale state.
from core.definitions import load_definitions
from api.editor import save_definitions
from systems.economy import household_economy
from systems.schema_defaults import ensure_world_defaults
from api.assets  import router as assets_router
from api.editor  import router as editor_router
from api.props   import router as props_router
from api.meshbank  import router as meshbank_router
from api.animbank  import router as animbank_router
from api.view      import router as view_router
from api.debug     import router as debug_router
from api.household import router as household_router
from api.admin     import router as admin_router

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
app.include_router(animbank_router,  prefix="/api")
app.include_router(editor_router,   prefix="/api/editor")
app.include_router(debug_router)
app.include_router(household_router, prefix="/api")
app.include_router(admin_router)

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

# Dedicated executor for tick() — kept separate from asyncio's shared
# default executor (which anyio/Starlette may also draw from for sync
# route handlers) so a long-running tick can never starve HTTP requests
# of a worker thread.
_tick_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tick")


def _run_tick_and_persist(sim_id: str) -> tuple[dict, dict]:
    """Runs the whole load->tick->persist span for one tick, held under
    _world_lock end to end. Bundled into one function (rather than the
    load/tick/cache/save calls each individually hopping to the executor,
    as before) so the lock — which must cover the entire span, since
    tick() reads/mutates world throughout its run, not just once — is
    acquired and released on this executor's background thread, never on
    the main event-loop thread (threading.Lock.acquire() is a blocking
    call; calling it directly inside async def loop() would freeze all
    HTTP/WebSocket handling while waiting on a lock some API route holds).

    Bonus: today only tick() itself ran via run_in_executor — load_world()
    and update_world_tick() ran inline on the event loop. Bundling
    everything here moves all of it off that thread too.
    """
    with _world_lock:
        world = load_world(sim_id)
        ensure_world_defaults(world)
        # Loaded fresh every tick (cheap on a cache hit) rather than once
        # at loop() startup — definitions.json edits via the Definitions
        # editor otherwise never reach a running simulation until restart,
        # even though save_definitions() already invalidates the read
        # cache correctly on its end.
        world["definitions"] = load_definitions(sim_id)

        tick(world)

        update_world_tick(sim_id, world["tick"])

        # Collect what changed this tick — must happen before persisting
        # below, since it pops world["_dirty"] (which holds raw Python
        # sets, not JSON-serializable) out of the tree entirely.
        dirty = collect_dirty(world)

        # Persist this tick's mutations. Without this, load_world() on the
        # next iteration serves a stale cached snapshot (or, once the 5s
        # Redis TTL expires, rebuilds from Postgres) and every character
        # decision / movement update / need decay this tick made is
        # silently discarded. Re-caching every tick also means the TTL
        # never actually expires during normal operation, so the expensive
        # cache-miss rebuild (build_world_geometry, generate_world_tiles,
        # build_outdoor_navigation, ...) only runs once at startup.
        #
        # world_tiles/world_tile_lookup/outdoor_navigation/etc. (~46MB of
        # static, purely-derived grid data) and "definitions" (loaded once,
        # never mutated through this path, ~71% of the blob's bytes) are
        # excluded here — see db.py's _STATIC_WORLD_KEYS, which load_world()
        # backfills on every call so no caller notices either is missing
        # from what's actually persisted.
        persisted_snapshot = {
            k: v for k, v in world.items()
            if k not in _STATIC_WORLD_KEYS
        }

        set_world_cache(sim_id, persisted_snapshot)

        # Durability: periodically persist to Postgres too, so simulation
        # progress survives a backend restart instead of only reflecting
        # whatever was last explicitly saved via the World Editor.
        if world["tick"] % 30 == 0:
            save_world(sim_id, persisted_snapshot)

    return world, dirty


async def loop():
    from core.tick_schedule import TICK_RATE_SECONDS

    world = {}  # only used for time_scale below; overwritten each iteration
                # on success, stays {} (-> default 1x) if the very first
                # tick throws before ever assigning it.

    while True:
        try:
            world, dirty = await asyncio.get_event_loop().run_in_executor(
                _tick_executor, _run_tick_and_persist, SIM_ID
            )

            # Broadcast to each client
            dead = []
            for client in _clients:
                ws   = client["ws"]
                cx   = client.get("cx", 0)
                cy   = client.get("cy", 0)
                zoom = client.get("zoom", 2)
                try:
                    if client.get("needs_full"):
                        snapshot = _build_full_snapshot(world, world["definitions"], cx, cy, zoom)
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
        except Exception:
            # This loop is a single long-lived background task that nothing
            # supervises or restarts — an unhandled exception here (e.g. the
            # psycopg2 "connection cannot be re-entered recursively" crash
            # this guards against, now also fixed at the source by db.py's
            # _conn_lock) used to kill the task outright, silently freezing
            # the whole simulation *and* every client's WebSocket feed
            # (broadcast happens from inside this same loop) until the
            # backend was restarted. Log and keep ticking instead.
            traceback.print_exc()

        # Server-side time-scale control (see api/admin.py) -- ticks fire
        # more often in real time as time_scale increases, which is what
        # actually speeds up everything counted in ticks (activity
        # durations, need decay, calendar). movement.py counter-scales its
        # own per-tick distance so walking speed on screen stays constant.
        time_scale = max(1, min(10, world.get("time_scale", 1)))
        await asyncio.sleep(TICK_RATE_SECONDS / time_scale)


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


@app.get("/social_debug.html")
def social_debug_page():
    path = Path(__file__).parent / "frontend" / "social_debug.html"
    return FileResponse(path)


@app.get("/meshbank.html")
def meshbank_page():
    path = Path(__file__).parent / "frontend" / "meshbank.html"
    return FileResponse(path)


@app.get("/animbank.html")
def animbank_page():
    path = Path(__file__).parent / "frontend" / "animbank.html"
    return FileResponse(path)


@app.get("/admin.html")
def admin_page():
    path = Path(__file__).parent / "frontend" / "admin.html"
    return FileResponse(path)


@app.get("/api/state")
def state():
    # FastAPI's default jsonable_encoder() (used for any raw dict/list
    # return value) recursively type-checks every value in pure Python —
    # measured ~7.5s on this payload vs. ~1s for a plain json.dumps() of
    # the same data. World state is already JSON-safe (it round-trips
    # through Redis via json.dumps every tick), so encode it directly.
    return Response(
        content=json.dumps(load_world(SIM_ID)),
        media_type="application/json",
    )


@app.get("/api/household/{household_id}")
def household(household_id: str):
    world = load_world(SIM_ID)
    return household_economy(world, household_id) or {"error": "not found"}


@app.post("/api/config/environment")
def update_environment(payload: dict):
    with world_lock():
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
    with world_lock():
        world = load_world(SIM_ID)
        world["llm_logs"] = []
        save_world(SIM_ID, world)
        return {"ok": True}
