"""
Finished intentions are kept (brain/intention_history.py) so the inspector can list them in the order they came; and a
character has ONE wish to confide, listing what it is about (systems/confiding.py).

Live (2026-11-06): the Mind tab only ever showed open intentions, so nobody could see what had been done; and one
character carried 70+ identical "confide in someone" desires at frustration 1.0.

Run inside the backend container:   python tests/test_intention_history.py
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
from brain import intention_history as ih
from core import event_bus

w = make_world()
w["tick"] = 1000
k = w["characters"]["kathleen"]
k["active_intentions"] = [{"type": "take_shower", "reason": "hygiene_low", "category": "health"},
                          {"type": "eat_food", "reason": "very_hungry", "category": "survival"},
                          {"type": "visit_person", "target_id": "susan", "reason": "miss her"}]
ih.track(k, w)
check("open intentions are noted with when they came", all(r["since"] == 1000 for r in k["_intention_seen"].values()))

# a shower is taken: the activity completes, then the intention goes away -> done
w["tick"] = 1300
event_bus.emit("activity_completed", {"character_id": "kathleen", "activity_type": "take_shower"})
event_bus.flush(w)
k["active_intentions"] = [i for i in k["active_intentions"] if i["type"] != "take_shower"]
ih.track(k, w)
h = k["intention_history"][-1]
check("taking the shower ticks the shower intention off", h["type"] == "take_shower" and h["outcome"] == "done"
      and h["since"] == 1000 and h["ended"] == 1300, str(h))

# hunger satisfied through a plan -> done (via intention.satisfied for the types it replaces)
w["tick"] = 1600
event_bus.emit("intention.satisfied", {"character_id": "kathleen", "intention": "reduce_hunger", "why": "Light meal worked"})
event_bus.flush(w)
k["active_intentions"] = [i for i in k["active_intentions"] if i["type"] != "eat_food"]
ih.track(k, w)
h = k["intention_history"][-1]
check("a plan that satisfied hunger ticks eat_food off, saying how", h["type"] == "eat_food" and h["outcome"] == "done"
      and h["how"] == "Light meal worked", str(h))

# a visit that just goes away -> dropped
w["tick"] = 1900
k["active_intentions"] = []
ih.track(k, w)
h = k["intention_history"][-1]
check("an intention that goes away without being done is 'dropped'", h["type"] == "visit_person" and h["outcome"] == "dropped")
check("the history is in the order they ended", [x["type"] for x in k["intention_history"]] == ["take_shower", "eat_food", "visit_person"])

# an expectation met -> done
from systems.expectations import satisfy_expectation
k["expectations"] = {"keep_room_clean": {"template_id": "keep_room_clean", "status": "pending", "streak": 0, "frustration": 0}}
k["active_intentions"] = [{"type": "expectation:keep_room_clean", "reason": "messy"}]
ih.track(k, w)
w["tick"] = 2000
satisfy_expectation(k, "keep_room_clean", w)
k["active_intentions"] = []
ih.track(k, w)
check("an expectation met is done", k["intention_history"][-1]["type"] == "expectation:keep_room_clean"
      and k["intention_history"][-1]["outcome"] == "done")

# ---- one wish to confide -------------------------------------------------------------------------------------------
from systems import confiding
c = w["characters"]["susan"]
c.update(memories=[], persistent_desires=[], relationships={})
for i in range(5):
    confiding.tag_dramatic_memory(c, w, f"Something upsetting happened ({i})", importance=0.7)
mine = [d for d in c["persistent_desires"] if d["type"] == "confide_in_someone" and d["active"]]
check("five dramatic moments: one wish to confide, about all five", len(mine) == 1 and len(mine[0]["about"]) == 5, str(mine))

# an older save: one desire per memory, some of them for forgotten memories
old = {"type": "confide_in_someone", "importance": 0.8, "frustration": 1.0, "progress": 0, "resolved": False, "active": True}
c["persistent_desires"] += [dict(old, target=c["memories"][0]["id"]), dict(old, target="mem_long_forgotten"), dict(old, target="mem_also_gone")]
lines = confiding.get_confiding_context(c, w)
mine = [d for d in c["persistent_desires"] if d["type"] == "confide_in_someone" and d["active"]]
check("an older save's copies merge into one, forgotten things dropped", len(mine) == 1 and len(mine[0]["about"]) == 5
      and mine[0]["frustration"] == 1.0, str([(d.get("about"), d.get("target")) for d in mine]))
check("the prompt says it once", len(lines) == 1 and "and 4 other things" in lines[0], str(lines))

# nobody to confide in: it stays (once); someone close: told, and the wish is over
confiding.resolve_confide_opportunities(c, w)
check("with nobody close to tell, the wish stays -- once", len([d for d in c["persistent_desires"] if d["type"] == "confide_in_someone" and d["active"]]) == 1)
c["relationships"]["steven"] = {"labels": ["parent"], "trust": 60}
w["characters"]["steven"] = {"id": "steven", "name": "Steven Moreau", "alive": True, "relationships": {}}
confiding._do_confide = lambda c_, confidant, mem, world: None
confiding.resolve_confide_opportunities(c, w)
check("told to someone close: every memory marked told, and the wish is over",
      all(m.get("confided") for m in c["memories"]) and not [d for d in c["persistent_desires"] if d["type"] == "confide_in_someone" and d["active"]])

# Live (2026-11-21): needs that were met showed as "dropped" -- the completed activity is named differently from the
# intention ("drink_water" for drink, "eat_meal" for eat_food, "dust_and_wipe" for clean_zone)
def _done_after(activity, itype, interaction=None, started_for=None, other_current=None):
    w["tick"] += 100
    k["active_intentions"] = [{"type": itype, "reason": "x"}] + ([{"type": other_current}] if other_current else [])
    if started_for is not None:
        k["_activity_starts"] = [[w["tick"], activity, started_for]]
    ih.track(k, w)
    w["tick"] += 50
    event_bus.emit("activity_completed", {"character_id": "kathleen", "activity_type": activity, "interaction": interaction})
    event_bus.flush(w)
    k["active_intentions"] = [i for i in k["active_intentions"] if i["type"] != itype]
    ih.track(k, w)
    return next(x for x in reversed(k["intention_history"]) if x["type"] == itype)["outcome"]

check("drinking water ticks 'drink' off", _done_after("drink_water", "drink") == "done")
check("eating a meal ticks 'eat_food' off", _done_after("eat_meal", "eat_food") == "done")
check("dusting ticks 'clean_zone' off", _done_after("dust_and_wipe", "clean_zone") == "done")
check("a night's sleep ticks 'seek_caffeine_or_rest' off", _done_after("sleep", "seek_caffeine_or_rest") == "done")
check("a prop interaction on the satisfied-by list counts", _done_after("interact", "drink", interaction="use_tap") == "done")
check("an activity started for an intention ticks it off ('sit_and_relax' for relieve_worry)",
      _done_after("sit_and_relax", "relieve_worry", started_for="relieve_worry") == "done")
check("... but not one with its own list: a toilet trip started during 'sleep' doesn't tick sleep off",
      _done_after("use_toilet", "sleep", started_for="sleep") == "dropped")
check("heating a meal is not eating it", _done_after("heat_meal", "eat_food") == "dropped")

# Live (2026-11-21): an intention a plan saw to (eat_food for Reduce Hunger, feed_child_* for Feed the Kids) was cleared
# by the plan before the intention.satisfied event marked it, so it showed as "dropped"
from brain.actionplans import runner
w["tick"] += 100
k["active_intentions"] = [{"type": "eat_food", "reason": "hungry"}, {"type": "feed_child_char_kid", "child_id": "char_kid"},
                          {"type": "brush_teeth", "reason": "x"}]
ih.track(k, w)
w["tick"] += 10
runner._clear_replaced(k, {"replaces": ["eat_food", "feed_child_*"]}, world=w, how="Light meal worked")
ih.track(k, w)
last = {x["type"]: x for x in k["intention_history"][-2:]}
check("what a plan cleared is ticked off as done, saying how",
      last.get("eat_food", {}).get("outcome") == "done" and last["eat_food"].get("how") == "Light meal worked", str(last))
check("... the per-child ones too", last.get("feed_child_char_kid", {}).get("outcome") == "done", str(last))
check("... and only those", [i["type"] for i in k["active_intentions"]] == ["brush_teeth"])

# socializing with someone who has left ends (systems/activities.py)
from systems import activities as A
w["tick"] = 50000
pat = {"id": "pat", "x": 10, "y": 10, "building_id": "house"}
mar = {"id": "mar", "name": "Margaret", "x": 11, "y": 10, "building_id": "house"}
w["characters"].update(pat=pat, mar=mar)
act = {"type": "socialize", "phase": "using", "target_id": "mar"}
check("socializing side by side goes on", not A._socialize_partner_gone(pat, w, act))
mar.update(building_id=None, x=40, y=30)
check("... a partner who just stepped away gets a moment", not A._socialize_partner_gone(pat, w, act))
w["tick"] += A.SOCIALIZE_AWAY_GRACE_TICKS
check("... and once they've been gone a while, it's over", A._socialize_partner_gone(pat, w, act))
mar.update(building_id="house", x=12, y=11)
check("... back in the room: the chat goes on", not A._socialize_partner_gone(pat, w, act) and "_partner_away_since" not in act)
mar["off_grid"] = True
w["tick"] += A.SOCIALIZE_AWAY_GRACE_TICKS + 1
A._socialize_partner_gone(pat, w, act)
w["tick"] += A.SOCIALIZE_AWAY_GRACE_TICKS
check("a partner who left the map ends it", A._socialize_partner_gone(pat, w, act))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
