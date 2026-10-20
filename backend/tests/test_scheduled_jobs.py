"""
Every scheduled job that used to be an every() block in tick() runs cleanly.

The blocks were moved into module-level functions mechanically; this calls each one against
a richly populated world (the pre-reset snapshot if present, else the live world) so a name
that only existed as a local of the old tick() body shows up here as a NameError.

Run inside the backend container:   python tests/test_scheduled_jobs.py
"""

import copy
import json
import os
import sys
import traceback

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]
import sim_loop
from core import scheduler
from db import load_world, _STATIC_WORLD_KEYS
from core.definitions import load_definitions
from systems.schema_defaults import ensure_world_defaults

live = load_world("default")
fixture = "/tmp/backup_world.json"
if os.path.exists(fixture):
    world = json.load(open(fixture, encoding="utf-8"))
    for k in set(_STATIC_WORLD_KEYS):
        if k in live:
            world[k] = live[k]
    source = "pre-reset snapshot"
else:
    world = copy.deepcopy(live)
    source = "live world"
world["definitions"] = load_definitions("default")
print(f"{len(scheduler._recurring)} recurring jobs; world: {source}, {len(world['characters'])} characters")

failures = []
for round_no in range(3):
    for owner, (every, offset) in sorted(scheduler._recurring.items()):
        ensure_world_defaults(world)
        world["tick"] += 7
        try:
            scheduler._handlers[owner](world, {"owner": owner, "key": "recurring", "payload": {}})
        except Exception:
            failures.append((owner, traceback.format_exc().strip().splitlines()[-1]))

seen = {}
for owner, err in failures:
    seen.setdefault((owner, err), 0)
    seen[(owner, err)] += 1
for (owner, err), n in seen.items():
    print(f"FAIL {owner}: {err}  (x{n})")
name_errors = [o for (o, e) in seen if "NameError" in e or "UnboundLocalError" in e]
print("jobs with a name error:", name_errors or "none")
print("ALL OK" if not name_errors else "FAILED")
sys.exit(1 if name_errors else 0)
