"""
API/gateway split, stage 2: the read replica (core/replication.py).

A seeded simulation runs as the core; every tick it publishes frames; a Feed in this same process
plays the gateway and applies them to its own copy of the world. The two must agree.

Uses its own stream/key names so a running core or gateway is never involved.

Run inside the backend container:   python tests/test_replication.py
(needs /tmp/backup_world.json, see tests/determinism.py)
"""

import copy
import os
import sys
import time

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from tests import determinism
from tests.determinism import norm, diff
import sim_loop
from systems.schema_defaults import ensure_world_defaults
from core import replication as rep
from core import world_state
from core.cache import r

failures = []
N_TICKS = int(os.getenv("REP_TICKS", "250"))


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


SIM = "rep_test"
ch = rep.Channel("test:rep")
for k in list(r.scan_iter(match="test:rep:*")):
    r.delete(k)
pub = rep.Publisher(ch)
pub.alive_cache_seconds = 0.0

import db
db._note_static_changed = lambda: None           # publisher and replica share this process; the map never changes here
determinism._install()
w = determinism.fixture("2026-11-01T09:00:00")
for c in w["characters"].values():
    c["off_grid"] = False


def tick():
    ensure_world_defaults(w)
    determinism._Clock.t += 1.0
    sim_loop.tick(w)
    dirty = sim_loop.collect_dirty(w)
    pub.publish(SIM, w, dirty)
    return dirty


def replica_world():
    return world_state.replica_entry(SIM).world


def synced(timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if feed.stats["last_tick"] == w["tick"] and feed.epoch is not None:
            return True
        time.sleep(0.02)
    return False


def agree():
    return diff(norm(w), norm(replica_world()))


# ---- nobody subscribed: the core pays nothing -----------------------------------------------
for _ in range(3):
    tick()
check("no subscriber, no frames", r.xlen(ch.stream) == 0 and pub.epoch is None)

# ---- a gateway connects -----------------------------------------------------------------------
feed = rep.Feed(SIM, ch)
feed.start()
deadline = time.time() + 90                      # the first bootstrap also rebuilds the map's lookup tables
while not feed.ready.is_set() and time.time() < deadline:
    tick()                                       # the core keeps ticking; the first publish starts the epoch
    time.sleep(0.05)
check("the replica bootstrapped from a snapshot", feed.ready.is_set(), str(feed.stats))
check("the epoch started on the first publish after the subscriber appeared", pub.epoch is not None)

for _ in range(5):
    tick()
check("the replica follows frames", synced(), f"{feed.stats} vs tick {w['tick']}")

# ---- a long run, compared at every full pass ---------------------------------------------------
mismatches = []
checks = 0
for i in range(N_TICKS):
    dirty = tick()
    if pub.last_full_tick == w["tick"]:
        if not synced():
            mismatches.append((w["tick"], "replica did not catch up"))
            continue
        d = agree()
        checks += 1
        if d:
            mismatches.append((w["tick"], d[:3]))
print(f"   {N_TICKS} ticks, {checks} full-pass comparisons, publisher: {pub.stats}")
check("the replica equals the core at every full pass", checks > N_TICKS // 20 and not mismatches, str(mismatches[:2]))

# between full passes the hot parts agree too: positions and activity of every character
for _ in range(7):
    tick()
synced()
bad = []
for cid, c in w["characters"].items():
    rc = replica_world()["characters"].get(cid)
    for k in ("x", "y", "activity", "posture", "health", "is_moving"):
        if rc is None or rc.get(k) != c.get(k):
            bad.append((cid, k))
check("hot character keys are current between full passes", not bad, str(bad[:3]))

# ---- frame sizes ---------------------------------------------------------------------------------
frames = pub.stats["frames"]
print(f"   mean frame {pub.stats['bytes'] / max(frames, 1):.0f} bytes, mean publish {pub.stats['ms'] / max(frames, 1):.2f} ms, snapshot {pub.stats.get('last_snapshot_bytes')} bytes")
check("publishing stays within a sane budget on the tick thread", pub.stats["ms"] / max(frames, 1) < 60, f"{pub.stats['ms'] / max(frames, 1):.1f} ms")

# ---- a route saved the world: everything is re-checked at once ------------------------------------
cid = next(iter(w["characters"]))
w["characters"][cid]["name"] = "Renamed By A Route"
w["households"] = w.get("households") or {}
w["environment"]["temperature"] = 3.5
pub.force_full()
tick()
check("a forced pass delivers unmarked changes immediately", synced() and replica_world()["characters"][cid]["name"] == "Renamed By A Route"
      and replica_world()["environment"]["temperature"] == 3.5)

# ---- read-your-writes: wait for the frame that carries a change -----------------------------------------
w["environment"]["temperature"] = 9.25
pub.force_full()
target = (pub.epoch, pub.seq + 1)
tick()
check("wait_applied returns once the frame is applied", feed.wait_applied(*target, timeout=10) and replica_world()["environment"]["temperature"] == 9.25)
check("wait_applied times out for a frame that never comes", not feed.wait_applied(pub.epoch, pub.seq + 100, timeout=0.3))
check("wait_applied gives up when the epoch is not the current one", not feed.wait_applied("some-other-epoch", 1, timeout=0.3))

# ---- characters come and go ---------------------------------------------------------------------------
newc = copy.deepcopy(w["characters"][cid])
newc["id"] = "newcomer"
newc["name"] = "Newcomer"
w["characters"]["newcomer"] = newc
tick()
check("a new character arrives whole", synced() and "newcomer" in replica_world()["characters"])
del w["characters"]["newcomer"]
tick()
check("a removed character is removed", synced() and "newcomer" not in replica_world()["characters"])

# ---- a key appears and disappears ------------------------------------------------------------------------
w["brand_new_key"] = {"a": 1}
pub.force_full()
tick()
check("a new top-level key is replicated", synced() and replica_world().get("brand_new_key") == {"a": 1})
del w["brand_new_key"]
pub.force_full()
tick()
check("a removed top-level key is removed", synced() and "brand_new_key" not in replica_world())

# ---- the dirty ids reach the gateway ------------------------------------------------------------------------
got = feed.take_dirty()
check("dirty character ids accumulate for websocket deltas", len(got["chars"]) > 0)
check("take_dirty clears them", not any(feed.take_dirty().values()))
view = rep.collect_dirty(replica_world(), {"chars": set(w["characters"])})
check("a dirty set can be turned into entities on the gateway", set(view["chars"]) == set(w["characters"]))

# ---- a gap in the sequence -> the replica re-bootstraps ---------------------------------------------------
resyncs = feed.stats["resyncs"]
pub.seq += 3                                     # three frames "lost on the wire"
for _ in range(5):
    tick()
    time.sleep(0.3)
check("a gap makes the replica bootstrap again", feed.stats["resyncs"] > resyncs, str(feed.stats))
pub.force_full()
tick()
check("and it converges again", synced() and not agree(), str(agree()[:3]))

# ---- the core restarts: a new epoch ------------------------------------------------------------------------------
resyncs = feed.stats["resyncs"]
pub._reset()
for _ in range(6):
    tick()
    time.sleep(0.2)
check("a new epoch makes the replica start over", feed.stats["resyncs"] > resyncs,
      f"{feed.stats} feed.epoch={feed.epoch} applied={feed.applied_seq} alive={feed._thread.is_alive()} pub.epoch={pub.epoch} seq={pub.seq} xlen={r.xlen(ch.stream)} subs={pub.subscribers_alive()}")
pub.force_full()
tick()
check("and it converges again after the restart", synced() and not agree(), str(agree()[:3]))

# ---- gateway disappears: the core goes back to paying nothing ------------------------------------------------
feed.stop()
time.sleep(0.2)
pub.forget_alive_cache()
frames_before = r.xlen(ch.stream)
tick()
check("with no subscriber left, publishing stops", r.xlen(ch.stream) == frames_before and pub.epoch is None)

for k in list(r.scan_iter(match="test:rep:*")):
    r.delete(k)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
