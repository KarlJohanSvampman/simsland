"""
A freshly loaded world always has its buildings' rooms resolvable, whichever way it was loaded.

systems/navigation.py's NAV_CACHE (building id -> floorplan lookups) is process-local. It used to be filled for the
world's buildings only when db._load_world_cold() took its Postgres branch (build_world_geometry); the Redis branch
-- taken whenever any other process had cold-loaded the same world in the last 5 seconds (core/cache.py::
set_world_cache's TTL) -- skipped it, so the process saw room_label=None on every household event until something
lazily primed the building (systems/lighting.py). That made tests/test_determinism.py flake whenever the live core
restarted just before it, and it is a real (small) bug for a restarted core.

Run inside the backend container:   python tests/test_nav_cache_priming.py
"""

import json
import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import db
from systems import navigation

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


real_get = db.get_world_cache
real_set = db.set_world_cache
db.set_world_cache = lambda sim_id, world: None                   # don't leave a cache entry behind for anyone else

db.get_world_cache = lambda sim_id: None                            # the Postgres branch
world = db._load_world_cold("default")
ids = [b["id"] for b in world.get("buildings", [])]
check("the world has buildings to resolve rooms in", len(ids) > 0, str(ids))
check("the Postgres branch primes the navigation cache for every building", all(i in navigation.NAV_CACHE for i in ids))

static = set(db._STATIC_WORLD_KEYS)
blob = json.dumps({k: v for k, v in world.items() if k not in static}, default=str)

navigation.NAV_CACHE.clear()                                        # a fresh process
db.get_world_cache = lambda sim_id: json.loads(blob)                # the Redis branch
cached = db._load_world_cold("default")
missing = [i for i in ids if i not in navigation.NAV_CACHE]
check("the Redis branch primes it too", not missing, f"missing {missing}")

# and rooms really resolve
b = next(b for b in cached["buildings"] if b["id"] in ids)
room = None
for p in cached.get("props", []):
    if p.get("building_id") == b["id"]:
        room = navigation.get_room_at_position(b, p.get("x"), p.get("y"))
        if room:
            break
check("a position inside a building resolves to a room", room is not None)

db.get_world_cache = real_get
db.set_world_cache = real_set
print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
