"""Build a populated world for the determinism harness when no backups/ snapshot is at hand (a fresh checkout, CI):
tests/house_world (the live 3-household world, rebuilt offline) + defaults, stored as the default world in Postgres
and as /tmp/backup_world.json -- the two must agree, because tests/determinism.py takes the static map from the
former and everything else from the latter.

    python tools/make_det_fixture.py        (inside the backend container, or with DATABASE_URL / REDIS_HOST set)

This overwrites the "default" world in the database it points at -- never run it against a world you want to keep.
"""
import json, os, sys, time
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/tests")
os.environ.setdefault("COGNITION_MODE", "local")
from house_world import make_world
from systems.schema_defaults import ensure_world_defaults
from db import save_world, _STATIC_WORLD_KEYS, init_db
from core import world_state
init_db()
from db import load_world
existing = load_world("default")
if len(existing.get("characters") or {}) > 1 and "--force" not in sys.argv:
    sys.exit(f"refusing: the database already holds a world with {len(existing['characters'])} characters "
             "(pass --force to overwrite it)")
w = make_world()
w["simulation_id"] = "default"
ensure_world_defaults(w)
from datetime import datetime
w["sim_time"] = datetime.fromisoformat("2026-11-01T08:00:00").timestamp()
save_world("default", w)
world_state.persist_now("default")
dyn = {k: v for k, v in w.items() if k not in set(_STATIC_WORLD_KEYS) and k != "definitions"}
json.dump(dyn, open("/tmp/backup_world.json", "w"), default=str)
print("characters", len(w["characters"]), "keys", len(dyn), "bytes", os.path.getsize("/tmp/backup_world.json"))
