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

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
