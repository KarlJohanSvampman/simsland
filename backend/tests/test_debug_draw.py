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

# ---- talking through a wall: caught (systems/conversation_reach.py) ----
from brain.perception import wall_hit, los_trace
from systems.room_assignment import room_at
pair = None
xs = range(int(rob["x"]) - 12, int(rob["x"]) + 13)
ys = range(int(rob["y"]) - 12, int(rob["y"]) + 13)
for x in xs:
    for y in ys:
        ra = room_at(w, x, y)
        if not ra:
            continue
        for dx, dy in ((1, 0), (0, 1)):
            rb = room_at(w, x + dx, y + dy)
            if rb and rb != ra and wall_hit({"x": x, "y": y}, {"x": x + dx, "y": y + dy}, w):
                pair = ((x, y), (x + dx, y + dy))
                break
        if pair: break
    if pair: break
check("found two rooms with a wall between them (for the test)", pair is not None)
from brain.conversations import create_conversation, add_message
rob.update(x=pair[0][0], y=pair[0][1], is_moving=False, route=[])
k.update(x=pair[1][0], y=pair[1][1])
conv = create_conversation(w, ["robert", "kathleen"])
w["conversation_reach_log"] = []
add_message(w, conv, "robert", "Did you see the game last night?", "smalltalk", "general", w["tick"])
log = w.get("conversation_reach_log") or []
check("a line said through a wall is logged: different rooms, no line of sight, where it was blocked",
      log and "different rooms" in log[-1]["issues"] and any(i.startswith("no line of sight") for i in log[-1]["issues"])
      and log[-1]["hit"] is not None and log[-1]["speaker_name"] and log[-1]["line"].startswith("Did you"), str(log[-1:])[:400])
check("... and kept on the conversation for Debug Draw", (conv.get("reach") or {}).get("robert>kathleen", {}).get("ok") is False)
k.update(x=pair[0][0], y=pair[0][1])                   # right beside him, same room
w["conversation_reach_log"] = []
add_message(w, conv, "kathleen", "No, I was out.", "smalltalk", "general", w["tick"])
check("face to face: no incident", not w["conversation_reach_log"], str(w["conversation_reach_log"])[:300])
w["conversations"][conv["id"]]["reach"] = {}
k.update(x=pair[1][0], y=pair[1][1])
out = dd.debug_draw("robert")
t = out["conversations"]
check("the endpoint: conversations they're in, checked now", t and t[0]["id"] == "kathleen" and not t[0]["now"]["ok"], str(t)[:300])

# ---- the sight-line tests a look really made ----
from brain.perception import perceive_people
rob["_los_checks"] = {"tick": w["tick"], "checks": []}
perceive_people(rob, w)
chk = [x for x in rob["_los_checks"]["checks"] if x["id"] == "kathleen"]
check("a look records the sight-line test: not seen, stopped at the wall, with distances",
      chk and chk[0]["ok"] is False and chk[0]["hit"] and chk[0]["hit_distance"] is not None and chk[0]["distance"] > 0, str(chk)[:300])

# ---- mistaking someone for someone else (systems/misrecognition.py) ----
from systems import misrecognition as mr
other = {"id": "o1", "name": "Bob", "sex": "male", "age": 40, "x": 0, "y": 0}
look = {"id": "o2", "name": "Sam", "sex": "male", "age": 44, "x": 50, "y": 50}
girl = {"id": "o3", "name": "Ann", "sex": "female", "age": 41, "x": 50, "y": 50}
obs = {"id": "me", "relationships": {"o1": {}, "o2": {}, "o3": {}}, "x": 0, "y": 0}
W = {"characters": {"o1": other, "o2": look, "o3": girl, "me": obs}, "calendar": {"hour": 12}}
far, near = [], []
for i in range(400):
    W["tick"] = i * mr.MISTAKE_WINDOW
    far.append(mr.seen_as(obs, other, W, 9.8, 10, 0.4)["name"])
    near.append(mr.seen_as(obs, other, W, 4, 10, 0.9)["name"])
check("seen at the edge of recognition: sometimes taken for a lookalike they know (same sex, similar age)",
      0 < far.count("Sam") < 300 and "Ann" not in far, str({n: far.count(n) for n in set(far)}))
check("... never when close", set(near) == {"Bob"})
heard = [mr.heard_as(obs, other, dict(W, tick=i * mr.MISTAKE_WINDOW), 0.32)["name"] for i in range(400)]
clear = [mr.heard_as(obs, other, dict(W, tick=i * mr.MISTAKE_WINDOW), 0.9)["name"] for i in range(400)]
check("a voice only just made out: sometimes taken for someone else's; a clear one never",
      0 < heard.count("Sam") < 300 and set(clear) == {"Bob"}, str({n: heard.count(n) for n in set(heard)}))

# ---- reputation around them; watch values ----
k.update(x=rob["x"] + 1, y=rob["y"], reputation={"global": 0.8, "community": 0.6, "notoriety": 0.0})
rob.setdefault("relationships", {})["kathleen"] = {"trust": 0.7, "respect": 0.5, "friendship": 0.6}
out = dd.debug_draw("robert")
rp = [r for r in out["social"]["reputation"] if r["id"] == "kathleen"]
check("reputation of people around them: score, standing, and how they regard them",
      rp and rp[0]["global"] == 0.8 and rp[0]["standing"] == "respected" and rp[0]["their_view"]["trust"] == 0.7, str(rp)[:300])
from systems import watch_values as wv
rob.update(stress=42.5, mood={"name": "irritable"}, activity={"type": "use_toilet"})
f = wv.fields(rob, w, "@")
vals = {x["path"]: x["value"] for x in f["fields"]}
check("watch: the quick picks (mood, intention, activity, stress, next due, reputation)",
      vals["@mood"] == "irritable" and vals["@activity"] == "use toilet" and vals["@stress"] == 42.5
      and isinstance(vals["@next"], str) and isinstance(vals["@intention"], str) and "@reputation" in vals, str(vals))
g = wv.fields(rob, w)
check("... groups of every field on the character", any(x["group"] == "body" for x in g["groups"]) or len(g["groups"]) > 5, str(g["groups"][:6]))
f = wv.fields(rob, w, "posture") if any(x["group"] == "posture" for x in g["groups"]) else None
check("... a string few values across everyone is an enum, with its options",
      f is None or f["fields"][0]["type"] == "enum", str(f and f["fields"][:2]))
check("... values by path", wv.value(rob, w, "mood.name") == "irritable" and wv.value(rob, w, "stress") == 42.5)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
