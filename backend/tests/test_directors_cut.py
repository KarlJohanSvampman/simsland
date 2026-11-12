"""
Director Mode: STOP (time stops, everyone near the director noted) and Director's Cut (change the choice and why;
key -> value changes to traits / quirks / ... and free facts; kept as a rule; undo) -- systems/directors_cut.py,
api/directors_cut.py.

Run inside the backend container:   python tests/test_directors_cut.py
"""
import contextlib
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
import systems.directors_cut as dc

w = make_world()
w["tick"] = 2000
ensure_world_defaults(w)
rob, kath = w["characters"]["robert"], w["characters"]["kathleen"]
rob.update(traits=["stubborn", "polite"], speech_quirks=["says 'indeed'"], activity={"type": "watch_tv"})
kath.update(x=rob["x"] + 3, y=rob["y"])
far = next((c for c in w["characters"].values() if c is not rob and c is not kath and c.get("x") is not None), None)
if far:
    far.update(x=rob["x"] + 50, y=rob["y"] + 50)

st = dc.stop_time(w, rob["x"] + 1, rob["y"], 5)
check("STOP: time is stopped; those within the radius are noted, others not",
      dc.is_stopped(w) and {"robert", "kathleen"} <= set(st["char_ids"]) and (far is None or far["id"] not in st["char_ids"]), str(st))
check("... nobody was interrupted", (rob.get("activity") or {}).get("type") == "watch_tv")
dc.resume_time(w)
check("Action!: time runs again (and remembers the last stop)", not dc.is_stopped(w) and w["director_stop"]["last"]["char_ids"])

# main.py skips the tick while stopped
src = open("main.py").read()
check("main.py skips ticks while stopped", "if not is_stopped(world):" in src)

cut = dc.apply_cut(rob, w, instead="go and apologise to Kathleen", why="he can't stand leaving an argument open",
                   changes=[{"area": "trait", "action": "replace", "old": "stubborn", "value": "conciliatory"},
                            {"area": "quirk", "action": "remove", "value": "says 'indeed'"},
                            {"area": "preference", "key": "food", "action": "set", "value": "loves spicy food, hates sweets"},
                            {"area": "ideal_partner", "key": "", "action": "set", "value": "someone who laughs at his jokes"},
                            {"area": "social_pressure", "key": "parents", "action": "set", "value": "still wants his father's approval"}],
                   keep_as_rule=True)
check("traits: replace one", rob["traits"] == ["conciliatory", "polite"], str(rob["traits"]))
check("... logged as a trait change, saying why", any("director's cut" in str(e.get("why")) for e in rob.get("trait_log") or []), str(rob.get("trait_log"))[:200])
check("speech quirks: remove one", rob["speech_quirks"] == [])
check("free facts by area and key", rob["character_facts"]["preference"]["food"].startswith("loves spicy")
      and rob["character_facts"]["ideal_partner"]["general"].startswith("someone who laughs"))
lines = dc.prompt_lines(rob)
check("... in their prompt", lines and "Preference (food): loves spicy food" in lines[0] and "Ideal partner: someone" in lines[0]
      and "Bound by expectations (parents / society) (parents)" in lines[0], str(lines))
check("the changed choice: they stop what they're doing and are woken with it",
      (rob.get("cognition") or {}).get("wake_reason") == "directors_cut" and rob["cognition"]["wake_payload"]["instead"].startswith("go and apologise"))
from brain.cognition_scheduler import wake_line
check("... worded for them", wake_line(rob) == "On second thought, you'll go and apologise to Kathleen instead -- that's more like you: he can't stand leaving an argument open", wake_line(rob))
from systems.personal_rules import rules, prompt_lines as rule_lines
check("'why' kept as an approved personal rule", any(r["text"].startswith("he can't stand") for r in rules(rob, "approved")))
check("the cut is recorded with what each change replaced", rob["directors_cuts"][-1]["changes"][0]["before"] == ["stubborn", "polite"])

dc.undo_cut(rob, w, cut["id"])
check("undo: traits, quirks and facts back as they were; the rule retired",
      rob["traits"] == ["stubborn", "polite"] and rob["speech_quirks"] == ["says 'indeed'"] and not rob.get("character_facts")
      and not rules(rob, "approved") and rob["directors_cuts"][-1]["undone"], str((rob["traits"], rob.get("character_facts"))))
try:
    dc.apply_cut(rob, w); bad = False
except ValueError:
    bad = True
check("an empty cut is refused", bad)

import api.directors_cut as ad
ad.load_world = lambda sim_id="default": w
ad.world_lock = contextlib.nullcontext
ad._save = lambda sim_id, world, cids=(): None
out = ad.stop(ad.StopIn(x=rob["x"], y=rob["y"], radius=4))
check("POST /director/stop", out["active"] and "robert" in out["char_ids"])
check("GET /director/stop", ad.get_stop()["active"])
v = ad.cut("robert", ad.CutIn(changes=[{"area": "hobby", "key": "weekends", "action": "set", "value": "fishing"}]))
check("POST /director/cut: applied, view returned", v["ok"] and v["facts"]["hobby"]["weekends"] == "fishing" and v["stopped"])
v = ad.get_cut("robert")
check("GET /director/cut: areas, lists, facts, last choice, past cuts", len(v["areas"]) > 15 and v["lists"]["trait"] and v["cuts"]
      and "last_choice" in v)
v = ad.undo("robert", v["cuts"][0]["id"])
check("POST undo", "hobby" not in v["facts"])
ad.resume()
check("POST /director/resume", not dc.is_stopped(w))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
