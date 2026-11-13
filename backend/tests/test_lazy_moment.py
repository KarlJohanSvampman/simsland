"""
The "body moment" values used to be stepped for every character every second (a PROCESS job): anger pressure,
intoxication, a baby's needs, blushes, arousal. They are lazy values of sim time now (core/lazy.py), brought up to date
in the character's own update or on a timer at the threshold that matters -- with the same per-tick rates.

Checked here: the result does not depend on how often they are brought up to date; the old stop rules hold (anger
only cools down to just under 0.05); thresholds are met on time (a baby starts crying, someone sobers up) by their
timers; a write brings the value up to date first.

Run inside the backend container:   python tests/test_lazy_moment.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import scheduler
from core.lazy import time_until_below


def W(ts):
    return {"sim_time": float(ts), "tick": int(ts), "calendar": {"hour": 12, "minute": 0}, "characters": {}}


# ── core/lazy ────────────────────────────────────────────────────────────────────────────────────────────────────────
check("time_until_below: one part", abs(time_until_below([(0.5, 0.01)], 0.3) - 20) < 1e-3)
check("... two parts, one running out first", abs(time_until_below([(0.1, 0.01), (0.5, 0.001)], 0.3) - 200) < 1e-3,
      time_until_below([(0.1, 0.01), (0.5, 0.001)], 0.3))
check("... already under: None", time_until_below([(0.1, 0.01)], 0.3) is None)

# ── anger ────────────────────────────────────────────────────────────────────────────────────────────────────────────
from systems.impulse import sync_anger, ANGER_DECAY_PER_TICK, add_anger_pressure, tick_impulse_for

def angry(p=0.4):
    return {"id": "a", "traits": [], "impulse_state": {"anger_pressure": p, "self_control": 0.9, "last_outburst_tick": 0}}

c1, c2, w1, w2 = angry(), angry(), W(0), W(0)
sync_anger(c1, w1); sync_anger(c2, w2)
for t in range(1, 1001):
    w1["sim_time"] = w1["tick"] = t
    sync_anger(c1, w1)
w2["sim_time"] = w2["tick"] = 1000
sync_anger(c2, w2)
a1, a2 = c1["impulse_state"]["anger_pressure"], c2["impulse_state"]["anger_pressure"]
check("anger cools the same however often it is brought up to date", abs(a1 - a2) < 1e-4 and abs(a1 - (0.4 - 1000 * ANGER_DECAY_PER_TICK)) < 1e-4, (a1, a2))
c, w = angry(0.06), W(0)
sync_anger(c, w)
w["sim_time"] = w["tick"] = 10 ** 6
sync_anger(c, w)
p = c["impulse_state"]["anger_pressure"]
check("... and stops just under 0.05, as the per-tick decay did", 0.05 - ANGER_DECAY_PER_TICK - 1e-9 <= p < 0.05, p)
c, w = angry(0.4), W(0)
c["off_grid"] = True
sync_anger(c, w)
w["sim_time"] = w["tick"] = 5000
sync_anger(c, w)
check("... not while they are away", c["impulse_state"]["anger_pressure"] == 0.4)
c, w = angry(0.5), W(100)
add_anger_pressure(c, 0.2, "test", w)
check("a bump wakes the character so a boilover is checked at once", (c.get("_wake") or {}).get("at") == 100.0, c.get("_wake"))

# ── intoxication ─────────────────────────────────────────────────────────────────────────────────────────────────────
import systems.harassment as H

w = W(0)
c = {"id": "d", "age": 30, "alive": True, "posture": "standing"}
w["characters"]["d"] = c
H.consume_alcohol(c, 10, w)                         # 0.8
lvl = c["intoxication_state"]["alcohol_level"]
timer = [t for t in w.get("timers", []) if t["owner"] == "intox:d"]
expect = (lvl - H.INTOX_INCAPACITATED_THRESHOLD) / H.ALCOHOL_DECAY_PER_TICK if lvl >= H.INTOX_INCAPACITATED_THRESHOLD else \
    (lvl - H.INTOX_CRAWL_THRESHOLD) / H.ALCOHOL_DECAY_PER_TICK if lvl >= H.INTOX_CRAWL_THRESHOLD else \
    (lvl - H.INTOX_POSTURE_THRESHOLD) / H.ALCOHOL_DECAY_PER_TICK
check("drinking sets a timer for the next sobering point", timer and abs(timer[0]["due"] - expect) < 1, (timer, expect))
w["sim_time"] = w["tick"] = 300
H.sync_intoxication(c, w)
check("alcohol wears off at the old per-tick rate", abs(c["intoxication_state"]["alcohol_level"] - (lvl - 300 * H.ALCOHOL_DECAY_PER_TICK)) < 1e-9)
before = c["intoxication_state"]["alcohol_level"]
w["sim_time"] = w["tick"] = 400
H.consume_alcohol(c, 1, w)
check("a drink brings it up to date before adding",
      abs(c["intoxication_state"]["alcohol_level"] - (before - 100 * H.ALCOHOL_DECAY_PER_TICK + 0.08)) < 1e-9)

# ── baby ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
import systems.baby as B

w = W(0)
baby = {"id": "b", "age": 0, "development_stage": "infant", "baby_needs": {"hunger": 0.8, "sleep": 0.8, "comfort": 0.8, "stimulation": 0.8}}
w["characters"]["b"] = baby
B._notify_nearby_parents = lambda c, world: None
B.sync_baby_needs(baby, w)
due = [t["due"] for t in w.get("timers", []) if t["owner"] == "babyneeds:b"]
rate = max(getattr(B, r) for _, r in B._NEED_RATES)
check("a baby's next crying point has a timer", due and abs(due[0] - (0.8 - B.CRY_THRESHOLD) / rate) < 1, due)
w["sim_time"] = w["tick"] = int(due[0]) + 1
B._on_baby_timer(w, {"owner": "babyneeds:b"})
check("... and they cry when it comes", baby.get("is_crying") is True, baby.get("baby_needs"))

# ── blush / arousal ──────────────────────────────────────────────────────────────────────────────────────────────────
import systems.crushes as C

w = W(0)
c = {"id": "k", "blush_score": 0.9, "is_blushing": True}
C.sync_blush(c, w)
C._arm_crush_wakes(c, w)
check("a blush sets a wake for when it stops showing",
      abs(c["_wake"]["at"] - (0.9 - C.BLUSH_THRESHOLD) / C.BLUSH_DECAY_PER_TICK) < 1, c["_wake"])
w["sim_time"] = w["tick"] = 300
C.sync_blush(c, w)
check("... and fades at the old rate", abs(c["blush_score"] - (0.9 - 300 * C.BLUSH_DECAY_PER_TICK)) < 1e-9 and c["is_blushing"] is False)

import systems.intimacy as I

w = W(0)
c = {"id": "r", "relationships": {"x": {"arousal_level": 0.5}, "y": {"arousal_level": 0.0}}}
I.sync_arousal(c, w)
w["sim_time"] = w["tick"] = 1000
I.sync_arousal(c, w)
check("arousal fades on every relationship at the old rate",
      abs(c["relationships"]["x"]["arousal_level"] - (0.5 - 1000 * I.AROUSAL_DECAY)) < 1e-9
      and c["relationships"]["y"]["arousal_level"] == 0.0)

# ── batteries ────────────────────────────────────────────────────────────────────────────────────────────────────────
import systems.power as P
import systems.personal_items as PI

phone = {"id": "ph", "object_type": "phone", "states": {"battery": 50.0, "powered_on": True}}
charger = {"id": "ch", "template": "phone_charger", "charges_per_tick": 0.8}
PI.get_inventory = lambda c: c.get("_inv", [])
PI.get_item_by_id = lambda c, i: next((x for x in c.get("_inv", []) if x["id"] == i), None)
P.find_charger_for = lambda c, d: charger
w = W(0)
c = {"id": "p", "_inv": [phone], "activity": None}
P.sync_batteries(c, w)
due = [t["due"] for t in w.get("timers", []) if t["owner"] == "battery:p"]
check("an idle phone's switching-off point has a timer", due and abs(due[0] - 50.0 / P.DEFAULT_IDLE_DRAIN) < 1, due)
c["activity"] = {"interaction": "phone_call"}            # on the phone from tick 100 (their update notes it)
w["sim_time"] = w["tick"] = 100
P.sync_batteries(c, w)
check("idle drain up to the change of regime", abs(phone["states"]["battery"] - (50 - 100 * P.DEFAULT_IDLE_DRAIN)) < 1e-6)
w["sim_time"] = w["tick"] = 200
P.sync_batteries(c, w)
check("... in-use drain after it", abs(phone["states"]["battery"] - (45 - 100 * P.DEFAULT_IN_USE_DRAIN)) < 1e-6, phone["states"])
c["activity"] = {"interaction": "charge", "device_item_id": "ph"}
P.sync_batteries(c, w)
w["sim_time"] = w["tick"] = 250
P.sync_batteries(c, w)
check("charging at the charger's rate", abs(phone["states"]["battery"] - (15 + 50 * 0.8)) < 1e-6, phone["states"])
due = [t["due"] for t in w.get("timers", []) if t["owner"] == "battery:p"]
check("... with a timer for when it is full", due and abs(due[0] - (250 + (100 - 55) / 0.8)) < 1, due)
c["activity"] = None
P.sync_batteries(c, w)
w["sim_time"] = w["tick"] = 250 + int(55 / P.DEFAULT_IDLE_DRAIN) + 5
P._on_battery_timer({**w, "characters": {"p": c}}, {"owner": "battery:p"})
check("an empty phone switches off", phone["states"]["battery"] == 0 and phone["states"]["powered_on"] is False, phone["states"])

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
