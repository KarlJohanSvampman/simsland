"""
tools/partition_runner.py -- one partition as its own process, on the determinism fixture (docs/step5b_plan.md, slice 3).

    python tools/partition_runner.py <sim> <partition> <n> <ticks> <out.json>

Builds the same fixture world every partition starts from (households spread over the partitions by
core/ownership.py), runs `ticks` steps in lockstep with the others -- a Redis counter per step is the barrier --
exchanging patches and frames over Redis streams (core/partitions.py::RedisTransport), lets the last messages in, and
writes its copy of every shared entity, its stats and any errors to out.json. tests/test_partition_processes.py runs
three of these and compares what they wrote.
"""

import itertools
import json
import os
import random
import sys
import time
import traceback
from collections import Counter

os.environ.setdefault("COGNITION_MODE", "local")
os.environ.setdefault("DET_POLICY", "social")
os.environ.setdefault("DET_SETUP", "together")
os.environ["DET_VIEW"] = "1"
sys.path.insert(0, "/app")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sim, p, n, ticks, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]

from tests import determinism as D  # noqa: E402
from core import ownership, partitions, world_view  # noqa: E402
from core.cache import r  # noqa: E402
import brain.intentions as _bi  # noqa: E402
import sim_loop  # noqa: E402
from systems.schema_defaults import ensure_world_defaults_if_due  # noqa: E402

D._install()
D._Clock.t = 1.7e9
D._Clock.counter = itertools.count(1)
D._think_calls = itertools.count(1)
random.seed(1234 + p)
_bi._intention_seq = 0
w = D.fixture("2026-11-04T09:00:00")
w = world_view.install(w)
D._together(w)
ownership.assign(w, n)
node = partitions.Node(w, p, partitions.RedisTransport(n, sim), sim_id=f"{sim}_")


def barrier(name):
    key = f"part:{sim}:bar:{name}"
    r.incr(key)
    r.expire(key, 3600)
    deadline = time.monotonic() + 120
    while int(r.get(key) or 0) < n:
        if time.monotonic() > deadline:
            raise TimeoutError(f"partition {p}: the others never reached {name}")
        time.sleep(0.002)


errs = Counter()
for i in range(ticks):
    ensure_world_defaults_if_due(node.world)
    D._Clock.t += 1.0
    try:
        node.tick(sim_loop.tick)
    except Exception:
        errs[traceback.format_exc().strip().splitlines()[-1]] += 1
    barrier(f"t{i}")
for k in range(3):                       # the last messages in: patches to owners, their frames back to everyone
    node.settle()
    barrier(f"s{k}")

shared = {f"{kind}|{eid}": partitions._dumps(partitions._get(node.world, (kind, eid)))
          for kind, eid in partitions._keys(node.world)}
with open(out, "w") as f:
    json.dump({"partition": p, "stats": node.stats, "errors": dict(errs), "entities": shared,
               "owners": node.world.get("_owners"),
               "last_run": {cid: (c.get("_wake") or {}).get("last") for cid, c in
                            dict.items(node.world.get("characters") or {})},
               "sim_time": node.world.get("sim_time")}, f)
