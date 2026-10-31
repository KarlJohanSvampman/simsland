"""
Fights and the police (systems/fights.py, systems/police_report.py): a fight carries what it was about and who was in it, the
offender is the one who started it and never phones the police on themselves, and when the police arrive they write a report and
take a statement from everyone involved.

Run inside the backend container:   python tests/test_fights_police.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from systems import emergency, fights, law, police_report
from systems import conflict_pipeline as cp
from systems.grievances import add_grievance

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, name, **extra):
    c = {"id": cid, "name": name, "age": 35, "age_group": "adult", "household_id": "h", "building_id": "home", "room_id": "kitchen",
         "x": 5, "y": 5, "traits": [], "relationships": {}, "memories": [], "legal": {"status": "free"}, "status": {"reputation": 0.0},
         "stress": 10, "money": 100, "alive": True}
    c.update(extra)
    return c


def make_world():
    w = {"tick": 1000, "calendar": {"year": 2026, "month": 10, "day": 30, "weekday": "Fri", "hour": 23, "minute": 24},
         "characters": {}, "households": {}, "environment": {"crime_solve_rate": 0.5}, "incidents": [], "calls": [], "responders": [],
         "buildings": [{"id": "home", "name": "the Haddad house", "rooms": [{"id": "kitchen", "name": "the kitchen"}]}]}
    for c in (person("k", "Karim"), person("l", "Lena"), person("n", "Noor", age=16, age_group="teen"), person("s", "Stranger", building_id="x", room_id="y", x=40, y=40)):
        w["characters"][c["id"]] = c
    return w


# ---- the topic -----------------------------------------------------------------------------------------------------------------------
check("a fight's topic reads in words", fights.topic_of(["loud_at_night", "left_mess"]) == "the noise at night and the mess left lying around")
check("... a one-off outburst has its own reason", fights.topic_of([], "gang_war") == "gang rivalry")
check("... and there is always something to say", "building" in fights.topic_of([]))

# ---- a conflict that turns physical -------------------------------------------------------------------------------------------------
w = make_world()
k, l = w["characters"]["k"], w["characters"]["l"]
add_grievance(k, "l", "loud_at_night", w, severity=20)
add_grievance(k, "l", "left_mess", w, severity=20)
conflict = cp.start_conflict("k", "l", w)
check("the conflict knows what it is about", conflict and "noise at night" in conflict["topic"], str(conflict and conflict.get("topic")))
conflict["phase"] = cp.PHASE_FIGHT
cp._handle_physical(conflict, k, l, w)
event_bus.flush(w)                       # the handlers run when the tick flushes the queue
inc = w["incidents"][0]
check("one incident, with an offender and a victim", len(w["incidents"]) == 1 and {inc["offender_id"], inc["victim_id"]} == {"k", "l"}, str(inc))
check("... the one who threw the first punch is the offender", inc["offender_id"] == conflict["aggressor"])
check("... and the incident says what it was about", "noise at night" in inc.get("topic", "") and inc["conflict_id"] == conflict["id"])
fight = w["fight_log"][0]
check("the fight is in the log with who, what about and how it ended",
      set(fight["parties"]) == {"k", "l"} and "noise at night" in fight["topic"] and fight["outcome"] == "physical_resolved" and fight["incident_id"] == inc["id"], str(fight))
check("... and the other adult and a teenager in the room were there, the stranger was not", fight["witnesses"] == ["n"], str(fight["witnesses"]))
texts = {c["id"]: [m["text"] for m in c["memories"] if m.get("conflict_outcome")] for c in (k, l)}
check("both remember who it was with and what about", all(any("noise at night" in t for t in texts[i]) for i in texts)
      and any("Lena" in t for t in texts["k"]) and any("Karim" in t for t in texts["l"]), str(texts))
check("... and that it turned physical", all(any("physical" in t for t in texts[i]) for i in texts))

# a suppressed one never got said; an agreement is no fight
w2 = make_world()
add_grievance(w2["characters"]["k"], "l", "lied", w2, severity=40)
c2 = cp.start_conflict("k", "l", w2)
cp._resolve(c2, "suppressed", w2)
event_bus.flush(w2)
check("a suppressed quarrel is not a fight in the log", not w2.get("fight_log"))
check("... the one who backed down remembers wanting to bring it up",
      any("backed down" in m["text"] and "a lie" in m["text"] for m in w2["characters"]["k"]["memories"]), str([m["text"] for m in w2["characters"]["k"]["memories"]]))
check("... the other only sensed tension and is not told the topic",
      any("Sensed" in m["text"] and "a lie" not in m["text"] for m in w2["characters"]["l"]["memories"]))

# ---- nobody phones the police on their own assault ---------------------------------------------------------------------------------
callers = {}
random.seed(3)
for i in range(300):
    wx = make_world()
    inc = emergency.report_assault_incident(wx, wx["characters"]["k"], wx["characters"]["l"], topic="the dishes")
    for _ in range(3):
        emergency.auto_report_incidents(wx)
    if inc.get("reported"):
        callers[inc["caller_id"]] = callers.get(inc["caller_id"], 0) + 1
check("the offender never calls it in", "k" not in callers and sum(callers.values()) > 50, str(callers))
check("... the victim and the people who were there do", callers.get("l", 0) > 0 and callers.get("n", 0) > 0, str(callers))
check("... a stranger across town does not", "s" not in callers)

wx = make_world()
inc = emergency.report_assault_incident(wx, wx["characters"]["k"], wx["characters"]["l"], topic="the dishes")
from systems import action_router
action_router._route_call_911(wx["characters"]["k"], wx, {"type": "call_911", "target_id": inc["id"]})
check("the offender's own call_911 does nothing", not inc.get("reported") and not wx["calls"])
action_router._route_call_911(wx["characters"]["l"], wx, {"type": "call_911", "target_id": inc["id"]})
check("the victim's does, and says who attacked whom", inc["reported"] and wx["calls"][0]["report"] == "Karim just attacked Lena.", str(wx["calls"]))

# ---- the police arrive ---------------------------------------------------------------------------------------------------------------
wx = make_world()
wx["characters"]["l"]["relationships"] = {"k": {"fear": 5, "friendship": 0}}
event_bus.emit("fight_physical", {"parties": ["k", "l"], "aggressor": "k", "topic": "the noise at night", "context": "impulsive_assault"})
event_bus.flush(wx)                      # a one-off outburst: no conflict behind it, so the incident logs the fight itself
inc = wx["incidents"][0]
check("an outburst with no conflict still logs the fight", wx["fight_log"][0]["context"] == "impulsive_assault" and inc["fight_id"] == wx["fight_log"][0]["id"])
emergency.create_911_call(wx, wx["characters"]["l"], "police", "Karim just attacked Lena.", incident_id=inc["id"])
inc["reported"] = True
inc["caller_id"] = "l"
emergency.dispatch(wx)
check("before they arrive there is no report and no arrest", not wx.get("police_reports") and not police_report.ensure_report(wx, inc))
law.maybe_arrest_from_incidents(wx)
check("... and the arrest waits for the police", not inc.get("arrest_checked"))
wx["tick"] += 20
emergency.resolve(wx)
rep = police_report.report_for(wx, inc)
check("on arrival the police file a report", rep and rep["incident_id"] == inc["id"] and rep["case_number"].startswith("2026-"), str(rep))
roles = {i["role"] for i in rep["interrogations"]}
check("... with the offender, the victim and the bystander interviewed", {"offender", "victim", "witness"} <= roles, str(roles))
check("... the offender and victim named by the report", rep["offender_id"] == "k" and rep["victim_id"] == "l" and "noise at night" in rep["summary"], rep["summary"])
check("... each person gave a statement",
      all(i["statement"] for i in rep["interrogations"]),
      str([(i["role"], i["statement"]) for i in rep["interrogations"]]))
check("everyone questioned remembers it", all(any(rep["case_number"] in m["text"] for m in wx["characters"][i["person_id"]]["memories"]) for i in rep["interrogations"]))
check("the fight in the log points to the report", wx["fight_log"][0]["police_report_id"] == rep["id"])
again = emergency.resolve(wx)
check("one report per incident", len(wx["police_reports"]) == 1)

# ---- the arrest and the station ------------------------------------------------------------------------------------------------------
law.send_offgrid = lambda *a, **k: True
arrested = held = 0
station_ok = True
random.seed(11)
for i in range(60):
    wy = make_world()
    wy["environment"]["crime_solve_rate"] = 0.5
    inc = emergency.report_assault_incident(wy, wy["characters"]["k"], wy["characters"]["l"], topic="the dishes")
    emergency.create_911_call(wy, wy["characters"]["l"], "police", "x", incident_id=inc["id"])
    inc["reported"], inc["caller_id"] = True, "l"
    emergency.dispatch(wy)
    wy["tick"] += 20
    emergency.resolve(wy)
    law.maybe_arrest_from_incidents(wy)
    rep = police_report.report_for(wy, inc)
    if wy["characters"]["k"]["legal"]["status"] != "free":
        arrested += 1
        station_ok &= rep["outcome"] == "arrested" and any(x["stage"] == "station" for x in rep["interrogations"])
        station_ok &= bool(wy["court_cases"] and wy["court_cases"][0].get("report_id") == rep["id"])
    else:
        held += 1
        station_ok &= rep["outcome"] == "no_charges" and any("No arrest" in f for f in rep["findings"])
check("some are arrested and some are not", arrested > 10 and held > 10, f"{arrested} arrested, {held} not")
check("... an arrest has the station interview and goes to trial with the report, a release says why", station_ok)

# evidence moves the odds
def odds(stances):
    n = 0
    for i in range(300):
        wz = make_world()
        wz["environment"]["crime_solve_rate"] = 0.5
        inc = emergency.report_assault_incident(wz, wz["characters"]["k"], wz["characters"]["l"], topic="x")
        inc["reported"] = True
        rep = {"id": "r", "incident_id": inc["id"], "offender_id": "k", "victim_id": "l", "evidence": stances, "interrogations": [], "findings": [],
               "outcome": "pending", "case_number": "1", "officer": "o"}
        wz["police_reports"] = [rep]
        inc["police_report_id"] = "r"
        law.maybe_arrest_from_incidents(wz)
        n += wz["characters"]["k"]["legal"]["status"] != "free"
    return n / 300


random.seed(5)
strong, weak = odds(0.45), odds(-0.4)
check("an admission and witnesses make an arrest likelier than a complainant who backs out", strong > weak + 0.4, f"{strong} vs {weak}")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
