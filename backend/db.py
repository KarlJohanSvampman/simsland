import psycopg2, json, os, threading
from contextlib import contextmanager
from fastapi import HTTPException
from core.cache import get_world_cache, set_world_cache
from core.cache import get_char_cache, set_char_cache
from systems.schema_defaults import (
    ensure_world_defaults
)
from world.generate_world import generate_initial_world
from systems.prop_index import (
    cache_prop_index
)
from core.definitions import (
    load_definitions
)
from systems.room_assignment import (
    assign_prop_rooms
)
from systems.outdoor_navigation import (
    build_outdoor_navigation
)
from systems.building_manager import (
    build_world_geometry
)
import time

# =========================================================
# PROCESS-LOCAL STATIC WORLD DATA CACHE
# =========================================================
# world_tiles (the outdoor 300x300 grid) is ~16MB, and world_tile_lookup/
# outdoor_navigation/road_graph/etc. (purely derived from it, no data of
# their own) add another ~30MB — re-serializing/deserializing ~46MB of
# static grid data on every single load_world() call (which happens on
# every tick AND every incoming request that reads world state) was
# causing multi-second latency under any concurrent load. All of it is
# excluded from the Redis-cached/Postgres-persisted world blob (see
# main.py::loop()) and instead computed once per backend process here.
#
# Since this lives outside the world dict's normal persistence, edits to
# world_tiles made anywhere other than the World Editor's save endpoint
# (which calls invalidate_static_world_cache() below) won't be reflected
# here until the backend container restarts.
_STATIC_WORLD_KEYS = (
    "world_tiles",
    "world_tile_lookup", "outdoor_navigation",
    "road_entry_points", "road_exit_points", "road_graph", "traffic",
    # "definitions" is loaded once and never mutated through any
    # save_world/set_world_cache path (the one real mutator,
    # api/editor.py's save_definitions(), writes straight to the JSON
    # file on disk) — it was ~71% of the persisted blob's bytes, and
    # excluding it just needs load_world() to keep backfilling it (see
    # below) so no caller notices it's no longer actually persisted.
    "definitions",
)
_static_world_cache = {}


def _ensure_static_world_data(world, sim_id):
    cached_static = _static_world_cache.get(sim_id)

    if cached_static is not None:
        world.update(cached_static)
        return

    from world.world_tiles import (
        generate_world_tiles,
        build_world_tile_lookup,
        build_traffic_network
    )

    if not world.get("world_tiles"):
        generate_world_tiles(world)

    build_world_tile_lookup(world)
    build_traffic_network(world)
    build_outdoor_navigation(world)

    _static_world_cache[sim_id] = {
        k: world[k] for k in _STATIC_WORLD_KEYS if k in world
    }


def invalidate_static_world_cache(sim_id):
    """Drop the cached static grid data so the next load_world() rebuilds it
    from scratch (procedural regeneration). Only correct when there is no
    edited world_tiles to restore from — otherwise use
    refresh_static_world_cache(), which preserves edits. NOT called from the
    generic save_world() path, since the tick loop's durability saves go
    through that too and unconditionally invalidating there would
    reintroduce the rebuild cost this cache exists to avoid."""
    _static_world_cache.pop(sim_id, None)


def refresh_static_world_cache(sim_id, world_tiles):
    """Rebuild the process-local static-world cache from an edited
    world_tiles array (e.g. from the World Editor's save) instead of
    discarding it. Popping the cache alone isn't enough here: world_tiles is
    deliberately excluded from the Redis/Postgres-persisted world blob (see
    main.py::loop()), so the next cache-miss rebuild would fall back to pure
    procedural regeneration and silently lose the edit. Rebuilding the
    derived structures (lookup/traffic/nav) directly from the posted tiles
    and re-caching them makes editor terrain edits stick for the life of
    this process, same as the original procedurally-generated grid did."""
    if not world_tiles:
        invalidate_static_world_cache(sim_id)
        return

    from world.world_tiles import (
        build_world_tile_lookup,
        build_traffic_network
    )

    world = {"world_tiles": world_tiles}
    build_world_tile_lookup(world)
    build_traffic_network(world)
    build_outdoor_navigation(world)

    _static_world_cache[sim_id] = {
        k: world[k] for k in _STATIC_WORLD_KEYS if k in world
    }


#conn = psycopg2.connect(
#    dbname=os.getenv("POSTGRES_DB","sim"),
#    user=os.getenv("POSTGRES_USER","postgres"),
#    password=os.getenv("POSTGRES_PASSWORD","postgres"),
#    host=os.getenv("POSTGRES_HOST","db")
#)

def connect_with_retry():
    for i in range(10):
        try:
            return psycopg2.connect(
                os.getenv("DATABASE_URL")
            )
        except Exception as e:
            print(f"DB not ready, retrying... ({i})")
            time.sleep(2)
    raise Exception("Could not connect to DB")

conn = connect_with_retry()
# Reads elsewhere in this module only close their cursor, not the
# transaction (e.g. load_world/load_character do `with conn.cursor()`,
# which never commits) — under the default autocommit=False, every read
# left the shared connection sitting "idle in transaction" indefinitely.
# That's harmless until something needs a stronger lock (e.g. an ALTER
# TABLE in init_db() on the next restart), which then hangs behind it.
# Autocommit removes the open-transaction state entirely; the `with conn:`
# blocks used for writes still work fine (their commit/rollback becomes a
# no-op since each statement is already committed as it executes).
conn.autocommit = True

# psycopg2 connections aren't safe for concurrent use from multiple
# threads. This one module-level `conn` is touched both from main.py's
# dedicated tick executor thread (every tick, via update_world_tick/
# save_world) and from FastAPI's own request threadpool (any plain `def`
# route — e.g. the World Editor's POST /world — runs there, off the main
# event loop). When those two threads' `with conn:`/`with conn.cursor()`
# blocks overlapped, psycopg2 raised "the connection cannot be re-entered
# recursively", which crashed main.py's loop() task outright — since
# nothing supervises/restarts that task, the whole simulation (and every
# client's WebSocket feed, which is broadcast from inside the same loop)
# silently froze until the backend was restarted. Serializing all access
# to `conn` through this lock closes that race. RLock (not Lock) because
# init_db() calls save_world() while already holding the lock itself.
_conn_lock = threading.RLock()

# A second, broader lock: `_conn_lock` only protects the psycopg2 connection
# object itself from concurrent use, not the read-modify-write span around
# it. Two callers can each safely `load_world()` (no conn contention) then
# both `save_world()` moments apart, and whichever writes last silently
# discards the other's changes — this is exactly how main.py's tick loop
# was found to be clobbering out-of-band API writes (a prop move via the
# World Editor, reverted within ~1-2s with zero errors). No existing
# versioning/dirty-tracking is granular enough for a partial-merge fix
# (collect_dirty() only tracks characters that got an LLM tick this cycle,
# never props/buildings/households — see sim_loop.py), and props/buildings/
# households/characters are all mutated by *both* the tick loop and API
# routes, so no safe key-level partition exists either. Full mutual
# exclusion over the whole read-modify-write span, on both sides, is the
# correct fix.
_world_lock = threading.Lock()   # not RLock — no call path re-enters it


@contextmanager
def world_lock(timeout=30):
    """API routes should wrap their load_world()->mutate->save_world() body
    in `with world_lock():`, not the raw _world_lock directly — this gives
    a bounded wait with a clear 503 instead of an open-ended hang. The tick
    loop's own critical section can genuinely take up to ~150s in the
    worst case (an LLM call's timeout — see llm_client.py) since tick()
    reads/mutates world throughout its run, not just once, so it uses the
    raw _world_lock (unbounded wait is fine for a background task). A 503
    here means "simulation busy, retry" — expected under load, not a bug.
    """
    acquired = _world_lock.acquire(timeout=timeout)
    if not acquired:
        raise HTTPException(status_code=503, detail="simulation busy, try again")
    try:
        yield
    finally:
        _world_lock.release()


def init_db():
    with _conn_lock, conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id TEXT PRIMARY KEY,
                simulation_id TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                version INTEGER DEFAULT 0,
                data JSONB
            );
            """)
            # =====================================
            # MIGRATIONS
            # =====================================

            cur.execute("""

            ALTER TABLE characters

            ADD COLUMN IF NOT EXISTS simulation_id TEXT;

            """)

            cur.execute("""

            ALTER TABLE characters

            ADD COLUMN IF NOT EXISTS updated_at
            TIMESTAMP DEFAULT NOW();

            """)

            cur.execute("""

            ALTER TABLE characters

            ADD COLUMN IF NOT EXISTS version
            INTEGER DEFAULT 0;

            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS world (
                simulation_id TEXT PRIMARY KEY,
                data JSONB
            );
            """)

            cur.execute("""

            SELECT simulation_id
            FROM world
            WHERE simulation_id=%s

            """, ("default",))

            exists = cur.fetchone()

    # save_world() acquires _conn_lock and re-enters `conn` as its own
    # context manager -- both of which are already held by the `with`
    # block above, and neither is reentrant (a plain threading.Lock isn't,
    # and psycopg2 raises "the connection cannot be re-entered
    # recursively" for the connection). Must run after that block has
    # released both, not inside it.
    if not exists:

        world = generate_initial_world()

        save_world(
            "default",
            world
        )

def load_world(sim_id):

    # =====================================
    # TRY CACHE
    # =====================================
    cached = get_world_cache(sim_id)

    if cached:

        ensure_world_defaults(
            cached
        )

        # world_tiles/world_tile_lookup/outdoor_navigation/etc. are
        # deliberately excluded from the cached blob (see main.py::loop())
        # — restore them from the process-local static-world cache (or
        # build it once) instead of recomputing/re-deserializing ~46MB on
        # every single load_world() call.
        if not cached.get("world_tiles") or not cached.get("outdoor_navigation"):
            _ensure_static_world_data(cached, sim_id)

        # "definitions" is excluded from the cached blob too (see
        # _STATIC_WORLD_KEYS above) — every caller of load_world() still
        # expects it populated, so backfill it the same way.
        if "definitions" not in cached:
            cached["definitions"] = load_definitions(sim_id)

        return cached

    # =====================================
    # LOAD DB
    # =====================================

    with _conn_lock, conn.cursor() as cur:

        cur.execute(

            """
            SELECT data
            FROM world
            WHERE simulation_id=%s
            """,

            (sim_id,)
        )

        row = cur.fetchone()

        world = (

            row[0]

            if row else {

                "tick": 0,

                "characters": {},

                "props": []
            }
            
        )

    # =====================================
    # WORLD DEFAULTS
    # =====================================
    ensure_world_defaults(
        world
    )
    for c in world.get(
        "characters",
        {}
    ).values():

        ensure_character_defaults(
            c
        )
    # =====================================
    # LOAD DEFINITIONS
    # =====================================

    definitions = load_definitions(
        sim_id
    )
    # See the cache-hit branch above — every caller of load_world()
    # expects world["definitions"] populated even though it's excluded
    # from what actually gets persisted.
    world["definitions"] = definitions
    build_world_geometry(
        sim_id,
        world
    )

    _ensure_static_world_data(world, sim_id)

    # =====================================
    # FIND FLOORPLAN
    # =====================================

    floorplans = definitions.get(
        "floorplan_templates",
        {}
    )

    default_floorplan = None

    if floorplans:

        default_floorplan = next(
            iter(floorplans.values())
        )

    # =====================================
    # AUTO ASSIGN PROP ROOMS
    # =====================================

    if default_floorplan:

        # Floorplan templates are position-less; inject world-origin defaults
        # so world_to_local can compute local coords (buildings start at 0,0).
        building_ctx = {"x": 0, "y": 0, "rotation": 0, **default_floorplan}

        assign_prop_rooms(

            building_ctx,

            world.get(
                "props",
                []
            )
        )

    # =====================================
    # BUILD PROP INDEX
    # =====================================

    cache_prop_index(

        sim_id,

        world,

        definitions
    )

    # =====================================
    # CACHE WORLD
    # =====================================

    set_world_cache(
        sim_id,
        world
    )

    return world

def save_world(sim_id, world):
    with _conn_lock, conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO world (simulation_id, data)
                VALUES (%s, %s)
                ON CONFLICT (simulation_id)
                DO UPDATE SET data=%s
            """, (sim_id, json.dumps(world), json.dumps(world)))

    # 🔥 update cache
    set_world_cache(sim_id, world)


def save_character_safe(c, sim_id="default"):

    with _conn_lock, conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE characters
                SET data=%s, updated_at=NOW()
                WHERE id=%s AND simulation_id=%s
            """, (json.dumps(c), c["id"], sim_id))

    # 🔥 update cache immediately
    set_char_cache(sim_id, c["id"], c)

# =====================================================
# CHARACTER DEFAULTS
# =====================================================

def ensure_character_defaults(c):

    # =====================================
    # LEGAL
    # =====================================

    legal = c.setdefault(
        "legal",
        {}
    )

    legal.setdefault(
        "status",
        "free"
    )

    legal.setdefault(
        "jail_until",
        None
    )

    legal.setdefault(
        "trial_tick",
        None
    )

    legal.setdefault(
        "record",
        []
    )

    # =====================================
    # STATUS
    # =====================================

    status = c.setdefault(
        "status",
        {}
    )

    status.setdefault(
        "reputation",
        0.5
    )

    # =====================================
    # ECONOMY
    # =====================================

    c.setdefault(
        "money",
        100
    )

    c.setdefault(
        "hourly_wage",
        0
    )

    c.setdefault(
        "employed",
        False
    )

    c.setdefault(
        "job_searching",
        False
    )

    # =====================================
    # SOCIAL
    # =====================================

    c.setdefault(
        "relationships",
        {}
    )

    c.setdefault(
        "social_models",
        {}
    )

    c.setdefault(
        "conversation_memory",
        []
    )

    # =====================================
    # MEMORY
    # =====================================

    c.setdefault(
        "memories",
        []
    )

    c.setdefault(
        "story_arc",
        []
    )

    # =====================================
    # ACTIVITIES
    # =====================================

    c.setdefault(
        "activity",
        None
    )

    c.setdefault(
        "intentions",
        []
    )

    # =====================================
    # OFFGRID
    # =====================================

    c.setdefault(
        "off_grid",
        False
    )

    c.setdefault(
        "off_grid_reason",
        None
    )

def load_character(

    cid,

    sim_id="default"
):

    with _conn_lock, conn.cursor() as cur:

        cur.execute(

            """
            SELECT data
            FROM characters
            WHERE id=%s
            AND simulation_id=%s
            """,

            (
                cid,
                sim_id
            )
        )

        row = cur.fetchone()

        if not row:
            return None

        c = row[0]

        ensure_character_defaults(
            c
        )

        return c

def update_world_tick(sim_id, tick):
    with _conn_lock, conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE world
                SET data = jsonb_set(data, '{tick}', to_jsonb(%s::int))
                WHERE simulation_id=%s
            """, (tick, sim_id))