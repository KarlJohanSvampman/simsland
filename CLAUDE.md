# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Simsland is a Dockerized AI society simulation: LLM-driven characters ("Sims") with bodies, households,
jobs, relationships, and a shared virtual town, rendered with Three.js. Backend decisions are produced by
a local/remote Ollama LLM. There is no automated test suite, linter, or CI config in this repo — validate
changes by running the stack and exercising the affected system/endpoint directly.

## Running the stack

```bash
cp .env.example .env        # if present; otherwise create backend/.env with the vars below
docker compose up --build
```
- Frontend: http://localhost:3000 (nginx serving the Vite build)
- Backend API/WS: http://localhost:8000
- Postgres: localhost:5432 (db `sim`, user/pass `postgres`)
- Redis: localhost:6379

If Ollama has no model pulled yet:
```bash
docker compose exec ollama ollama pull llama3
```
Note: `docker-compose.yml` currently points `OLLAMA_BASE_URL` at a hardcoded LAN address
(`http://192.168.0.7:11434`) rather than an `ollama` service in compose — update this env var to match
wherever Ollama is actually reachable.

Services (see `docker-compose.yml`):
- `backend` — FastAPI app (`uvicorn main:app --reload`), bind-mounts `./backend`, `./resources`, `./simulations`
- `worker` — separate process consuming the agent-tick queue (`python -m workers.worker`)
- `frontend` — Vite build served by nginx
- `db` — Postgres 16, initialized via `scripts/init_db.sql`
- `redis` — job queue + world/character cache + LLM response cache

### Running backend without Docker
```bash
./scripts/run_local.sh
```
Requires local Postgres/Redis/Ollama reachable at the URLs the script exports (override via env vars).

### Frontend dev server
```bash
cd frontend
npm install
npm run dev        # vite dev server
npm run build       # production build (multi-page, see vite.config.js)
npm run preview
```
The frontend is a multi-page Vite app (no framework/router): `index.html` (main sim viewer, `src/main.js`),
`editor.html` (`src/editor-main.js`), `definitions.html` (`src/definitions.js`), `floorplan.html`
(`src/floorplan.js`), `meshbank.html` (`src/meshbank.js`). All entry points are registered in
`vite.config.js` under `build.rollupOptions.input`.

### Key environment variables (backend)
- `DATABASE_URL` — Postgres connection string
- `REDIS_HOST` — Redis hostname
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL` — LLM endpoint and model name
- `TICK_RATE_SECONDS` — simulation tick interval (default `1.0`)
- `PYTHONPATH=/app` — required so `backend/` submodules import as top-level packages (`core.`, `systems.`, `brain.`, `llm.`, `api.`, `world.`)

## Backend architecture

Entry point `backend/main.py` boots a FastAPI app and, on startup, spawns an infinite async `loop()`
(distinct from the per-agent worker) that each `TICK_RATE_SECONDS`:
1. Loads world state (`db.load_world`), fills in schema defaults, loads simulation definitions.
2. Calls `sim_loop.tick(world)` — the world-level tick (economy, jobs, market, crises, weather-of-society
   systems — see below).
3. Persists the new tick number and enqueues one `agent_tick` Redis job per character.
4. Pushes the current view state to all connected WebSocket clients (`/ws`).

A **separate** `worker` container (`backend/workers/worker.py`) pulls batches of `agent_tick` jobs off
Redis (`core/redis_queue.py`, list-based queue `sim_jobs`) and runs `brain.agent_loop.update_agent` for
each character concurrently (bounded by an `asyncio.Semaphore`, `MAX_CONCURRENCY=5`). This is the actual
per-character cognition/action tick; `main.py`'s loop only advances world-level systems and dispatches work.

### State storage model
- **Postgres** is the source of truth: `world` table (one JSONB blob per `simulation_id`) and `characters`
  table (one JSONB row per character, keyed by `id` + `simulation_id`). See `backend/db.py` and
  `scripts/init_db.sql`. `db.py` also runs light schema migrations (`ALTER TABLE ... ADD COLUMN IF NOT
  EXISTS`) at `init_db()` time — add new migrations there rather than assuming a fresh schema.
- **Redis** is a short-TTL read cache in front of Postgres for `world` (5s TTL) and `character` (10s TTL)
  data (`core/cache.py`), plus the job queue and an LLM response cache (`llm/llm_client.py`, 300s TTL,
  keyed by a hash of the full message list).
- **Simulation "definitions"** (prop/item/character/interaction/activity/floorplan/trait/job/... templates)
  are static per-simulation JSON, not DB rows: `simulations/<sim_id>/definitions.json`, loaded via
  `core/definitions.py` / `api/editor.py`. World *state* (dynamic) and definitions (static templates) are
  deliberately separate — don't conflate them.
- World JSON must stay plain-JSON-safe: `core/cache.py` validates recursively before caching and raises
  loudly (`WORLD CACHE SERIALIZATION FAILED`) if a non-JSON type (e.g. a set, custom object) leaks into
  world/character state.

### Per-character tick (`brain/agent_loop.py: update_agent`)
Order matters and short-circuits: off-grid check → internal state (needs/emotion/memory decay/health) →
persistent desires → cooking → reflections → social intentions → economy (jobs/bills) → schedule runtime →
clean/sort intentions → **if already in an activity, execute it and return** → **if moving, continue and
return** → try starting an activity from the highest-priority intention → otherwise fall through to
`brain.llm_brain.think()` (LLM call) → `process_decision()` applies thought/emotion/intention/memory and
validates+executes any proposed action via `systems/action_validator.py`. The LLM is the *last resort*,
only reached when no scripted intention/activity/movement already claims the tick — most ticks for most
characters never touch the LLM.

### LLM access — two different queues, don't confuse them
- `llm/llm_client.py` (`call_llm` / `call_llm_safe`) — direct HTTP calls to Ollama's `/api/chat`, with a
  Redis-backed response cache and optional rolling per-session history. Used for the main synchronous
  decision path.
- `llm/llm_queue.py` — an in-process `asyncio.Queue` + single `worker()` coroutine that serializes LLM jobs
  one at a time (used by `llm/cognition_jobs.py` for social-interpretation reflections). This is separate
  from the Redis job queue in `core/redis_queue.py` (which dispatches *agent ticks* to the `worker`
  container, not LLM calls).

### `backend/systems/` and `backend/brain/` — ownership boundaries
This is a large, organically-grown module set. **`docs/architecture_,,map.md` is the authoritative
ownership doc — read it before touching movement, navigation, activities, intentions, occupancy, anchors,
transforms, or households.** Key rules it establishes:
- `llm_brain.py` + `context_builder.py` own subjective reasoning/cognition; they must never touch movement/animation/pathfinding.
- `activities.py` owns embodied execution/phase transitions (start → walking → arriving → using → finishing → complete); `activity_runtime.py` and `activity_state` are deprecated.
- `movement.py` owns route traversal/interpolation only — never destination choice.
- `navigation.py` (+ `world_pathfinding.py`) own route generation/room connectivity.
- `transforms.py` is the only place rotation/local-world conversion math should live.
- `intentions.py`/`intention.py` and `scheduling.py`'s old intention queues are deprecated in favor of `active_intentions` — don't extend the deprecated files, migrate off them gradually, don't delete outright.
When adding a new system, check that map first so you extend the authoritative module instead of creating a second source of truth.

`sim_loop.py: tick(world)` is the top-level orchestrator of *world*-scale systems (jobs market, economy,
crises, politics, elections, factions, migration, evictions, emergency dispatch, courts/jail, news/media,
household monitoring, deliveries, traffic) — it runs once per tick regardless of character count, then
iterates characters for the lighter per-character world-level updates (perception, memory decay,
relationships-with-others). Character *cognition* itself happens later, per-character, in the `worker`
process via `agent_loop.py`.

### API routers (`backend/api/`)
Mounted in `main.py`: `view` (world/viewport queries, no prefix), `assets`, `props`, `meshbank` (all under
`/api`), `editor` (under `/api/editor`, reads/writes `simulations/<sim_id>/definitions.json` and world
JSON directly — this is the world/definitions editor backend, not simulation runtime). `/ws` is the single
WebSocket endpoint pushing view-state snapshots each tick to connected clients.

## Frontend architecture

Vanilla JS + Three.js (no framework). `src/main.js` is the main 3D viewer: orthographic camera, GLTF/skeleton
loading with caching (`modelCache`, `materialCache`), raycasting for selection, polling/streaming world
state and rendering props/characters/floorplans. `src/templates.js` resolves definition templates
(prop/character/floorplan/material) fetched from the backend. `src/editor-main.js`, `floorplan.js`,
`meshbank.js`, `definitions.js` are separate standalone tools (also multi-page Vite entries) for authoring
world content rather than viewing the live simulation — check which HTML entry point you're editing before
assuming shared state with the main viewer.

## Conventions to be aware of

- Backend code favors heavily vertically-spread function calls (one argument per line) in many files —
  this is the prevailing style in `systems/`, `brain/`, and `db.py`; match it in files that already use it
  rather than reformatting to a denser style.
- Imports are frequently local (inside functions, e.g. `brain/agent_loop.py`'s `update_agent`) to avoid
  circular imports between `systems/`, `brain/`, and `llm/` — follow the existing pattern rather than
  hoisting to module scope if you hit a circular import.
- There's no request-time auth — this is a local/dev-oriented project (CORS only allows
  `http://localhost:3000`).
