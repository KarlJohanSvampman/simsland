"""
API/gateway split, stage 1: mutations as commands (core/commands.py).

Uses its own stream/key names so a running core or gateway is never involved.

Run inside the backend container:   python tests/test_commands.py
"""

import json
import os
import subprocess
import sys
import threading
import time

os.environ["SIM_ROLE"] = "api"                      # this process plays the gateway
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from fastapi import HTTPException
from pydantic import BaseModel
from core import commands
from core.cache import r

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


q = commands.queue
q.rename("test:cmd")
q.alive_cache_seconds = 0.0
for k in (q.req_stream, q.res_stream):
    r.delete(k)
for k in r.scan_iter(match=q.worker_prefix + "*"):
    r.delete(k)


class Model(BaseModel):
    enabled: bool
    note: str = "x"


ran_in = []


@commands.command("t.add")
def add(x: int, y: int = 10):
    ran_in.append(threading.current_thread().name)
    return {"sum": x + y}


@commands.command("t.missing")
def missing(what: str):
    raise HTTPException(status_code=404, detail=f"{what} not found")


@commands.command("t.boom")
def boom():
    raise ValueError("bug")


@commands.command("t.model")
def model_cmd(req: Model, tag: str = "t"):
    return {"enabled": req.enabled, "note": req.note, "tag": tag, "type": type(req).__name__}


@commands.command("t.slow")
def slow(seconds: float):
    time.sleep(seconds)
    return {"slept": seconds}


@commands.command("t.odd")
def odd():
    import datetime
    return {"when": datetime.date(2026, 10, 24), "set": {1}}


check("in the api role a command is a stub", getattr(add, "__command__", None) == "t.add")

# ---- nobody serving ------------------------------------------------------------------------
try:
    add(1)
    check("no core -> 503", False)
except HTTPException as exc:
    check("no core -> 503", exc.status_code == 503, str(exc.status_code))

# ---- the owner side, in this process -------------------------------------------------------
rt = commands.serve(threads=4)
rt.worker_id = "test-core"
rt.heartbeat_seconds = 0.5
deadline = time.time() + 5
while q.workers_alive() == 0 and time.time() < deadline:
    time.sleep(0.1)
check("the core's heartbeat is seen", q.workers_alive() == 1)

check("a command returns its value", add(2, y=5) == {"sum": 7})
check("defaults are applied by the caller's signature", add(3) == {"sum": 13})
check("it ran on a serving thread", ran_in and ran_in[-1].startswith("commands-"), str(ran_in))

try:
    missing("household")
    check("HTTPException keeps its status", False)
except HTTPException as exc:
    check("HTTPException keeps its status and detail", exc.status_code == 404 and exc.detail == "household not found")

try:
    boom()
    check("an unexpected error is a 500", False)
except HTTPException as exc:
    check("an unexpected error is a 500", exc.status_code == 500 and "bug" in exc.detail, exc.detail)

out = model_cmd(Model(enabled=True), tag="z")
check("a pydantic argument is rebuilt on the core", out == {"enabled": True, "note": "x", "tag": "z", "type": "Model"}, str(out))
check("non-JSON return values are stringified, not lost", odd() == {"when": "2026-10-24", "set": "{1}"}, str(odd()))

try:
    commands.call("t.slow", {"seconds": 1.5}, timeout=0.4)
    check("a slow command times out as 504", False)
except HTTPException as exc:
    check("a slow command times out as 504", exc.status_code == 504)
time.sleep(1.5)

try:
    commands.call("nope", {})
    check("an unknown command is an error", False)
except HTTPException as exc:
    check("an unknown command is an error", exc.status_code == 500 and "unknown" in exc.detail)

# an expired command is dropped, not run late
before = len(ran_in)
q.enqueue({"id": "late", "command": "t.add", "args": {"x": 1, "y": 1}, "deadline": time.time() - 5})
time.sleep(2.5)
check("a command past its deadline is not run", len(ran_in) == before)

# concurrency: many callers at once, each gets its own answer
results = {}


def worker(i):
    results[i] = add(i, y=1000)


threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
t0 = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join(20)
check("forty concurrent callers each get their own answer",
      all(results.get(i) == {"sum": i + 1000} for i in range(40)), f"{len(results)} answered in {time.time()-t0:.1f}s")

# ---- the real routes ---------------------------------------------------------------------------
import main  # noqa: F401  (registers every command)
names = sorted(commands.REGISTRY)
real = [n for n in names if not n.startswith("t.")]
print(f"   {len(real)} real commands registered")
check("every converted route is registered", len(real) >= 42, str(len(real)))

import api.household as hh
check("a real route is a stub in this role", getattr(hh.set_name, "__command__", None) == "household.set_name")
res = hh.set_name(sim_id="cmd_test", payload={"household_id": "nope", "name": "x"})
check("a real command round-trips (nothing written: unknown household)", res == {"ok": False, "error": "household not found"}, str(res))

# ---- the route table is identical in both roles -------------------------------------------------
code = ("import json,sys,inspect;import main;"
        "rows=sorted((r.path,sorted(getattr(r,'methods',None) or []),list(inspect.signature(r.endpoint).parameters)) "
        "for r in main.app.routes if hasattr(r,'endpoint'));print(json.dumps(rows))")
tables = {}
for role in ("all", "api"):
    env = dict(os.environ, SIM_ROLE=role)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd="/app")
    try:
        tables[role] = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        tables[role] = out.stderr[-300:]
check("both roles expose the same routes and parameters", tables["all"] == tables["api"] and isinstance(tables["all"], list),
      str(tables)[:300])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
