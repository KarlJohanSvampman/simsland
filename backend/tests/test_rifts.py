"""
Falling out with someone you live with (systems/rifts.py): a bad fight no longer sends anyone off on the spot; it
opens a rift they try to resolve, daily -- giving in, an agreement, a deal, or a go-between -- and only after
MAX_ATTEMPTS tries or STAY_DAYS days do they consider leaving, for a purpose: time away to come back and make peace,
or moving out for good, which the household sees as they come back for their things.

Run inside the backend container:   python tests/test_rifts.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from core import scheduler
from systems import rifts


def setup():
    w = make_world()
    w["tick"] = 100000
    for cid, age in (("kathleen", 38), ("robert", 41), ("joseph", 40), ("susan", 11)):
        w["characters"][cid].update(age=age, traits=[], memories=[], relationships={}, grievances=[], activity=None,
                                    off_grid=False, route=[], is_moving=False, cognition={})
    k, r, j = (w["characters"][x] for x in ("kathleen", "robert", "joseph"))
    r["relationships"]["joseph"] = {"designation": "close_friend", "trust": 80, "friendship": 70}
    j["relationships"]["robert"] = {"trust": 70, "friendship": 60}
    j["relationships"]["kathleen"] = {"trust": 60, "friendship": 50}
    k["relationships"]["joseph"] = {"trust": 60, "friendship": 50}
    w["fight_log"] = []
    return w, k, r, j


def bad_fight(w, a, b, outcome="storm_off", topic="the dishes"):
    cid = f"conflict_{w['tick']}"
    w.setdefault("conflicts", {})[cid] = {"id": cid, "parties": [a["id"], b["id"]], "initiator": a["id"],
                                         "topic": topic, "issues": [], "outcome": outcome}
    w["fight_log"].append({"tick": w["tick"], "parties": [a["id"], b["id"]], "topic": topic, "outcome": outcome})
    rifts.on_conflict_resolved(w, {"conflict_id": cid, "outcome": outcome, "parties": [a["id"], b["id"]]})


def advance(w, ticks):
    w["tick"] += ticks
    scheduler.fire_due(w)


def mems(c, *words):
    return [m["text"] for m in c.get("memories", []) if all(x.lower() in m["text"].lower() for x in words)]


def settle_conflicts(w, outcome):
    """A reconciliation sit-down started by the rift: end it with `outcome`."""
    for conflict in list((w.get("conflicts") or {}).values()):
        if conflict.get("reconciliation") and conflict.get("outcome") is None:
            conflict["outcome"] = outcome
            rifts.on_conflict_resolved(w, {"conflict_id": conflict["id"], "outcome": outcome,
                                           "parties": conflict["parties"]})


# ---- a bad fight opens a rift, not a suitcase ----------------------------------------------------------------------
w, k, r, j = setup()
bad_fight(w, r, k)
check("a fight that ends with someone storming off: a rift for both, about what it was about",
      r["rifts"]["kathleen"]["status"] == "open" and k["rifts"]["robert"]["topics"] == ["the dishes"])
check("... nobody moves out on the spot", not r.get("temporary_residence") and not r.get("off_grid")
      and not k.get("temporary_residence") and not k.get("off_grid"))

# ---- trying, and getting nowhere -------------------------------------------------------------------------------------
rifts._receptive = lambda other, cid: -1.0              # nobody comes round in this part
rifts.LEAVE_CHANCE = 0.0                                 # ... and nobody leaves yet
advance(w, rifts.FIRST_TRY_TICKS + 1)
settle_conflicts(w, "cold_shoulder")
check("a few hours later he recalls what led to it", mems(r, "things have been bad with kathleen", "the dishes"),
      str([m["text"] for m in r["memories"]][-4:]))
check("... and tries something: no understanding, one try down", r["rifts"]["kathleen"]["attempts"] >= 1,
      str(r["rifts"]["kathleen"]))
for _ in range(4):
    advance(w, rifts.DAY)
    settle_conflicts(w, "cold_shoulder")
tried = set(r["rifts"]["kathleen"]["tried"])
check("each day a different way forward: more than one kind tried", len(tried) >= 2, str(tried))
check("... a go-between among them, with Joseph hearing about it",
      "third_party" not in tried or mems(j, "asked me to talk to"), str(tried))

# ---- after three tries he considers leaving: time away, with a purpose ----------------------------------------------
rifts.LEAVE_CHANCE = 1.0
for _ in range(3):
    advance(w, rifts.DAY)
    settle_conflicts(w, "cold_shoulder")
    if (r.get("temporary_residence") or r.get("off_grid")):
        break
res = r.get("temporary_residence") or {}
check("three tries with nothing: he leaves for a while, to stay with his close friend Joseph",
      res.get("host_id") == "joseph" and res.get("purpose") == "time_away", str(res) + str(r["rifts"]["kathleen"]))
check("... and knows why he's going", mems(r, "leaving to get some distance from kathleen"),
      str([m["text"] for m in r["memories"]][-2:]))
check("... Kathleen notices he's gone", mems(k, "robert okafor has left for a while"))
check("... he heads for Joseph's house", (r.get("move_target") or {}).get("target_id") == "building:starter_house_1"
      or r.get("is_moving"), str(r.get("move_target")))

# ---- ... and comes back to make peace ------------------------------------------------------------------------------
advance(w, rifts.AWAY_DAYS[1] * rifts.DAY + 1)
check("after a few days he comes back home to try again", not r.get("temporary_residence")
      and r["rifts"]["kathleen"]["status"] == "open" and mems(r, "came back home to try to make peace"))
rifts._receptive = lambda other, cid: 1.0                # this time she comes round
advance(w, 1801)
settle_conflicts(w, "agreement")
check("... and this time they come to an understanding: the rift is closed for both",
      r["rifts"]["kathleen"]["status"] == "resolved" and k["rifts"]["robert"]["status"] == "resolved",
      str(r["rifts"]["kathleen"]))
check("... with standing back above the line", rifts.standing(r, "kathleen") >= rifts.STANDING_BAD
      and rifts.standing(k, "robert") >= rifts.STANDING_BAD)

# ---- beyond repair: moving out, and coming back for his things -----------------------------------------------------
w, k, r, j = setup()
rifts._receptive = lambda other, cid: -1.0
rifts.LEAVE_CHANCE = 1.0
bad_fight(w, r, k, outcome="physical_resolved", topic="money")
for _ in range(10):
    advance(w, rifts.DAY)
    settle_conflicts(w, "cold_shoulder")
    if r.get("temporary_residence"):
        break
res = r.get("temporary_residence") or {}
check("a fight that got physical and won't mend: he moves out", res.get("purpose") == "moving_out", str(res))
for _ in range(rifts.PICKUPS):
    advance(w, rifts.PICKUP_DAYS[1] * rifts.DAY + 1)
check("... coming back every few days for his things, which Kathleen sees", len(mems(k, "came by and took")) == rifts.PICKUPS,
      str(mems(k, "came by")))
check("... until the last of them: moved out", r["rifts"]["kathleen"]["status"] == "moved_out"
      and mems(k, "they've moved out"))

# ---- bad standing alone, and children ------------------------------------------------------------------------------
w, k, r, j = setup()
k["relationships"]["robert"] = {"resentment": 90, "hostility": 20}
rifts.scan(w)
check("standing sunk below the line, no fight needed: a rift", (k.get("rifts") or {}).get("robert", {}).get("status") == "open")
s = w["characters"]["susan"]
check("a child gets no rift (and never leaves)", rifts.open_rift(s, w, "kathleen") is None)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
