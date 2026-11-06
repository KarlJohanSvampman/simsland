"""
Reduce Pressure: Bladder, Reduce Pressure: Bowels and Relieve Sexual Tension (brain/actionplans) on the real house world.

Bladder/bowels: at home -> the toilet; out in the open, far from home (or unable to wait) and nobody in view -> a bush;
someone could see -> back to the toilet. Bowels have their own intention type now (use_toilet_bowels), raised by
systems/body_intentions.py. Sexual tension: a partner who is here and willing first; otherwise alone somewhere private --
right where they are if that is private, else the nearer of their own bed and the bathroom (shower when they need a wash,
else the toilet); a child never gets past the first gate.

Run inside the backend container:   python tests/test_pressure_and_tension.py
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
from systems.schema_defaults import ensure_world_defaults
from brain.actionplans import store, checker, runner
from brain.actionplans import resolvers as R
from core.definitions import load_definitions

data = store.load()
errors = [p for p in checker.check(data, load_definitions("default")) if p["level"] == "error"]
check("the behaviour definitions pass the path checker", not errors, str(errors[:3]))
intents = store.by_id(data, "intentions")
check("bladder, bowels and sexual tension are live intentions of their own",
      intents["reduce_pressure_bladder"]["status"] == intents["reduce_pressure_bowels"]["status"]
      == intents["relieve_sexual_tension"]["status"] == "live"
      and runner.live_intention_for({}, "use_toilet")["id"] == "reduce_pressure_bladder"
      and runner.live_intention_for({}, "use_toilet_bowels")["id"] == "reduce_pressure_bowels"
      and runner.live_intention_for({}, "seek_sexual_release")["id"] == "relieve_sexual_tension")


def world():
    w = make_world()
    w["tick"] = 20000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": 14, "minute": 0, "second": 0,
                     "minute_of_day": 14 * 60, "weekday": "Monday"}
    ensure_world_defaults(w)
    for c in w["characters"].values():
        c.setdefault("body", {}).update(bladder=10, bowels=10, hygiene=80)
        c["activity"] = None
        c["traits"] = ["impulsive"]
        c["age"], c["age_group"] = 35, "adult"
    return w


def steps(c, iid):
    att = (c.get("plan_attempts") or {}).get(iid) or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


PEE = {"type": "use_toilet", "category": "survival", "priority": 80, "reason": "bladder_full"}
POO = {"type": "use_toilet_bowels", "category": "survival", "priority": 95, "reason": "bowels_urgent"}
SEX = {"type": "seek_sexual_release", "category": "private", "priority": 60, "reason": "feeling horny"}

# ---- bladder at home: the toilet ------------------------------------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
j["body"]["bladder"] = 80
res = runner.autopilot(j, w, PEE)
check("bladder full at home: the outdoors plan falls back, the toilet visit starts",
      res == "started" and j["activity"]["type"] == "use_toilet"
      and ("relieve_outdoors_bladder", "out", "gate", "no") in steps(j, "reduce_pressure_bladder"),
      f"{res} {j.get('activity')} {steps(j, 'reduce_pressure_bladder')}")
j["body"]["bladder"] = 5
j["activity"] = None
runner.on_activity_end({"character_id": "joseph", "activity_type": "use_toilet"}, w, "done")
check("... and when it ends with the bladder empty: satisfied", j["plan_log"][-1]["status"] == "satisfied", str(j["plan_log"][-1]))

# ---- bladder far out in the open, nobody around: a bush ------------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
j.update(x=50, y=80, building_id=None)
j["body"]["bladder"] = 80
check("out in the open, 75 tiles from home, nobody in view", R.RESOLVERS["is_outdoors"](j, w)
      and R.RESOLVERS["nobody_in_view"](j, w) and R.distance_home(j, w) >= 40)
res = runner.autopilot(j, w, PEE)
check("... too far to go home: behind a bush", res == "started" and j["activity"]["type"] == "relieve_outdoors"
      and ("relieve_outdoors_bladder", "far", "decision", "too far") in steps(j, "reduce_pressure_bladder"),
      f"{res} {j.get('activity')} {steps(j, 'reduce_pressure_bladder')}")
from systems.activities import complete_activity
complete_activity(j, w, j["activity"])
check("... which empties the bladder", j["body"]["bladder"] < 10, str(j["body"]))

# ---- the same, but someone is standing right there: not here -- the toilet --------------------------------------------
w = world()
j, s = w["characters"]["joseph"], w["characters"]["susan"]
j.update(x=50, y=80, building_id=None)
s.update(x=53, y=80, building_id=None)
j["body"]["bladder"] = 80
res = runner.autopilot(j, w, PEE)
tr = steps(j, "reduce_pressure_bladder")
check("someone could see: no bush, they head for the toilet instead",
      ("relieve_outdoors_bladder", "seen", "gate", "no") in tr and res == "started" and j["activity"]["type"] == "use_toilet",
      f"{res} {j.get('activity')} {tr}")

# ---- just outside the front door and it can wait: the toilet --------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
j.update(x=35, y=16, building_id=None)
j["body"]["bladder"] = 75
res = runner.autopilot(j, w, PEE)
tr = steps(j, "reduce_pressure_bladder")
check("outdoors near home, not urgent: it can wait, the toilet",
      ("relieve_outdoors_bladder", "far", "decision", "can wait") in tr and j["activity"]["type"] == "use_toilet", str(tr))

# ---- bowels: raised as their own type; at home the toilet, far out and urgent a bush ---------------------------------
w = world()
j = w["characters"]["joseph"]
j["body"]["bowels"] = 90
from systems.body_intentions import generate_body_intentions
generate_body_intentions(j, w)
check("bowels over 80 raise a use_toilet_bowels intention (not the bladder's use_toilet)",
      any(i.get("type") == "use_toilet_bowels" for i in j.get("active_intentions") or []), str(j.get("active_intentions")))
res = runner.autopilot(j, w, POO)
check("... at home: the bowels toilet visit", res == "started" and j["activity"]["type"] == "use_toilet_bowels",
      f"{res} {j.get('activity')} {steps(j, 'reduce_pressure_bowels')}")
j["activity"] = None
j["body"]["bowels"] = 30
runner.on_activity_end({"character_id": "joseph", "activity_type": "use_toilet_bowels"}, w, "done")
check("... down to 30 afterwards counts as met", j["plan_log"][-1]["status"] == "satisfied", str(j["plan_log"][-1]))
w = world()
j = w["characters"]["joseph"]
j.update(x=50, y=80, building_id=None)
j["body"]["bowels"] = 97
res = runner.autopilot(j, w, POO)
check("bowels at 97 far out in the open: can't wait, a bush", res == "started" and j["activity"]["type"] == "relieve_outdoors_bowels"
      and ("relieve_outdoors_bowels", "far", "decision", "can't wait") in steps(j, "reduce_pressure_bowels"),
      str(steps(j, "reduce_pressure_bowels")))
h0 = j["body"]["hygiene"]
complete_activity(j, w, j["activity"])
check("... the bowels go down and they feel less clean", j["body"]["bowels"] < 50 and j["body"]["hygiene"] < h0, str(j["body"]))

# ---- sexual tension ------------------------------------------------------------------------------------------------


def horny(c):
    c["libido_state"] = {"baseline": 0.4, "current": 0.8, "spike_until_tick": 10 ** 9, "denied_count": 0,
                         "last_release_tick": None, "_last_roll_day": "2026-11-02"}


check("the drive reads today's libido while it spikes, nothing otherwise",
      runner.drive_level({"libido_state": {"current": 0.8, "spike_until_tick": 5}}, {}, {"source": "libido.tension"}) == 80
      and runner.drive_level({"libido_state": {"current": 0.8}}, {}, {"source": "libido.tension"}) == 0)

# a partner at home, willing
w = world()
k, rob = w["characters"]["kathleen"], w["characters"]["robert"]
horny(rob)
rob["relationships"] = {"kathleen": {"labels": ["spouse"]}}
import systems.sexual_release as sr
real_try = sr._try_partner


def willing(c, world_):
    from systems.libido import note_released
    note_released(c, world_)
    return True


sr._try_partner = willing
res = runner.autopilot(rob, w, SEX)
sr._try_partner = real_try
check("partner here and willing: asked, and the tension is gone -- satisfied",
      ("with_partner", "ask", "action", "done") in steps(rob, "relieve_sexual_tension")
      and rob["plan_log"][-1]["status"] == "satisfied", str(steps(rob, "relieve_sexual_tension")))

# nobody: in the dining room -> the nearer private place, their bed
w = world()
j = w["characters"]["joseph"]
horny(j)
j["relationships"] = {}
res = runner.autopilot(j, w, SEX)
tr = steps(j, "relieve_sexual_tension")
from systems.room_assignment import room_at
bed = next((p for p in w["props"] if p["id"] == (j.get("activity") or {}).get("target_id")), {})
check("no partner, nobody from before, in the dining room: the bed is nearer -- to their own bed",
      ("masturbate_privately", "where", "decision", "bed is closer") in tr and j["activity"]["type"] == "masturbate_in_bed"
      and bed.get("building_id") == "starter_house_1" and "bedroom" in str(room_at(w, bed.get("x", 0), bed.get("y", 0))),
      f"{j.get('activity')} {bed.get('building_id')} {tr}")

# someone in the bedroom: the bathroom, the toilet
w = world()
j, k = w["characters"]["joseph"], w["characters"]["kathleen"]
horny(j)
j["relationships"] = {}
k.update(x=40, y=10, building_id="starter_house_1")
res = runner.autopilot(j, w, SEX)
tr = steps(j, "relieve_sexual_tension")
check("someone in the bedroom: off to the bathroom, the toilet",
      ("masturbate_privately", "bed", "gate", "no") in tr and res == "started"
      and j["activity"]["type"] == "masturbate_on_toilet", f"{res} {j.get('activity')} {tr}")
j["activity"] = None
complete_activity_type = "masturbate_on_toilet"
from systems import activities as A
j["activity"] = {"type": complete_activity_type, "phase": "using", "phase_started_tick": w["tick"], "duration": 1, "state": {}}
A.complete_activity(j, w, j["activity"])
check("... and finishing it releases the tension", not j["libido_state"].get("spike_until_tick"), str(j["libido_state"]))

# needs a wash: the shower
w = world()
j, k = w["characters"]["joseph"], w["characters"]["kathleen"]
k.update(x=40, y=10, building_id="starter_house_1")
horny(j)
j["relationships"] = {}
j["body"]["hygiene"] = 20
runner.autopilot(j, w, SEX)
check("feeling dirty as well: the shower", (j.get("activity") or {}).get("type") == "masturbate_in_shower",
      str(steps(j, "relieve_sexual_tension")))

# already alone in their own bedroom: right there
w = world()
j = w["characters"]["joseph"]
horny(j)
j["relationships"] = {}
j.update(x=40, y=10)
from systems.room_assignment import room_at
check("(standing in the bedroom)", str(room_at(w, 40, 10)).endswith("bedroom_5"), str(room_at(w, 40, 10)))
runner.autopilot(j, w, SEX)
check("alone in their own bedroom: right where they are", (j.get("activity") or {}).get("type") == "masturbate_private",
      str(steps(j, "relieve_sexual_tension")))

# someone else in the bathroom and the bedroom: nowhere private -> blocked, says why
w = world()
j, s, k = w["characters"]["joseph"], w["characters"]["susan"], w["characters"]["kathleen"]
horny(j)
j["relationships"] = {}
s.update(x=40, y=7, building_id="starter_house_1")
k.update(x=40, y=10, building_id="starter_house_1")
check("(susan in the restroom, kathleen in the bedroom)", str(room_at(w, 40, 7)).endswith("restroom_2"), str(room_at(w, 40, 7)))
runner.autopilot(j, w, SEX)
log = (j.get("plan_log") or [{}])[-1]
check("nowhere private: blocked, 'nowhere private'", log.get("status") == "blocked" and "private" in str(log.get("why")),
      str(log.get("why")) + " " + str(steps(j, "relieve_sexual_tension")))

# a child: never
w = world()
k = w["characters"]["kathleen"]
k.update(age=10, age_group="child")
horny(k)
runner.autopilot(k, w, SEX)
log = (k.get("plan_log") or [{}])[-1]
check("a child never gets past the first gate", log.get("status") == "blocked" and not k.get("activity"), str(log))
from systems.activities import start_activity
check("... and the activity itself refuses anyone under 18", start_activity(k, w, "masturbate_private") is False)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
