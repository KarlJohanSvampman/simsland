"""
Debug Draw's data (systems/path_debug.py, systems/props.py's search records, api/debug_draw.py):
    - an anchor search records every place in the running, its score (walking distance) and why any were passed over
    - a route plan records what it is for (resolved), the path, an estimate, and -- when the walk ends -- how it ended
      and how long it really took
    - the endpoint returns the route being walked, perception ranges, who is seen, and who is in range but not seen

Run inside the backend container:   python tests/test_debug_draw.py
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

w = make_world()
w["tick"] = 1000
ensure_world_defaults(w)
rob = w["characters"]["robert"]
rob.update(activity=None, age=40)

from systems.activities import start_activity
ok = start_activity(rob, w, "use_toilet")
plan = (rob.get("path_plans") or [{}])[-1]
check("a walk to the toilet: planned", ok and plan.get("ok"), str(plan)[:300])
cands = plan.get("candidates") or []
check("... with the toilets that were in the running, scored, the chosen one first",
      cands and cands[0].get("chosen") and all("score" in c_ for c_ in cands) and plan.get("interaction") == "use_toilet", str(cands)[:300])
check("... another household's toilet is listed as passed over", any(c_.get("skipped") == "another household's" for c_ in cands)
      or len(cands) == 1, str([(c_["label"], c_["skipped"]) for c_ in cands]))
check("... the target resolved to the prop, with coordinates", (plan.get("target") or {}).get("kind") == "prop"
      and "toilet" in (plan.get("target") or {}).get("label", "") and plan["target"].get("x") is not None, str(plan.get("target")))
check("... a simplified path and an estimate", len(plan.get("path") or []) >= 2 and (plan.get("eta_s") or 0) > 0, str(plan.get("eta_s")))

# walk it
from systems.movement import update_character_movement
for _ in range(2000):
    if not rob.get("is_moving"):
        break
    w["tick"] += 1
    update_character_movement(rob, w)
plan = rob["path_plans"][-1]
check("arriving: the plan says so, and how long it really took", plan.get("ended") == "arrived" and plan.get("actual_s", 0) > 0,
      str({k: plan.get(k) for k in ("ended", "actual_s", "eta_s")}))

# the endpoint's pieces
import api.debug_draw as dd
dd.load_world = lambda sim_id="default": w
k = w["characters"]["kathleen"]
k.update(x=rob["x"] + 2, y=rob["y"], building_id=rob["building_id"])
rob["perception"] = {"visible_people": [{"id": "kathleen", "name": k["name"], "distance": 2, "visibility": 0.9}],
                     "audible_events": [{"x": k["x"], "y": k["y"], "volume": 60, "clarity": 0.8, "distance": 2, "sound": "talking"}]}
out = dd.debug_draw("robert")
p = out["perception"]
check("the endpoint: who they see (with where), what they hear, and their ranges",
      p["seen"][0]["id"] == "kathleen" and p["seen"][0]["x"] == k["x"] and p["heard"][0]["what"] == "talking"
      and p["visual_range"] > 0 and p["hearing_range"] > 0, str(p)[:300])
check("... and their recent plans", out["navigation"]["plans"] and out["navigation"]["plans"][-1]["ended"] == "arrived")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
