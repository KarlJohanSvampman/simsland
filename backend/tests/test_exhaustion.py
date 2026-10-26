"""
Being worn out by day with a responsibility open (systems/exhaustion.py): no sleep, strain instead (angrier, more stressed, more
mistakes, fewer details), and the way out -- someone offers to take over, they snap, then give in and sleep.

Run inside the backend container:   python tests/test_exhaustion.py
(the last section runs the seeded simulation, see tests/determinism.py)
"""

import os
import random
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from brain import intentions as it
from systems import exhaustion as ex
from systems.body_intentions import generate_body_intentions

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def world(hour=12, tick=100000):
    return {"tick": tick, "calendar": {"hour": hour, "minute": 0, "weekday": "Tuesday"}, "characters": {}, "households": {"hh": {"id": "hh", "members": []}},
            "definitions": {}}


def person(cid, name, age=36, fatigue=90, **extra):
    d = {"id": cid, "name": name, "age": age, "household_id": "hh", "building_id": "b1", "traits": [], "memories": [], "relationships": {},
         "active_intentions": [], "alive": True, "stress": 10, "x": 1, "y": 1,
         "body": {"fatigue": fatigue, "hunger": 10, "hydration": 90, "bladder": 10, "bowels": 10, "sleep_debt": 0, "hours_awake": 20, "energy": 30}}
    d.update(extra)
    return d


def home(hour=12, fatigue=90):
    w = world(hour)
    mum, dad = person("mum", "Anna Lindqvist", fatigue=fatigue), person("dad", "Erik Lindqvist", fatigue=20)
    kid = person("kid", "Oskar Lindqvist", 6, fatigue=10, age_group="child", _awaiting_caregiver={"need": "hunger"})
    w["characters"] = {c["id"]: c for c in (mum, dad, kid)}
    w["households"]["hh"]["members"] = ["mum", "dad", "kid"]
    it.add_intention(mum, {"type": "feed_child_kid", "category": "health", "priority": 85, "reason": "Oskar is hungry", "child_id": "kid"})
    return w, mum, dad, kid


def sleeping_intentions(c):
    return [i for i in c["active_intentions"] if i["type"] in ("sleep", "take_nap")]


# ---- strain -----------------------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home()
check("no strain below the threshold", ex.strain(person("x", "X", fatigue=60), w) == 0)
check("full strain at the end of their tether", ex.strain(person("x", "X", fatigue=100), w) == 1.0)
check("in between", abs(ex.strain(person("x", "X", fatigue=82.5), w) - 0.5) < 1e-9)
check("not at night (they go to bed)", ex.strain(person("x", "X", fatigue=100), world(2)) == 0)
check("not a child, not asleep, not away", ex.strain(person("x", "X", 8, fatigue=100), w) == 0 and ex.strain(person("x", "X", fatigue=100, activity={"type": "sleep"}), w) == 0
      and ex.strain(person("x", "X", fatigue=100, off_grid=True), w) == 0)
check("mistakes are up to three times as likely, attention down to half", ex.mistake_multiplier(person("x", "X", fatigue=100), w) == 3.0 and ex.attention_factor(person("x", "X", fatigue=100), w) == 0.5
      and ex.mistake_multiplier(person("x", "X", fatigue=10), w) == 1.0)

# ---- no sleep while a responsibility is open --------------------------------------------------------------------------------------------
check("an adult with a hungry child to feed is blocked from daytime sleep", ex.blocks_daytime_sleep(mum, w))
generate_body_intentions(mum, w)
check("so exhaustion does not send them to sleep or to nap", not sleeping_intentions(mum), str(sleeping_intentions(mum)))
check("and the duty is still there", any(i["type"] == "feed_child_kid" for i in mum["active_intentions"]))
w, mum, dad, kid = home()
mum["active_intentions"] = []
generate_body_intentions(mum, w)
check("without a duty, ordinary fatigue still puts them down for a nap or sleep", bool(sleeping_intentions(mum)), str(mum["active_intentions"]))
w, mum, dad, kid = home(hour=2)
generate_body_intentions(mum, w)
check("at night they sleep as usual, duty or not", bool(sleeping_intentions(mum)))
w, mum, dad, kid = home()
mum["_rest_accepted_until"] = w["tick"] + 3600
generate_body_intentions(mum, w)
sl = sleeping_intentions(mum)
check("once they have agreed to rest, they go to bed", sl and sl[0]["reason"] == "rest_accepted" and not ex.blocks_daytime_sleep(mum, w), str(sl))
w, mum, dad, kid = home()
mum["age"] = 9
check("a child is not held back (children nap)", not ex.blocks_daytime_sleep(mum, w))

# ---- what strain does ---------------------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home(fatigue=100)
stress0 = mum["stress"]
with mock.patch.object(ex, "_maybe_slip", lambda *a, **k: None), mock.patch.object(ex.random, "random", return_value=0.99):
    ex.tick_exhaustion(w)
check("stress builds", mum["stress"] > stress0)
check("anger pressure builds", mum["impulse_state"]["anger_pressure"] > 0)
check("they turn angry", mum["emotion"] == "angry", str(mum.get("emotion")))
check("the rested are untouched", dad["stress"] == 10 and "impulse_state" not in dad)
slips = []
w, mum, dad, kid = home(fatigue=100)
with mock.patch.object(ex.random, "random", side_effect=[0.0] + [0.99] * 20):
    ex.tick_exhaustion(w)
check("and slips happen: a mistake is noted and frays them further", any("too tired" in m["text"] for m in mum["memories"]) and mum["stress"] > 10 + 1.5, str([m["text"] for m in mum["memories"]]))
lines = ex.context_lines(mum, w)
check("the prompt says so, and why they cannot lie down", lines and "worn out" in lines[0] and "a child still needs you" in lines[0], str(lines))
check("a rested character has no such line", ex.context_lines(dad, w) is None)

# ---- someone offers to take over -------------------------------------------------------------------------------------------------------------
said = []
w, mum, dad, kid = home(fatigue=95)
dad["relationships"] = {}
with mock.patch.object(ex, "_say", lambda c, world, text, target=None, act="remark", intent=None: said.append((c["id"], act, text))), \
        mock.patch.object(ex, "_maybe_slip", lambda *a, **k: None), mock.patch.object(ex.random, "random", return_value=0.0), \
        mock.patch.object(ex.random, "randint", return_value=600):
    ex.tick_exhaustion(w)
offer = mum.get("_rest_offer")
check("a helper in the house offers to take the responsibility over", offer and offer["by"] == "dad" and offer["count"] == 1, str(offer))
check("the helper offers, the worn-out one snaps back", [(s[0], s[1]) for s in said] == [("dad", "offer"), ("mum", "retort")], str(said))
check("being told to calm down does not calm them", mum["impulse_state"]["anger_pressure"] > 0.05)
check("nothing is handed over yet, and still no sleep", any(i["type"] == "feed_child_kid" for i in mum["active_intentions"]) and not rest_ok(mum, w) if (rest_ok := ex.rest_accepted) else False)
w["tick"] += 600
with mock.patch.object(ex, "_say", lambda *a, **k: None), mock.patch.object(ex.random, "random", return_value=0.5):      # 0.5 < 0.65: gives in
    ex.tick_exhaustion(w)
check("minutes later they give in: the duty moves to the helper", not any(i["type"] == "feed_child_kid" for i in mum["active_intentions"])
      and any(i["type"] == "feed_child_kid" and i.get("child_id") == "kid" for i in dad["active_intentions"]))
check("and they are free to sleep", ex.rest_accepted(mum, w) and not ex.blocks_daytime_sleep(mum, w))
check("both remember it", any("took over" in m["text"] for m in mum["memories"]) and any("took over" in m["text"] for m in dad["memories"]))
generate_body_intentions(mum, w)
check("and they go to bed", any(i["type"] == "sleep" for i in mum["active_intentions"]))
check("the offer is closed", "_rest_offer" not in mum)

# a refusal, then the next offer is accepted
w, mum, dad, kid = home(fatigue=95)
with mock.patch.object(ex, "_say", lambda *a, **k: None), mock.patch.object(ex, "_maybe_slip", lambda *a, **k: None), \
        mock.patch.object(ex.random, "random", return_value=0.0), mock.patch.object(ex.random, "randint", return_value=600):
    ex.tick_exhaustion(w)
w["tick"] += 600
with mock.patch.object(ex, "_say", lambda *a, **k: None), mock.patch.object(ex, "_maybe_slip", lambda *a, **k: None), mock.patch.object(ex.random, "random", return_value=0.9):
    ex.tick_exhaustion(w)
check("they can refuse: the duty stays with them, and the offer waits a while", any(i["type"] == "feed_child_kid" for i in mum["active_intentions"]) and not ex.rest_accepted(mum, w)
      and mum["_rest_refusals"] == 1 and mum["_rest_offer_cd"] > w["tick"])
w["tick"] += ex.OFFER_COOLDOWN + 1
with mock.patch.object(ex, "_say", lambda *a, **k: None), mock.patch.object(ex, "_maybe_slip", lambda *a, **k: None), \
        mock.patch.object(ex.random, "random", return_value=0.0), mock.patch.object(ex.random, "randint", return_value=600):
    ex.tick_exhaustion(w)
check("the next offer is a second one", mum["_rest_offer"]["count"] == 2)
w["tick"] += 600
with mock.patch.object(ex, "_say", lambda *a, **k: None), mock.patch.object(ex.random, "random", return_value=0.99):
    ex.tick_exhaustion(w)
check("and the second is always accepted", ex.rest_accepted(mum, w) and not ex.duties(mum))

# who may help
for label, change in (("asleep", lambda d: d.update(activity={"type": "sleep"})), ("away", lambda d: d.update(off_grid=True)),
                      ("in another building", lambda d: d.update(building_id="b2")), ("worn out too", lambda d: d["body"].update(fatigue=85)),
                      ("a child", lambda d: d.update(age=12))):
    w, mum, dad, kid = home(fatigue=95)
    change(dad)
    check(f"a helper who is {label} cannot offer", dad not in ex._helpers(mum, w))
w, mum, dad, kid = home(fatigue=95)
dad["household_id"] = "other"
stranger = person("s", "Sam", fatigue=10, household_id="hh")
w["characters"]["s"] = stranger
mum["relationships"] = {"dad": {"friendship": 5}, "s": {"friendship": 5}}
check("the household comes first", ex._helpers(mum, w)[0]["id"] == "s")

# ---- woken for a duty ---------------------------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home()
mum["activity"] = {"type": "sleep"}
check("a daytime sleeper whom a hungry child is waiting for is to be woken", ex.should_wake_for_duty(mum, w))
mum["_duty_wake_tick"] = w["tick"] - 60
check("not again at once", not ex.should_wake_for_duty(mum, w))
mum["_duty_wake_tick"] = None
kid["_awaiting_caregiver"] = None
check("not when the child has been seen to", not ex.should_wake_for_duty(mum, w))
kid["_awaiting_caregiver"] = {"need": "hunger"}
mum["_rest_accepted_until"] = w["tick"] + 100
check("nor when someone has taken it over", not ex.should_wake_for_duty(mum, w))
mum["_rest_accepted_until"] = 0
w["calendar"]["hour"] = 2
check("nor at night", not ex.should_wake_for_duty(mum, w))
w["calendar"]["hour"] = 12
kid["building_id"] = "b2"
check("nor when the child is somewhere else", not ex.should_wake_for_duty(mum, w))

# ---- mistakes at the stove ---------------------------------------------------------------------------------------------------------------------------
from systems import accidents
seen = []
w = world()
w["definitions"] = {"stage_primitives": {"chop": {"possible_accidents": [{"accident_template": "cut", "probability": 0.1}]}}, "accident_templates": {"cut": {"possible_injuries": []}}}
rested, tired = person("r", "R", fatigue=10), person("t", "T", fatigue=100)
for who in (rested, tired):
    with mock.patch.object(accidents, "weighted_pick", lambda opts: (seen.append(opts[0]["probability"]), None)[1]):
        accidents.maybe_trigger_cooking_accident(who, w, "chop")
check("a worn-out cook is three times as likely to have an accident", seen == [0.1, 0.30000000000000004], str(seen))

# ---- and days away are not a day's work ---------------------------------------------------------------------------------------------------------------
from systems import offgrid as og
w = world()
w.update(environment={}, events=[], offmap=[])
c = person("a", "A", fatigue=20, off_grid=True, off_grid_reason="temporary_separation", return_tick=w["tick"] - 1, _offgrid_departure_tick=w["tick"] - 3 * 86400)
w["characters"] = {"a": c}
with mock.patch("systems.events.maybe_generate_summary_linked_event", lambda *a, **k: None), mock.patch("systems.childcare_arrangement.maybe_return_dependents", lambda *a, **k: None), \
        mock.patch.object(og, "_private_story", lambda *a, **k: []), mock.patch.object(og, "handle_return_transport", lambda *a, **k: None):
    og.process_return(c, w)
check("three days at a relative's cost no fatigue (they used to come back at 100 and drop)", c["body"]["fatigue"] <= 20, str(c["body"]["fatigue"]))

# ---- in the simulation ------------------------------------------------------------------------------------------------------------------------------
from tests import determinism

picked = {}


def setup(w):
    adults = [c for c in w["characters"].values() if (c.get("age") or 0) >= 18 and not c.get("is_workplace_npc") and not c.get("is_service_worker")]
    kids = [c for c in w["characters"].values() if c.get("age_group") == "child" and not c.get("is_workplace_npc")]
    mum, dad, kid = adults[0], adults[1], kids[0]
    for p in (mum, dad):
        p["household_id"] = kid["household_id"]
        p["activity"] = None
        p["off_grid"] = False
        p["building_id"] = kid["building_id"] = "starter_house_1"
        p["room_id"] = kid["room_id"] = "starter_house_1:dining_room_1"
        p["x"], p["y"], kid["x"], kid["y"] = 10, 8, 11, 8
        p.pop("_body_lazy", None)
        p["body"].update({"hunger": 0, "hydration": 100, "energy": 100, "fatigue": 20, "bladder": 0, "bowels": 0, "hygiene": 100, "odor": 0,
                          "stomach_discomfort": 0, "mouth_hygiene": 100, "sleep_debt": 0, "hours_awake": 1})
        p["active_intentions"] = []
    mum["body"].update({"fatigue": 97, "hours_awake": 22, "energy": 20})
    kid["body"]["hunger"] = 95
    kid["_awaiting_caregiver"] = {"need": "hunger", "tick": w["tick"]}
    from brain.intentions import add_intention
    add_intention(mum, {"type": f"feed_child_{kid['id']}", "category": "health", "priority": 85, "reason": "hungry", "child_id": kid["id"]})
    picked.update(mum=mum["id"], dad=dad["id"], kid=kid["id"])


import brain.agent_loop as _al
_al.tick_curiosity = lambda c, w: None
_al.maybe_go_offgrid = lambda c, w: None
_al.maybe_schedule_doctor_visit = lambda c, w: None
w2, errs, _ = determinism.run_sim(2400, start="2026-11-04T12:00:00", setup=setup)
mum2 = w2["characters"][picked["mum"]]
print(f"   after 40 sim-minutes: mum stress {mum2['stress']:.0f}, emotion {mum2.get('emotion')}, rest accepted {mum2.get('_rest_accepted_until')}, activity {(mum2.get('activity') or {}).get('type')}, "
      f"errors {dict(errs)}")
check("the simulation ran without errors", not errs, str(determinism.ERROR_TRACES))
check("with the child seen to, nothing holds her back: she is free to sleep (she did)", (mum2.get("activity") or {}).get("type") in ("sleep", "nap", None))
check("the hungry child was fed", not w2["characters"][picked["kid"]].get("_awaiting_caregiver"))
check("and she was strained all the while", mum2["stress"] > 10)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
