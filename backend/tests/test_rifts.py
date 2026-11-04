"""
Falling out with someone you live with (systems/rifts.py): a confrontation that ends badly no longer sends anyone off
on the spot; it opens a rift. Each day they're woken wanting to find a way forward (their own choice what, and the
AI's reading of the conversation says how it went -- here, the confrontation's outcome stands in for that), and only
after MAX_ATTEMPTS tries or STAY_DAYS days do they consider leaving, for a purpose: time away to come back and make
peace, or moving out for good, which the household sees as they come back for their things.

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
import core.event_handlers  # noqa: F401
import social.tick  # noqa: F401
from core import scheduler, event_bus
from systems import rifts
from social import confrontations as X, standing


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
    # things were already strained (one ordinary disagreement shouldn't sink anyone's regard)
    k["relationships"]["robert"] = {"standing": {"score": -29, "confidence": 0.5, "history": []}}
    r["relationships"]["kathleen"] = {"standing": {"score": -29, "confidence": 0.5, "history": []}}
    w["fight_log"] = []
    return w, k, r, j


def bad_fight(w, a, b, outcome="relationship_deterioration", topic="the dishes", physical=False):
    conf = X.start(w, a["id"], b["id"], ctype="criticism", problem=topic)
    conf["stage_idx"], conf["peak_stage"] = 2, "verbal_confrontation"
    if physical:
        X.on_hostile_act(w, a["id"], b["id"], "punch")
    X.end(w, conf, outcome)
    event_bus.flush(w)


def advance(w, ticks):
    w["tick"] += ticks
    scheduler.fire_due(w)


def mems(c, *words):
    return [m["text"] for m in c.get("memories", []) if all(x.lower() in m["text"].lower() for x in words)]


def settle_conflicts(w, outcome, by="robert", with_="kathleen"):
    """The one woken wanting to make peace talks to the other; the AI's reading says how it went (outcome)."""
    c = w["characters"][by]
    if with_ in (c.get("wants_to_repair") or {}):
        conf = X.start(w, by, with_, ctype="negotiation", reconciliation=True, problem="making peace")
        X.end(w, conf, outcome)
        event_bus.flush(w)


# ---- a bad fight opens a rift, not a suitcase ----------------------------------------------------------------------
w, k, r, j = setup()
bad_fight(w, r, k)
check("a confrontation that ends badly: a rift for both, about what it was about",
      r["rifts"]["kathleen"]["status"] == "open" and k["rifts"]["robert"]["topics"] == ["the dishes"],
      str((standing.score(r, "kathleen"), r.get("rifts"))))
check("... nobody moves out on the spot", not r.get("temporary_residence") and not r.get("off_grid")
      and not k.get("temporary_residence") and not k.get("off_grid"))

# ---- trying, and getting nowhere -------------------------------------------------------------------------------------
advance(w, rifts.FIRST_TRY_TICKS + 1)
check("a few hours later he's woken wanting to find a way forward", "kathleen" in (r.get("wants_to_repair") or {})
      and r["cognition"].get("wake_reason") in (None, "wants_to_repair") or r.get("wants_to_repair"))
check("... with the go-between he could ask in his prompt", any("ask Joseph" in l for l in rifts.context_lines(r, w)),
      str(rifts.context_lines(r, w)))
settle_conflicts(w, "apology_rejected")
check("a few hours later he recalls what led to it", mems(r, "things have been bad with kathleen", "the dishes"),
      str([m["text"] for m in r["memories"]][-4:]))
check("... and tries something: no understanding, one try down", r["rifts"]["kathleen"]["attempts"] >= 1,
      str(r["rifts"]["kathleen"]))
advance(w, rifts.DAY)
settle_conflicts(w, "unresolved")
check("what he tried is recorded", len(r["rifts"]["kathleen"]["tried"]) >= 2, str(r["rifts"]["kathleen"]))

# ---- after three tries leaving is on his mind -- his decision, with notice ---------------------------------------
for _ in range(3):
    advance(w, rifts.DAY)
    settle_conflicts(w, "unresolved")
rk = r["rifts"]["kathleen"]
check("three tries with nothing: leaving is on his mind, nothing rolled -- he hasn't gone",
      rk.get("may_leave") and not r.get("temporary_residence") and not r.get("off_grid"), str(rk))
check("... his prompt says it's his call, with 2-3 days' notice", any("announce_leaving" in l for l in rifts.context_lines(r, w)))


def announce(days=2, purpose="time_away"):
    event_bus.emit("leaving_announced", {"character_id": "robert", "about": "Kathleen", "days": days,
                                         "purpose": purpose, "reason": "we just keep fighting"})
    event_bus.flush(w)


announce(days=5)
n = rk.get("notice") or {}
check("he announces it: 2-3 days ahead (5 is held to 3)", n.get("days") == 3 and n["leave_tick"] == w["tick"] + 3 * rifts.DAY, str(n))
check("... the household is told, Kathleen that it's because of her", mems(k, "leaving for a while in 3 days because of me")
      and mems(j, "leaving for a while in 3 days") if "joseph" in [m["id"] for m in rifts._housemates(r, w)]
      else mems(k, "leaving for a while in 3 days because of me"), str([m["text"] for m in k["memories"]][-2:]))
check("... and her prompt says trying to make it right holds him off", any("each day you genuinely try" in l.lower()
      for l in rifts.context_lines(k, w)))
event_bus.emit("leaving_called_off", {"character_id": "robert", "about": "Kathleen", "reason": "I'll give it time"})
event_bus.flush(w)
check("he can call it off", not rk.get("notice") and mems(k, "isn't leaving after all"))
announce(days=2)
leave_at = rk["notice"]["leave_tick"]

from brain.conversations import create_conversation, add_message
from social import discourse


def kathleen_tries():
    conv = create_conversation(w, ["kathleen", "robert"], topic="general")
    w["tick"] += 3
    add_message(w, conv, "kathleen", "I'm sorry about the dishes. Can we talk?", "apology", "general", w["tick"])
    discourse.on_line({"conversation_id": conv["id"], "speaker_id": "kathleen", "target_id": "robert",
                       "utterance": "I'm sorry", "social": {"intent": "apologise", "escalation": "de-escalate"}}, w)
    return conv


advance(w, rifts.DAY + 60)
kathleen_tries()
check("Kathleen tries to make it right: he holds off another day", rk["notice"]["leave_tick"] == leave_at + rifts.DAY
      and mems(r, "hold off leaving another day"), str(rk["notice"]))
kathleen_tries()
check("... once a day, not per sentence", rk["notice"]["leave_tick"] == leave_at + rifts.DAY)
from social import confrontations as XX
for conf in XX.active(w):
    XX.end(w, conf, "unresolved")
event_bus.flush(w)
# then she stops trying: the notice runs out and he goes
advance(w, 2 * rifts.DAY + 1)
res = r.get("temporary_residence") or {}
check("she stops trying: the notice runs out and he leaves, to stay with his close friend Joseph",
      res.get("host_id") == "joseph" and res.get("purpose") == "time_away", str(res) + str(rk))
check("... and knows why he's going, including the day he held off", mems(r, "leaving to get some distance from kathleen")
      and mems(r, "held off 1 day"), str([m["text"] for m in r["memories"]][-2:]))
check("... Kathleen notices he's gone", mems(k, "robert okafor has left for a while"))
check("... he heads for Joseph's house", (r.get("move_target") or {}).get("target_id") == "building:starter_house_1"
      or r.get("is_moving"), str(r.get("move_target")))

# ---- ... and comes back to make peace ------------------------------------------------------------------------------
advance(w, rifts.AWAY_DAYS[1] * rifts.DAY + 1)
check("after a few days he comes back home to try again", not r.get("temporary_residence")
      and r["rifts"]["kathleen"]["status"] == "open" and mems(r, "came back home to try to make peace"))
advance(w, 1801)
settle_conflicts(w, "mutual_understanding")                 # this time she comes round
check("... and this time they come to an understanding: the rift is closed for both",
      r["rifts"]["kathleen"]["status"] == "resolved" and k["rifts"]["robert"]["status"] == "resolved",
      str(r["rifts"]["kathleen"]))
check("... with standing back above the line", rifts.standing(r, "kathleen") >= rifts.STANDING_BAD
      and rifts.standing(k, "robert") >= rifts.STANDING_BAD)

# ---- beyond repair: moving out, and coming back for his things -----------------------------------------------------
w, k, r, j = setup()
bad_fight(w, r, k, outcome="physical_fight", topic="money", physical=True)
for _ in range(10):
    advance(w, rifts.DAY)
    settle_conflicts(w, "unresolved")
    if r["rifts"]["kathleen"].get("may_leave"):
        break
event_bus.emit("leaving_announced", {"character_id": "robert", "about": "Kathleen", "days": 2, "purpose": "moving_out"})
event_bus.flush(w)
advance(w, 2 * rifts.DAY + 1)
res = r.get("temporary_residence") or {}
check("a fight that got physical and won't mend: he moves out", res.get("purpose") == "moving_out", str(res))
for _ in range(rifts.PICKUPS):
    advance(w, rifts.PICKUP_DAYS[1] * rifts.DAY + 1)
check("... coming back every few days for his things, which Kathleen sees", len(mems(k, "came by and took")) == rifts.PICKUPS,
      str(mems(k, "came by")))
check("... until the last of them: moved out", r["rifts"]["kathleen"]["status"] == "moved_out"
      and mems(k, "they've moved out"))

# ---- on notice, and she wins him round: he stays --------------------------------------------------------------------
w, k, r, j = setup()
bad_fight(w, r, k)
for _ in range(6):
    advance(w, rifts.DAY)
    settle_conflicts(w, "unresolved")
    if r["rifts"]["kathleen"].get("may_leave"):
        break
event_bus.emit("leaving_announced", {"character_id": "robert", "about": "Kathleen", "days": 2})
event_bus.flush(w)
conv = kathleen_tries()
conf = XX.get(w, conv.get("related_confrontation_id"))
check("her try is a reconciliation he takes part in", conf and conf["reconciliation"])
XX.end(w, conf, "mutual_understanding")
event_bus.flush(w)
check("they work it out: the rift is closed and the notice with it -- he stays",
      r["rifts"]["kathleen"]["status"] == "resolved" and not r["rifts"]["kathleen"].get("notice"))
advance(w, 4 * rifts.DAY)
check("... and he doesn't leave when the notice would have run out", not r.get("temporary_residence") and not r.get("off_grid"))

# ---- bad standing alone, and children ------------------------------------------------------------------------------
w, k, r, j = setup()
k["relationships"]["robert"] = {"standing": {"score": -60, "confidence": 0.6, "history": []}}
rifts.scan(w)
check("standing sunk below the line, no fight needed: a rift", (k.get("rifts") or {}).get("robert", {}).get("status") == "open")
s = w["characters"]["susan"]
check("a child gets no rift (and never leaves)", rifts.open_rift(s, w, "kathleen") is None)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
