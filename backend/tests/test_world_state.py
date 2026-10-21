"""
The world lives in memory (core/world_state.py): resident identity, snapshot isolation, in-place
routes, write-behind persistence, and the tick runner working on it.

Uses its own simulation id ("ws_test") so it never touches the live world.

Run inside the backend container:   python tests/test_world_state.py
"""

import copy
import json
import sys
import threading
import time

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

SIM = "ws_test"

import db
from core import world_state as ws
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def pg_row():
    with db._conn_lock, db.conn.cursor() as cur:
        cur.execute("SELECT data FROM world WHERE simulation_id=%s", (SIM,))
        r = cur.fetchone()
        return r[0] if r else None


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# start clean
with db._conn_lock, db.conn.cursor() as cur:
    cur.execute("DELETE FROM world WHERE simulation_id=%s", (SIM,))
ws.reset_for_tests()

# the first world goes straight to Postgres (init_db's path); no resident yet
seed = {"tick": 100, "characters": {}, "props": [], "marker": {"a": 1}}
db.save_world(SIM, seed)
check("a brand-new world is written straight to Postgres", pg_row() and pg_row()["marker"] == {"a": 1} and SIM not in ws._residents)

# ── resident identity ────────────────────────────────────────────────────────────
t0 = time.time()
with db.world_lock():
    w1 = db.load_world(SIM)
print(f"   cold load of the resident world took {time.time() - t0:.1f}s")
with db.world_lock():
    w2 = db.load_world(SIM)
    w2["marker"]["b"] = 2
check("inside the lock load_world is the resident world itself", w1 is w2 and ws.is_resident(SIM, w1))
with db.world_lock():
    check("in-place changes persist between locks without a save", db.load_world(SIM)["marker"] == {"a": 1, "b": 2})

# ── snapshots are private copies ──────────────────────────────────────────────────
snap = db.load_world(SIM)
check("outside the lock load_world is a copy", snap is not w1 and snap["marker"] == {"a": 1, "b": 2})
snap["marker"]["mutated"] = True
with db.world_lock():
    check("mutating a snapshot doesn't touch the live world", "mutated" not in db.load_world(SIM)["marker"])
check("snapshots carry the static map data and definitions", snap.get("world_tiles") and snap.get("definitions") and snap.get("outdoor_navigation"))
check("static data is shared, not copied, between snapshots", db.load_world(SIM)["world_tiles"] is snap["world_tiles"])

# one JSON rendering per tick, shared by readers
n0 = ws._stats["snapshots"]
for _ in range(5):
    db.load_world(SIM)
n1 = ws._stats["snapshots"]
check("readers within a tick share one rendering", n1 - n0 <= 1, str(n1 - n0))
with db.world_lock():
    db.load_world(SIM)["tick"] += 1
    ws.after_tick(SIM, db.load_world(SIM))
db.load_world(SIM); db.load_world(SIM)
check("a new tick (version) renders a new snapshot, once", ws._stats["snapshots"] - n1 == 1, str(ws._stats["snapshots"] - n1))

# ── save: in place and foreign ────────────────────────────────────────────────────────
with db.world_lock():
    w = db.load_world(SIM)
    w["marker"]["saved"] = 1
    db.save_world(SIM, w)
check("an in-place save is queued for Postgres", wait_for(lambda: (pg_row() or {}).get("marker", {}).get("saved") == 1))
foreign = copy.deepcopy(snap)
foreign["marker"] = {"replaced": True}
foreign["tick"] = 500
with db.world_lock():
    db.save_world(SIM, foreign)
    live = db.load_world(SIM)
    check("a foreign world replaces the resident contents (identity kept, static data kept)", live is w1 and live["marker"] == {"replaced": True} and live["tick"] == 500 and live.get("world_tiles"))
check("and reaches Postgres without the static map data", wait_for(lambda: (pg_row() or {}).get("tick") == 500) and "world_tiles" not in pg_row())

# ── the tick runner works on the resident world and persists write-behind ────────────────
import main
ws.PERSIST_EVERY_TICKS = 5
base_tick = ws._residents[SIM].world["tick"]
persisted_before = ws._stats["persists"]
for i in range(12):
    main._run_tick_and_persist(SIM)
w_after = ws._residents[SIM].world
check("the tick advanced the resident world in memory", w_after["tick"] == base_tick + 12)
check("ticks don't write to Postgres every tick (write-behind)", ws._stats["persists"] - persisted_before <= 12 // 5 + 1, str(ws._stats["persists"] - persisted_before))
check("…but it reaches Postgres at the interval", wait_for(lambda: (pg_row() or {}).get("tick", 0) >= base_tick + 10), str((pg_row() or {}).get("tick")))
check("a reader sees the latest tick", db.load_world(SIM)["tick"] == base_tick + 12)

# ── readers and the tick at the same time ────────────────────────────────────────────────
stop = threading.Event()
errs = []
reads = [0]


def reader():
    while not stop.is_set():
        try:
            s = db.load_world(SIM)
            assert "tick" in s and "characters" in s
            reads[0] += 1
        except Exception as e:
            errs.append(repr(e))
        time.sleep(0.005)


threads = [threading.Thread(target=reader) for _ in range(3)]
for t in threads:
    t.start()
for _ in range(40):
    main._run_tick_and_persist(SIM)
stop.set()
for t in threads:
    t.join()
check("3 reader threads and 40 ticks run together without errors", not errs and reads[0] >= 3, f"{reads[0]} reads, errors {errs[:2]}")

# ── a route-style writer between ticks ─────────────────────────────────────────────────────
with db.world_lock():
    w = db.load_world(SIM)
    w["marker"] = {"from_route": True}
    db.save_world(SIM, w)
main._run_tick_and_persist(SIM)
check("a route's change survives the next tick (nothing re-reads a stale copy)", ws._residents[SIM].world["marker"] == {"from_route": True})

# ── shutdown ───────────────────────────────────────────────────────────────────────────────────
ws._residents[SIM].world["marker"] = {"final": True}
ws.persist_now(SIM)
check("persist_now writes synchronously", (pg_row() or {}).get("marker") == {"final": True})
print("   stats:", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in ws.stats().items() if k != "residents"})

with db._conn_lock, db.conn.cursor() as cur:
    cur.execute("DELETE FROM world WHERE simulation_id=%s", (SIM,))
print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
