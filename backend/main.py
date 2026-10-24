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

import asyncio, os, json, traceback, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.cache import set_world_cache
from db import load_world, save_world, init_db, update_world_tick, world_lock, _world_lock, _STATIC_WORLD_KEYS
from sim_loop import tick, collect_dirty
from api.view import get_view, in_view, RESPONDER_FADE_TICKS
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
from api.social_sandbox import router as social_sandbox_router
from api.events    import router as events_router
from api.overview  import router as overview_router
from api.finances  import router as finances_router
from api.dependents import router as dependents_router
from api.director  import router as director_router
from api.middleware_bridge import router as middleware_bridge_router

from core.commands import command, core_only

app = FastAPI(title="Simsland")
app.add_middleware(
    CORSMiddleware,
    # localhost:5174 is the local `npm run dev` viewer (.claude/launch.json's
    # "viewer-dev" config) -- used for testing pages like operator_view.html
    # against this backend directly, without the nginx-built frontend
    # container. Plain WebSocket connections (main.js's ws://.../ws) aren't
    # subject to CORS, but director.py's fetch() calls from operator_view.js
    # are, so this needs to be here for the Director Panel to work in dev.
    allow_origins=["http://localhost:3000", "http://localhost:5174"],
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
app.include_router(social_sandbox_router)
app.include_router(events_router, prefix="/api")
app.include_router(overview_router, prefix="/api")
app.include_router(finances_router, prefix="/api")
app.include_router(dependents_router, prefix="/api")
app.include_router(director_router)
app.include_router(middleware_bridge_router)

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
    # ~25-30% wider than the strict "what's visible at this zoom" figure --
    # slack so ordinary pan/zoom drift stays inside the already-loaded
    # window instead of immediately falling outside it (see the WS
    # handler's movement-threshold check above, which relies on this
    # margin existing). Kept in sync with api/view.py's copy of this table.
    # Tier 0 covers camera.zoom values below the old tier-1 floor -- with
    # no minZoom on OrbitControls a user could scroll out indefinitely while
    # the loaded window stayed capped at radius 32, leaving everything past
    # that ring unloaded (a black void) instead of streaming more in.
    #
    # Doubled from the original {55,32,20,12} table -- confirmed live that
    # a second, real building placed ~25 tiles from map origin never loaded
    # in the game viewer (visible in the Floorplan/World Editor, which
    # isn't viewport-gated) because the default zoom tier's radius was too
    # small to reach it even at the default camera center. Loading a wider
    # area by default is worth the larger per-connect payload for a
    # single-player-scale sim.
    return {0: 110, 1: 64, 2: 40, 3: 24}.get(zoom, 40)


def _build_full_snapshot(world, definitions, cx, cy, zoom):
    """Full world slice for a given viewport — sent on first connect."""
    radius = _view_radius(zoom)
    return get_view(sim_id=SIM_ID, cx=cx, cy=cy, zoom=zoom)


def _character_patches(world: dict, visible_chars: dict, selected_id, sent: dict) -> dict:
    """Turn the visible dirty characters into what THIS client still needs.

    A character the client has never been sent goes whole. After that only the top-level keys
    whose value changed since what this client last got are sent -- for the character the client
    has selected the rarely-changing "cold" keys are re-checked every tick too, so the Inspector
    never lags, as {"__patch__": True, <key>: value, ...,
    "__deleted__": [keys]}; a character with nothing new is skipped entirely. A whole character
    is ~90 KB; a patch is usually a few hundred bytes. See core/entity_versions.py.
    """
    from core import entity_versions as ev
    tick = world.get("tick", 0)
    out = {}
    for cid, c in visible_chars.items():
        have = sent.get(cid)
        digests = ev.char_digests(c, tick, fresh_cold=(cid == selected_id))
        if have is None:
            out[cid] = c
            sent[cid] = digests
            continue
        changed = [k for k, d in digests.items() if have.get(k) != d]
        deleted = [k for k in have if k not in digests]
        if not changed and not deleted:
            continue
        patch = {"__patch__": True}
        for k in changed:
            patch[k] = c[k]
        if deleted:
            patch["__deleted__"] = deleted
        out[cid] = patch
        sent[cid] = digests
    return out


def _build_delta(world: dict, dirty: dict, cx: int, cy: int, zoom: int,
                 selected_id: str | None = None, sent: dict | None = None) -> dict | None:
    """
    Filter the dirty entities to only what falls within this client's viewport.
    Returns None if nothing in the delta is visible to this client.

    Confirmed live bug (player report: a followed character's position and
    Inspector state going stale -- "in totally different positions" --
    until a manual page refresh): the viewport filter below is exactly
    right for the 3D scene (no reason to update meshes nobody can see), but
    it silently starved whoever the CLIENT has selected in the Inspector
    too, the moment that character walked outside whatever area the camera
    happened to be centered on -- nothing ever marked it stale, their last
    known state just froze in place, unrelated to whether the character
    was actually still doing anything. `selected_id` (set via the client's
    own {"type":"select",...} WS message -- main.py's ws_endpoint) is
    force-included below regardless of camera position, same as if they
    were always in view.
    """
    radius = _view_radius(zoom)

    visible_chars = {
        cid: c for cid, c in dirty["chars"].items()
        if not c.get("is_workplace_npc")      # no position; would otherwise sit at the origin
        and in_view(c.get("x", 0), c.get("y", 0), cx, cy, radius)
    }
    if selected_id and selected_id in dirty["chars"] and selected_id not in visible_chars:
        visible_chars[selected_id] = dirty["chars"][selected_id]
    if sent is not None:
        visible_chars = _character_patches(world, visible_chars, selected_id, sent)
    visible_props = {
        pid: p for pid, p in dirty["props"].items()
        if in_view(p.get("x", 0), p.get("y", 0), cx, cy, radius)
    }
    visible_placed_items = {
        iid: i for iid, i in dirty["placed_items"].items()
        if in_view(i.get("x", 0), i.get("y", 0), cx, cy, radius)
    }
    visible_world_objects = {
        oid: o for oid, o in dirty["world_objects"].items()
        if in_view(o.get("x", 0), o.get("y", 0), cx, cy, radius)
    }

    # Responders (police/medical/fire) aren't dirty-tracked like the entity
    # types above -- there are only ever a handful active at once, so this
    # recomputes the current visible set fresh every tick from world state
    # directly (see api/view.py::get_view()'s identical filter for the
    # initial-connect snapshot) rather than wiring a new producer-side
    # dirty-marking call into every emergency.py call site that creates or
    # resolves one. Sent as the full current list, not a sparse delta, so
    # the frontend can just replace its tracked set wholesale each time.
    visible_responders = [
        r for r in world.get("responders", [])
        if (
            r.get("status") == "en_route"
            or (world.get("tick", 0) - r.get("arrival_tick", 0)) <= RESPONDER_FADE_TICKS
        )
        and in_view(r.get("location", {}).get("x", 0), r.get("location", {}).get("y", 0), cx, cy, radius)
    ]

    if (not visible_chars and not visible_props and not visible_placed_items
            and not visible_world_objects and not visible_responders):
        return None

    return {
        "type":          "delta",
        "characters":    visible_chars,
        "props":         visible_props,
        "placed_items":  visible_placed_items,
        "world_objects": visible_world_objects,
        "responders":    visible_responders,
        # current world tick -- see api/view.py::get_view()'s matching
        # field, both feed main.js's _worldState.tick.
        "tick":       world.get("tick", 0),
    }


# =========================================================
# MAIN LOOP
# =========================================================

# Dedicated executor for tick() — kept separate from asyncio's shared
# default executor (which anyio/Starlette may also draw from for sync
# route handlers) so a long-running tick can never starve HTTP requests
# of a worker thread.
_tick_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tick")

_resynced_clock_this_process = False


def _maybe_resync_clock_to_real_time(world):
    """Per the user's explicit ask: at 1x speed, the in-game clock is
    conceptually supposed to track real time -- but sim_time
    (sim_loop.py::advance_calendar()) only ever increments by a fixed
    TICK_RATE_SECONDS per tick, never resyncing to actual wall-clock time.
    Any time this process was stopped, restarted, or simply ticking
    slower than real-time (routine during active development), that gap
    silently accumulates forever -- confirmed live: the in-game clock had
    fallen 17 real days behind. Snap sim_time back to now, once, on this
    process's first tick, so a 1x-speed game's clock actually reads "now"
    again after a restart instead of resuming wherever it last left off.
    Only at 1x -- a deliberately sped-up (or slowed) simulation has
    already chosen to diverge from real time on purpose."""
    global _resynced_clock_this_process
    if _resynced_clock_this_process:
        return
    _resynced_clock_this_process = True
    if max(1, min(50, world.get("time_scale", 1))) == 1:
        world["sim_time"] = time.time()


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
    from core import world_state
    _t_wait = time.perf_counter()
    with _world_lock, world_state.hold():
        _t_held = time.perf_counter()
        _tick_watch["thread"] = threading.get_ident()
        _tick_watch["started"] = _t_held
        _tick_watch["reported"] = 0.0
        # The live world stays in memory between ticks (core/world_state.py): no per-tick load,
        # JSON round trip or database write. The idempotent ensure_* passes still run each tick.
        world = world_state.resident(sim_id)
        ensure_world_defaults(world)
        # Loaded fresh every tick (cheap on a cache hit) rather than once at loop() startup --
        # definitions.json edits via the Definitions editor otherwise never reach a running
        # simulation until restart, even though save_definitions() already invalidates the
        # read cache correctly on its end.
        defs = load_definitions(sim_id)
        if world.get("definitions") is not defs:
            world["definitions"] = defs
        from systems.schema_defaults import ensure_prop_template_fields
        from systems.electrical import ensure_power_outlets
        from systems.vehicles import ensure_vehicle_fields
        from systems.market import init_market_catalog
        ensure_prop_template_fields(world, defs)
        ensure_power_outlets(world, defs)
        ensure_vehicle_fields(world, defs)
        init_market_catalog(world)

        _maybe_resync_clock_to_real_time(world)

        from core import tick_state
        tick_state.enter()
        try:
            tick(world)
        finally:
            tick_state.leave()

        # Collect what changed this tick -- must happen before anything serialises the world,
        # since it pops world["_dirty"] (raw Python sets, not JSON-serialisable) out of the tree.
        dirty = collect_dirty(world)

        # Gateway replicas (core/replication.py): a no-op unless one is connected.
        from core import replication
        replication.publisher.publish(sim_id, world, dirty)

        _t_persist = time.perf_counter()
        # Durable persistence is write-behind: every PERSIST_EVERY_TICKS ticks the world is
        # serialised here (under the lock) and a background thread writes it to Postgres.
        world_state.after_tick(sim_id, world)
        _t_end = time.perf_counter()
        _tick_watch["started"] = None
        if _t_end - _t_held > SLOW_TICK_LOG_SECONDS:
            print(f"[tick] tick {world['tick']} held the world lock {_t_end - _t_held:.1f}s "
                  f"(waited {_t_held - _t_wait:.1f}s for it; tick {_t_persist - _t_held:.1f}s, "
                  f"persist {_t_end - _t_persist:.1f}s)", flush=True)

    return world, dirty


SLOW_TICK_LOG_SECONDS = 2.0
_tick_watch = {"thread": None, "started": None, "reported": 0.0}


def _tick_watchdog():
    """Logs the tick thread's stack whenever a tick has held the world lock longer than
    SLOW_TICK_LOG_SECONDS (once per 5s of that tick): the long holds are what turn API
    calls into "simulation busy" 503s, and a stack shows exactly what it is doing."""
    import sys
    while True:
        time.sleep(1.0)
        started, ident = _tick_watch.get("started"), _tick_watch.get("thread")
        if not started or not ident:
            continue
        held = time.perf_counter() - started
        if held < SLOW_TICK_LOG_SECONDS * 2 or held - _tick_watch.get("reported", 0.0) < 5.0:
            continue
        _tick_watch["reported"] = held
        frame = sys._current_frames().get(ident)
        if frame:
            stack = "".join(traceback.format_stack(frame)[-14:])
            print(f"[tick] still running after {held:.1f}s holding the world lock; tick thread is at:\n{stack}", flush=True)


async def _broadcast(world, dirty):
    """Send each connected client its snapshot or delta for this tick."""
    # Broadcast to each client
    dead = []
    for client in _clients:
        ws   = client["ws"]
        cx   = client.get("cx", 0)
        cy   = client.get("cy", 0)
        zoom = client.get("zoom", 2)
        try:
            if client.get("needs_full"):
                snapshot = _build_full_snapshot(world, world.get("definitions"), cx, cy, zoom)
                snapshot["type"] = "snapshot"
                # what this client now has of each character: the baseline later deltas
                # are patched against (core/entity_versions.py)
                from core import entity_versions as _ev
                client["sent"] = {
                    cid: _ev.char_digests(ch, world.get("tick", 0))
                    for cid, ch in (snapshot.get("characters") or {}).items()
                    if isinstance(ch, dict) and ch.get("id")
                }
                await ws.send_json(snapshot)
                client["needs_full"] = False
            else:
                delta = _build_delta(world, dirty, cx, cy, zoom, client.get("selected_id"),
                                     sent=client.setdefault("sent", {}))
                if delta:
                    await ws.send_json(delta)
        except Exception:
            # Log instead of swallowing: a bug in snapshot/delta
            # building (e.g. the missing RESPONDER_FADE_TICKS
            # import that used to crash _build_delta on every
            # single call) previously killed every client here
            # with zero trace, silently disabling all live
            # updates while still leaving reconnect+one-shot
            # snapshot working -- which looked exactly like
            # "nothing updates until I refresh".
            traceback.print_exc()
            dead.append(client)

    for client in dead:
        if client in _clients:
            _clients.remove(client)



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
            await _broadcast(world, dirty)
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
        time_scale = max(1, min(50, world.get("time_scale", 1)))
        await asyncio.sleep(TICK_RATE_SECONDS / time_scale)


# =========================================================
# STARTUP
# =========================================================

@app.on_event("shutdown")
def shutdown_persist():
    """The world lives in memory (core/world_state.py): write it out before the process exits.
    A gateway holds only a copy of the core's world and never writes it."""
    from core import commands
    if commands.ROLE == "api":
        return
    try:
        from core import replication
        replication.publisher.release()
    except Exception:
        pass
    try:
        from core import world_state
        world_state.persist_now(SIM_ID)
    except Exception as exc:
        print(f"[shutdown] could not persist the world: {exc!r}")


async def replica_loop(feed):
    """Gateway: whenever the core's frames have been applied to this process's copy of the world,
    send the connected clients what changed (the core's own loop() does the same after a tick)."""
    from core import replication, world_state
    loop = asyncio.get_event_loop()
    counter = -1
    resyncs = 0
    while True:
        counter = await loop.run_in_executor(None, feed.wait_for_update, counter, 1.0)
        try:
            feed.pump()                       # applied here, on the event-loop thread: nothing changes the world mid-broadcast
            if not feed.ready.is_set():
                continue
            if feed.stats["resyncs"] != resyncs:
                resyncs = feed.stats["resyncs"]
                for client in _clients:
                    client["needs_full"] = True
            world = world_state.replica_entry(SIM_ID).world
            dirty = replication.collect_dirty(world, feed.take_dirty())
            await _broadcast(world, dirty)
        except Exception:
            traceback.print_exc()


@app.on_event("startup")
async def startup():
    from core.memory_guard import start as _start_memory_guard
    _start_memory_guard()
    init_db()
    from core import commands
    if commands.ROLE == "api":
        # A gateway: no tick, no world of its own. It follows the core's world over Redis
        # (core/replication.py) and sends every mutation back as a command (core/commands.py).
        from core import replication
        feed = replication.Feed(SIM_ID, manual=True).start()
        app.state.feed = feed
        asyncio.create_task(replica_loop(feed))
        return
    # Answer commands from gateway processes (core/commands.py). A no-op cost when none exist.
    commands.serve()
    threading.Thread(target=_tick_watchdog, name="tick-watchdog", daemon=True).start()
    asyncio.create_task(loop())


# =========================================================
# WEBSOCKET ENDPOINT
# Clients should send JSON messages to update their viewport:
#   {"type": "viewport", "cx": 12, "cy": 8, "zoom": 2}
# =========================================================

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    client = {"ws": ws, "cx": 0, "cy": 0, "zoom": 2, "needs_full": True, "selected_id": None}
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

                # A full resnapshot tears down and rebuilds every tile mesh
                # outside the new radius window in one synchronous swap (see
                # main.js::updateTiles()) -- visibly "popping" whatever was
                # just at the edge. Re-triggering that on *any* cx/cy change
                # at all (even a 1-tile drift) made this happen constantly
                # during normal pan/zoom. Only resync once the camera has
                # moved far enough that the old radius window would actually
                # be stale -- a real move still resyncs immediately, small
                # drift just keeps riding deltas against the still-valid
                # window instead.
                radius = _view_radius(client["zoom"])
                moved = (
                    abs(new_cx - client["cx"]) > radius // 3
                    or abs(new_cy - client["cy"]) > radius // 3
                    or new_zoom != client["zoom"]
                )
                if moved:
                    client["cx"]         = new_cx
                    client["cy"]         = new_cy
                    client["zoom"]       = new_zoom
                    client["needs_full"] = True

            elif msg.get("type") == "select":
                # See _build_delta()'s selected_id parameter: this is what
                # keeps the Inspector's character live once the camera has
                # moved on from wherever they physically are.
                selected_id = msg.get("character_id")
                client["selected_id"] = selected_id
                if selected_id:
                    world = load_world(SIM_ID)
                    c = world.get("characters", {}).get(selected_id)
                    if c:
                        await ws.send_json({
                            "type": "delta",
                            "characters": {selected_id: c},
                            "tick": world.get("tick", 0),
                        })

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
@command("main.update_environment")
def update_environment(payload: dict):
    with world_lock():
        world = load_world(SIM_ID)
        world.setdefault("environment", {}).update(payload)
        save_world(SIM_ID, world)
        return world["environment"]


@app.get("/api/llm/logs")
@core_only
def llm_logs():
    world = load_world(SIM_ID)
    return world.get("llm_logs", [])


@app.delete("/api/llm/logs")
@command("main.clear_llm_logs")
def clear_llm_logs():
    with world_lock():
        world = load_world(SIM_ID)
        world["llm_logs"] = []
        save_world(SIM_ID, world)
        return {"ok": True}
