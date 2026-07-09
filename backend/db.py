import psycopg2, json, os
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

def init_db():
    with conn:
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

        return cached

    # =====================================
    # LOAD DB
    # =====================================

    with conn.cursor() as cur:

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
    build_world_geometry(
        sim_id,
        world
    )

    from world.world_tiles import (

        generate_world_tiles,

        build_world_tile_lookup,

        generate_road_gateways,
        build_traffic_network
    )

    if not world.get(
        "world_tiles"
    ):

        generate_world_tiles(
            world
        )

    build_world_tile_lookup(
        world
    )

    build_traffic_network(
        world
    )

    build_outdoor_navigation(
        world
    )

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
    with conn:
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

    with conn:
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

    with conn.cursor() as cur:

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
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE world
                SET data = jsonb_set(data, '{tick}', to_jsonb(%s::int))
                WHERE simulation_id=%s
            """, (tick, sim_id))