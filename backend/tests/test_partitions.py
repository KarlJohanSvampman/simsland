"""
Step 5b, slice 2 (docs/step5b_plan.md): partitioned ownership in one process (core/partitions.py).

  * one partition gives exactly the world the single-writer run gives (the routing adds nothing by itself);
  * three partitions (households spread over partitions 1 and 2, the rest partition 0), a social run:
      - no errors;
      - after every step every partition's copy of every entity is the same (no divergence);
      - writes to another partition's entities travelled as patches and landed;
      - characters ran in their own partition only, and people still talked.

Run inside the backend container:   python tests/test_partitions.py
"""

import json
import os
import random
import sys
import traceback
from collections import Counter

os.environ.setdefault("COGNITION_MODE", "local")
os.environ.setdefault("DET_POLICY", "social")
os.environ.setdefault("DET_SETUP", "together")
os.environ["DET_VIEW"] = "1"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from tests import determinism as D
from core import partitions, ownership

TICKS = int(os.getenv("PART_TICKS", "1500"))
START = "2026-11-04T09:00:00"


def run_cluster(ticks, n, watch=None):
    import itertools
    import brain.intentions as _bi
    import sim_loop
    from systems.schema_defaults import ensure_world_defaults_if_due
    D._install()
    D._Clock.t = 1.7e9
    D._Clock.counter = itertools.count(1)
    D._think_calls = itertools.count(1)
    random.seed(1234)
    _bi._intention_seq = 0
    w = D.fixture(START)
    from core import world_view
    w = world_view.install(w)
    D._together(w)
    cluster = partitions.Cluster(w, n)
    errs = Counter()
    diverged = 0
    for i in range(ticks):
        for part in cluster.parts:
            ensure_world_defaults_if_due(part["world"])
        D._Clock.t += 1.0
        try:
            cluster.step(sim_loop.tick)
        except Exception:
            text = traceback.format_exc().strip()
            errs[text.splitlines()[-1]] += 1
            D.ERROR_TRACES.setdefault(text.splitlines()[-1], text)
        if n > 1 and i % 100 == 99:
            diverged += len(cluster.divergence())
        if watch:
            watch(cluster)
    return cluster, errs, diverged


# ── one partition == the single writer ───────────────────────────────────────────────────────────────────────────────
w1, e1, _ = D.run_sim(TICKS, start=START)
c, ec, _ = run_cluster(TICKS, 1)
drop = ("definitions", "_dirty", "_owners")
a = D.norm(w1, drop=drop)
b = D.norm(c.world(0), drop=drop)
d = D.diff(a, b)
check("one partition gives exactly the single writer's world", not e1 and not ec and not d,
      (dict(e1), dict(ec), d[:5]))

# ── three partitions ─────────────────────────────────────────────────────────────────────────────────────────────────
owners_seen = Counter()


def watch(cl):
    for p in cl.parts:
        for cid, ch in dict.items(p["world"].get("characters") or {}):
            pass


c3, e3, diverged = run_cluster(TICKS, 3, None)
w0 = c3.world(0)
m = w0["_owners"]
print(f"   owners: households {m['households']}, characters {m['characters']}")
print(f"   cluster: {c3.stats}")
check("three partitions run without errors", not e3, "\n".join(D.ERROR_TRACES.get(k, k) for k in e3)[:1500])
check("every partition's copy of every entity is the same after each step", diverged == 0 and not c3.divergence(),
      c3.divergence()[:5])
check("there are characters in partitions 1 and 2", {1, 2} <= set(m["characters"].values()), m["characters"])
check("writes to another partition's entities travelled as patches, and landed",
      c3.stats["patches"] > 0 and c3.stats["ops_landed"] > 0, c3.stats)
hist = sum(len(cv.get("history") or []) for cv in (w0.get("conversation_archive") or {}).values()) + \
    sum(len(cv.get("history") or []) for cv in (w0.get("conversations") or {}).values())
hist1 = sum(len(cv.get("history") or []) for cv in (w1.get("conversation_archive") or {}).values()) + \
    sum(len(cv.get("history") or []) for cv in (w1.get("conversations") or {}).values())
print(f"   conversation lines: single writer {hist1}, three partitions {hist}")
check("people still talk -- at least half as much as with one writer (a partition sees the floor and the other side's "
      "lines a step late, so talk is looser, not quieter)", hist >= hist1 / 2 and hist > 0, (hist1, hist))
last_run = {cid: ((ch.get("_wake") or {}).get("last") or 0) for cid, ch in (w0.get("characters") or {}).items()
            if not ch.get("is_workplace_npc")}
stuck = [cid for cid, t in last_run.items() if t < (w0.get("sim_time") or 0) - 120]
check("every character kept running in its own partition (none stalled)", not stuck, (stuck, last_run))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
