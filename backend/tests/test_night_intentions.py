"""
Nights: asleep, an unanswered intention doesn't escalate (re-armed instead); a sleeping child doesn't make a parent's
"feed the child" duty, and the duty goes only to a parent who is awake; "suggest a shower" only between two people who
are awake and in the same space. (brain/intentions.py, systems/child_care.py, systems/social_odor.py)

Run inside the backend container:   python tests/test_night_intentions.py
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


from brain.intentions import check_intention_deadlines
c = {"id": "a", "activity": {"type": "sleep"}, "active_intentions": [{"type": "suggest_hygiene", "stage": 0, "priority": 30, "deadline_tick": 100}]}
w = {"tick": 200}
check_intention_deadlines(c, w)
i = c["active_intentions"][0]
check("asleep: past its deadline but not escalated, re-armed", i["stage"] == 0 and i["priority"] == 30 and i["deadline_tick"] > 200, str(i))
c["activity"] = None
w["tick"] = i["deadline_tick"] + 1
check_intention_deadlines(c, w)
check("awake again: escalates as before", c["active_intentions"][0]["stage"] == 1)

from house_world import make_world
from systems.schema_defaults import ensure_world_defaults
import systems.child_care as cc
w = make_world(); w["tick"] = 5000
# a parent and child at the Moreaus' (as the run harness sets them up)
w["characters"]["steven"] = {"id": "steven", "name": "Steven Moreau", "first_name": "Steven", "family_name": "Moreau",
                             "household_id": "mor", "building_id": "starter_house_3", "x": 85, "y": 5, "age": 38,
                             "age_group": "adult", "sex": "male", "alive": True}
w["households"]["mor"]["members"].append("steven")
kid = w["characters"]["susan"]
kid.update(age=11, age_group="child", sex="female", x=83, y=5)
ensure_world_defaults(w)
w["characters"]["steven"].setdefault("relationships", {})["susan"] = {"labels": ["parent"], "authority_over": True}
parents = cc._find_parents_for_child(kid, w)
check("a child with parents (for the test)", bool(parents), kid.get("name"))
need = next(n for n, cfg in cc.CHILD_NEED_CONFIG.items() if cfg["mode"] == "parent_serves")
kid.setdefault("body", {})[need] = 100
kid.pop("_awaiting_caregiver", None)
kid["activity"] = {"type": "sleep"}
for p in parents:
    p["active_intentions"] = []; p["activity"] = None
cc.tick_child_needs(w)
check("child asleep: no feed duty for the parents", not any(str(x.get("type")).startswith("feed_child_") for p in parents for x in p.get("active_intentions") or []))
kid["activity"] = None
for p in parents[1:]:
    p["activity"] = {"type": "sleep"}
parents[0]["activity"] = {"type": "sleep"} if len(parents) == 1 else None
cc.tick_child_needs(w)
if len(parents) == 1:
    check("the only parent asleep: no duty yet", not any(str(x.get("type")).startswith("feed_child_") for x in parents[0].get("active_intentions") or []))
    parents[0]["activity"] = None; kid.pop("_awaiting_caregiver", None)
    cc.tick_child_needs(w)
    check("... and once they're up, it's theirs", any(str(x.get("type")).startswith("feed_child_") for x in parents[0].get("active_intentions") or []))
else:
    got = [p["id"] for p in parents if any(str(x.get("type")).startswith("feed_child_") for x in p.get("active_intentions") or [])]
    check("child awake: the duty goes only to the parent who is up", got == [parents[0]["id"]], str(got))

import systems.social_odor as so
a, b = w["characters"]["robert"], w["characters"]["joseph"]
a.update(activity=None, active_intentions=[]); b.update(activity={"type": "sleep"}, active_intentions=[])
a.setdefault("body", {})["odor"] = 100
b.update(x=a["x"] + 1, y=a["y"], building_id=a.get("building_id"))
so.apply_odor_social_pressure(a, w)
check("the one next to someone smelly is asleep: no 'suggest a shower'", not any(x.get("type") == "suggest_hygiene" for x in b.get("active_intentions") or []))
b["activity"] = None
so.apply_odor_social_pressure(a, w)
check("both awake, side by side: they think of saying something", any(x.get("type") == "suggest_hygiene" for x in b.get("active_intentions") or []))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
