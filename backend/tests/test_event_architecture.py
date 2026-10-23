"""
Step 0 of the event-driven migration: tick profiling, section registry, event log and replay.

Run inside the backend container:   python tests/test_event_architecture.py
"""

import copy
import json
import re
import sys
import time

import os
os.environ.setdefault("COGNITION_MODE", "local")     # never reach a live cognition worker
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from core import event_bus, event_log, tick_profile, section_registry

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---- every mark in tick() is classified -------------------------------------------------
import sim_loop                        # registers the scheduled jobs that used to be tick() blocks
from core import scheduler
src = open("/app/sim_loop.py", encoding="utf-8").read()
labels = {section_registry.base_label(m) for m in re.findall(r'_prof\.mark\("([^"]+)"\)', src)}
missing = sorted(l for l in labels if section_registry.classify(l) is None)
check("every tick() section is in the registry", not missing, str(missing))
job_labels = {"every:" + section_registry.base_label(o) for o in scheduler._recurring}
missing_jobs = sorted(l for l in job_labels if l not in section_registry.REGISTRY)
check("every scheduled job is classified", not missing_jobs, str(missing_jobs))
stale = sorted(l for l in section_registry.REGISTRY if l not in labels and l not in job_labels)
check("registry has no entries for sections that no longer exist", not stale, str(stale))
print("   ", section_registry.summary())

# ---- profiler attributes time to the right section --------------------------------------
tick_profile.reset()
tick_profile.begin_tick()
tick_profile.mark("a"); time.sleep(0.02)
tick_profile.mark("b"); time.sleep(0.005)
tick_profile.mark("a"); time.sleep(0.01)
tick_profile.end_tick()
rep = tick_profile.report()
rows = {r["section"]: r for r in rep["sections"]}
check("profiler: section a gets both its slices", 0.028 < rows["a"]["total_s"] < 0.06, str(rows["a"]))
check("profiler: section b is small", rows["b"]["total_s"] < 0.02)
check("profiler: tick total covers the sections", rep["ticks"]["count"] == 1 and rep["ticks"]["avg_ms"] >= 30)
check("profiler: unknown labels are flagged UNCLASSIFIED", rows["a"]["kind"] == "UNCLASSIFIED")

# ---- event log --------------------------------------------------------------------------
from core.cache import r as _redis
event_log.STREAM_KEY = "simsland:events:test"   # never touch the live stream
_redis.delete(event_log.STREAM_KEY)             # the stream is durable: start this run from empty
event_bus.clear()
got = []
event_bus.subscribe("test_ping", lambda d, w: got.append(d["n"]))
def boom(d, w):
    raise ValueError("handler bug")
event_bus.subscribe("test_boom", boom)
event_log.set_tick(77)
for i in range(3):
    event_bus.emit("test_ping", {"n": i})
event_bus.emit("test_boom", {"x": 1})
world = {"tick": 77}
event_bus.flush(world)
check("handlers ran", got == [0, 1, 2], str(got))
rec = event_log.recent(10)
types = [e["type"] for e in rec][::-1]
check("all events are in the log, in order", types[-4:] == ["test_ping", "test_ping", "test_ping", "test_boom"], str(types))
check("events carry the tick", all(e["tick"] == 77 for e in rec[:4]))
stats = {(s["event"], s["handler"].split(".")[-1]): s for s in event_log.handler_stats()}
boom_stats = next(s for k, s in stats.items() if k[0] == "test_boom")
check("handler errors are counted", boom_stats["errors"] == 1 and boom_stats["calls"] == 1, str(boom_stats))
check("handler timing is recorded", all(s["total_ms"] >= 0 for s in stats.values()))

# export -> parse -> replay reproduces the handlers' effect and the bug
time.sleep(1.0)    # let the writer flush to Redis
text = event_log.export_jsonl(50)
parsed = event_log.parse_jsonl(text)
check("export is JSONL, oldest first", [e["type"] for e in parsed][-4:] == ["test_ping"] * 3 + ["test_boom"], str([e["type"] for e in parsed][-5:]))
stream = event_log.stream_range(5)
check("events reach the Redis stream", len(stream) >= 1 and stream[0]["type"] in ("test_ping", "test_boom"), str(stream[:1]))
got.clear()
n_before = len(event_log.recent(500))
summary = event_log.replay({"tick": 1}, [e for e in parsed if e["type"].startswith("test_")])
check("replay runs the live handlers", got == [0, 1, 2], str(got))
check("replay reports the handler error", len(summary["errors"]) == 1 and summary["errors"][0]["type"] == "test_boom", str(summary))
check("replay does not re-log events", len(event_log.recent(500)) == n_before)
only = event_log.replay({"tick": 1}, parsed, only_types={"test_ping"})
check("replay can be limited to event types", set(only["by_type"]) == {"test_ping"})

# ---- real tick: instrumented, sections sum to the tick, nothing unclassified ----------------
from db import load_world
from core.definitions import load_definitions
import core.event_handlers  # noqa: F401
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]
import sim_loop
from systems.schema_defaults import ensure_world_defaults

w = copy.deepcopy(load_world("default")); w["definitions"] = load_definitions("default")
tick_profile.reset()
for _ in range(60):
    ensure_world_defaults(w)
    sim_loop.tick(w)
rep = tick_profile.report()
secs = rep["sections"]
check("tick profile has sections", len(secs) > 50, str(len(secs)))
check("no unclassified sections in a real run", all(r["kind"] != "UNCLASSIFIED" for r in secs), str([r["section"] for r in secs if r["kind"] == "UNCLASSIFIED"]))
covered = sum(r["total_s"] for r in secs)
check("sections account for the whole tick", abs(covered - rep["ticks"]["total_s"]) < 0.05 * max(rep["ticks"]["total_s"], 0.01) + 0.02,
      f"sections {covered:.3f}s vs ticks {rep['ticks']['total_s']}s")
print("   ticks:", rep["ticks"])
print("   by kind:", json.dumps({k: {"sections": v["sections"], "total_s": v["total_s"], "active_pct": v["active_pct"]} for k, v in rep["by_kind"].items()}))
print("   top sections:", [(r["section"], r["total_s"], r["active_pct"]) for r in secs[:5]])

# overhead of the marks themselves
t0 = time.perf_counter()
tick_profile.begin_tick()
for i in range(20000):
    tick_profile.mark("x")
tick_profile.end_tick()
per_mark_us = (time.perf_counter() - t0) / 20000 * 1e6
check("a mark costs about a microsecond", per_mark_us < 5, f"{per_mark_us:.2f}us")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
