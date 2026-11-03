"""
Guests in someone else's home (systems/guests.py): who let them in, being asked to leave, going -- or not, and what
happens then -- and the ordinary limits on a visit.

Live (2026-11-02): characters stayed on in other families' homes while the people living there were plainly against
it; nothing knew who was a guest, and "please leave" was just words.

Run inside the backend container:   python tests/test_guests.py
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


import random
from house_world import make_world
from core import scheduler
from systems import guests
from systems.room_assignment import refresh_character_room
from systems.travel import TRAVEL_WALKING_STATES

# Lindqvists live in starter_house_1 (x 25..), Okafors in starter_house_2 (x 50..), Moreaus in starter_house_3.


def setup(minute=14 * 60):
    w = make_world()
    w["tick"] = 50000
    w["calendar"] = {"minute_of_day": minute, "hour": minute // 60, "minute": minute % 60}
    w["households"]["lind"]["name"] = "The Lindqvist Household"
    for cid, age in (("joseph", 40), ("robert", 41), ("kathleen", 10), ("susan", 11)):
        w["characters"][cid].update(age=age, traits=[], relationships={}, legal={"status": "free"}, activity=None,
                                    route=[], is_moving=False, off_grid=False, cognition={})
    j = w["characters"]["joseph"]
    j.update(x=34, y=4, building_id="starter_house_1")        # at home, in his kitchen
    return w, j


def step(w, ticks=1):
    for _ in range(ticks):
        w["tick"] += 1
        for c in w["characters"].values():
            refresh_character_room(c, w)
            guests.track(c, w)
        scheduler.fire_due(w)


def visit(w, cid, x=35, y=5):
    c = w["characters"][cid]
    c.update(x=x, y=y, building_id="starter_house_1")
    step(w)
    return c


def mems(c, *words):
    return [m["text"] for m in c.get("memories", []) if all(wd.lower() in m["text"].lower() for wd in words)]


def said(c):
    return (c.get("current_speech") or {}).get("utterance") or ""


conv = lambda *ids: {"participants": list(ids)}

# ---- walking in uninvited; both sides are told ----------------------------------------------------------------------
w, j = setup()
r = visit(w, "robert")
v = r.get("guest_visit") or {}
check("walking into the Lindqvists' home: Robert is a guest there, uninvited",
      v.get("household_id") == "lind" and v.get("status") == "uninvited", str(v))
check("... Joseph is woken by it", (j["cognition"] or {}).get("wake_reason") == "house_guest")
host_lines = " ".join(guests.context_lines(j, w))
check("... and told who is in his home and how they got in", "Robert Okafor is in your home" in host_lines
      and "without being let in" in host_lines, host_lines)
check("... Robert is told it isn't his home", "It isn't your home" in " ".join(guests.context_lines(r, w)))
check("his own home isn't a visit", not guests.context_lines(w["characters"]["kathleen"], w))

# ---- "come in" welcomes; "you don't have to leave" doesn't send anyone away ---------------------------------------
guests.on_line(w, conv("joseph", "robert"), "joseph", "Oh, hi Robert! Come on in.")
check("'come in' from Joseph: welcome", r["guest_visit"]["status"] == "welcome")
guests.on_line(w, conv("joseph", "robert"), "joseph", "You don't have to leave yet, stay for coffee.")
check("'you don't have to leave' isn't asking him to go", r["guest_visit"]["status"] == "welcome")

# ---- asked to leave: an agreeable guest goes home --------------------------------------------------------------------
random.seed(1)
_orig = random.random
random.random = lambda: 0.0                                  # always does as asked
guests.on_line(w, conv("joseph", "robert"), "joseph", "Robert, I'd like you to leave now, please.")
check("'I'd like you to leave' from someone who lives there: asked to leave", r["guest_visit"]["status"] == "asked_to_leave")
check("... and he remembers being asked", mems(r, "asked me to leave"))
step(w, guests.DEPART_DELAY_TICKS + 1)
check("... a moment later he sets off home", r.get("travel_state") in TRAVEL_WALKING_STATES, str(r.get("travel_state")))
check("... saying so", "head home" in said(r), said(r))
random.random = _orig

# ---- asked to leave and won't: it escalates, all the way to the police ---------------------------------------------
w, j = setup()
r = visit(w, "robert")
random.random = lambda: 0.999                               # never does as asked
guests.on_line(w, conv("joseph", "robert"), "joseph", "Get out of my house!")
check("'get out of my house': asked to leave", r["guest_visit"]["status"] == "asked_to_leave")
check("... he's woken, told the host wants him gone", (r["cognition"] or {}).get("wake_reason") == "asked_to_leave")
check("... and his prompt says staying means ignoring them",
      "staying means ignoring" in " ".join(guests.context_lines(r, w)))
step(w, guests.ESCALATE_TICKS + 1)
check("5 minutes on, still there: Joseph asks again, firmly", "I asked you to leave" in said(j), said(j))
check("... trust drops", (j["relationships"].get("robert") or {}).get("trust", 50) < 50)
check("... Joseph holds a grudge", any(g.get("caused_by") == "robert" or g.get("caused_by_id") == "robert"
                                       or "robert" in str(g) for g in j.get("grievances", [])))
step(w, guests.ESCALATE_TICKS + 1)
check("10 minutes on: a last warning, with the police", "calling the police" in said(j), said(j))
step(w, guests.ESCALATE_TICKS + 1)
calls = [c for c in w.get("calls", []) if c.get("caller") == "joseph"]
check("15 minutes on: Joseph calls the police", calls and calls[-1]["type"] == "police", str(w.get("calls")))
check("... a trespass incident", any(i["type"] == "trespass" and i["offender_id"] == "robert" for i in w["incidents"]))
step(w, 121)
check("the police come and escort him out: walking home", r.get("travel_state") in TRAVEL_WALKING_STATES)
check("... with a warning on his record", (r.get("legal") or {}).get("warnings"))
check("... and he remembers it", mems(r, "police", "escorted"))
random.random = _orig

# ---- coming straight back after being sent away isn't welcome --------------------------------------------------------
r.update(travel_state=None, x=60, y=8, building_id="starter_house_2")
step(w)
r.pop("_let_in", None)
r = visit(w, "robert")
check("back an hour later: not welcome, and the host knows why", r["guest_visit"]["status"] == "uninvited"
      and "came back after being sent home" in r["guest_visit"]["how"], str(r["guest_visit"]))

# ---- let in at the door: welcome, for a while -------------------------------------------------------------------------
w, j = setup()
w["characters"]["robert"]["_let_in"] = {"household_id": "lind", "tick": w["tick"]}
r = visit(w, "robert")
check("let in at the door: welcome", r["guest_visit"]["status"] == "welcome" and r["guest_visit"]["how"] == "let in at the door")
random.random = lambda: 0.0
step(w, guests.WELCOME_TICKS["other"] + 2)
check("after an hour the host says it's time to go", "time to head home" in said(j) or "another time" in said(j), said(j))
step(w, guests.DEPART_DELAY_TICKS + 1)
check("... and he goes", r["guest_visit"]["status"] == "asked_to_leave" and r.get("travel_state") in TRAVEL_WALKING_STATES)
random.random = _orig

# ---- a child guest goes home for dinner -------------------------------------------------------------------------------
w, j = setup(minute=17 * 60 + 50)
random.random = lambda: 0.0
s = visit(w, "susan")
step(w, 10 * 60 + guests.DEPART_DELAY_TICKS + 2)
check("a child visiting before dinner is sent home at 18:00", "dinner time" in said(j), said(j))
check("... and goes", s.get("travel_state") in TRAVEL_WALKING_STATES, str(s.get("travel_state")))
random.random = _orig

# ---- everyone who lives there goes to bed: guests leave ---------------------------------------------------------------
w, j = setup()
w["characters"]["robert"]["_let_in"] = {"household_id": "lind", "tick": w["tick"]}
r = visit(w, "robert")
j["activity"] = {"type": "sleep", "phase": "using", "phase_started_tick": w["tick"], "duration": 28800}
step(w, guests.CHECK_EVERY_TICKS + 1)
check("the host goes to bed: the guest lets himself out and goes home", r.get("travel_state") in TRAVEL_WALKING_STATES
      and mems(r, "gone to bed"))

# ---- the guest saying they'll head home ------------------------------------------------------------------------------
w, j = setup()
r = visit(w, "robert")
guests.on_line(w, conv("joseph", "robert"), "robert", "Well, I should get going, see you around.")
step(w, guests.DEPART_DELAY_TICKS + 1)
check("Robert saying 'I should get going': he goes", r.get("travel_state") in TRAVEL_WALKING_STATES)

# ---- a child who won't leave: the parents are called --------------------------------------------------------------------
w, j = setup()
k = visit(w, "kathleen")
random.random = lambda: 0.999
guests.on_line(w, conv("joseph", "kathleen"), "joseph", "Kathleen, you need to go home now.")
step(w, 3 * (guests.ESCALATE_TICKS + 1))
check("a child who won't go: her parents get a call", mems(w["characters"]["robert"], "called", "Kathleen"))
check("... and she's sent home", k.get("travel_state") in TRAVEL_WALKING_STATES)
check("... no police for a child", not w.get("calls"))
random.random = _orig

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
