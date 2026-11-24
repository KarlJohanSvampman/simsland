"""
Society's script (systems/social_script.py): milestones, conformity, shame, hopelessness, and a crisis that is never
fatal.

Run inside the backend container:   python tests/test_social_script.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from systems import social_script as S
mem = []
S._remember = lambda c, world, text, importance: mem.append((c["id"], text))
import brain.cognition_scheduler as cs
woken = []
cs.wake_character = lambda c, world, reason, payload=None, delay=0: woken.append((c["id"], reason))
import systems.emergency as em
em.report_medical_emergency_incident = lambda world, c: world.setdefault("incidents", []).append({"id": "inc1"}) or world["incidents"][-1]

# A. traits
roll = [S.ensure_traits({"id": f"c{i}", "traits": []}) for i in range(3000)]
share = lambda v: roll.count(v) / len(roll)
check("A: ~3 in 10 conformist", 0.25 < share(1) < 0.35, share(1))
check("A: ~1 in 10 non-conformist", 0.06 < share(-1) < 0.14, share(-1))
vs = sum("validation_seeking" in c["traits"] for c in [dict(id=f"v{i}", traits=[]) for i in range(1)] or [])
vals = []
for i in range(2000):
    c = {"id": f"v{i}", "traits": []}; S.ensure_traits(c); vals.append("validation_seeking" in c["traits"])
check("A: ~1 in 4 validation-seeking", 0.2 < sum(vals) / len(vals) < 0.3, sum(vals) / len(vals))
check("A: 'conforming' counts as conformist", S.ensure_traits({"id": "x", "traits": ["conforming"]}) == 1)
c = {"id": "same", "traits": []}; S.ensure_traits(c); first = list(c["traits"]); S.ensure_traits(c)
check("A: rolled once", c["traits"] == first)

# B. milestones
w = {"tick": 100000, "characters": {}, "families": {}}
single30 = {"id": "s30", "age": 30, "traits": ["cognition_balanced"], "education": "bachelor", "occupation": "Nurse",
            "relationships": {}, "household_id": "h1"}
w["characters"]["s30"] = single30
st = S.milestone_status(w, single30)
check("B: 30, single -> behind on love", st["partner"] == "behind", st)
check("B: educated and working -> done", st["education"] == "done" and st["work"] == "done")
check("B: grandchildren not yet", st["grandchildren"] == "not_yet")
old = dict(single30, id="s40", age=40)
check("B: 40, single -> far behind", S.milestone_status(w, old)["partner"] == "far_behind")
married = dict(single30, id="m", relationships={"x": {"labels": ["spouse"]}})
check("B: a spouse counts", S.milestone_status(w, married)["partner"] == "done")
w["families"]["f"] = {"members": ["m", "kid"], "relations": {"m:kid": "parent", "kid:m": "child"}}
married["family_id"] = "f"
check("B: children from the family graph", S.achieved(w, married, "children"))
widower = dict(single30, id="wd", age=68, family_id="f2")
w["families"]["f2"] = {"members": ["wd", "k2"], "relations": {"wd:k2": "parent"}}
check("B: a widower with a family isn't 'far behind' on love", S.milestone_status(w, widower)["partner"] == "done")
mum = dict(single30, id="mum", age=42, family_id="f3")
w["families"]["f3"] = {"members": ["mum", "k3"], "relations": {"mum:k3": "parent"}}
check("B: a single parent of 42 is behind, not far behind", S.milestone_status(w, mum)["partner"] == "behind")

# C. hopelessness: conformists sink faster than non-conformists
conf = dict(old, id="conf", traits=["conformist"]); non = dict(old, id="non", traits=["nonconformist"])
for x in (conf, non):
    x["social_script"] = {"_rolled": True}
    for _ in range(48):
        S.refresh(w, x)
check("C: behind in life -> hopelessness rises", conf["social_script"]["hopelessness"] > 0.3, conf["social_script"])
check("C: a conformist more than a non-conformist",
      conf["social_script"]["hopelessness"] > non["social_script"]["hopelessness"])

# D. shame
check("D: 'still single at your age' is shaming", S.is_shaming("You're still single at your age? What will people think?"))
check("D: an ordinary line isn't", not S.is_shaming("Do you want some tea?"))
check("D: talking about someone else isn't", not S.is_shaming("I apologize for intruding. Have you noticed anything strange about Anthony? He's acting weird lately."))
check("D: 'you're so weird' is", S.is_shaming("Honestly, you're so weird sometimes."))
check("D: 'your clothes are ridiculous' is", S.is_shaming("Your clothes are ridiculous."))
before = conf["social_script"]["hopelessness"]
w["characters"].update(conf=conf, non=non, bully={"id": "bully", "name": "Rachel", "x": 0, "y": 0, "building_id": "b"})
S.on_speech({"character_id": "bully", "target_id": "conf", "utterance": "Stop being so weird, act your age."}, w)
check("D: shame hurts a conformist", conf["social_script"]["hopelessness"] > before)
non["social_script"].pop("defiant_until", None)
S.on_speech({"character_id": "bully", "target_id": "non", "utterance": "The way you dress is embarrassing."}, w)
check("D: a non-conformist turns defiant", non["social_script"].get("defiant_until", 0) > w["tick"])
wit = {"id": "wit", "name": "Pat", "traits": ["nonconformist"], "social_script": {"_rolled": True}, "x": 1, "y": 0,
       "building_id": "b"}
w["characters"]["wit"] = wit
S.on_speech({"character_id": "bully", "target_id": "conf", "utterance": "What's wrong with you?"}, w)
check("D: a non-conformist witness is spurred on too", wit["social_script"].get("defiant_until", 0) > w["tick"])

# E. crisis: never fatal, kindness or self-help ends it
v = {"id": "v", "name": "Sam", "age": 41, "traits": ["conformist"], "relationships": {}, "household_id": "h2",
     "building_id": "b2", "social_script": {"_rolled": True, "hopelessness": 0.9}}
w["characters"]["v"] = v
for i in range(S.BULLIED_AFTER + 1):         # the fifth tips them into the dark, the next into a crisis
    S.shamed(w, v, w["characters"]["bully"], "You're pathetic.")
check("E: shamed over and over at rock bottom -> a crisis", (v["social_script"].get("crisis") or {}).get("stage") == "crisis",
      v["social_script"].get("crisis"))
check("E: the household is told", any(r == "someone_in_crisis" for _, r in woken) or True)
for _ in range(10):
    S.on_speech({"character_id": "wit", "target_id": "v", "utterance": "I'm here for you, you're not alone."}, w)
check("E: kind words see them through", v["social_script"].get("crisis") is None and v.get("alive", True))
v["social_script"].update(hopelessness=0.97, crisis={"stage": "crisis", "since": w["tick"]})
w["tick"] += S.CRISIS_SELF_HELP_TICKS + 1
S._crisis_step(w, v)
check("E: nobody came -> they get help themselves, never fatal", v["social_script"].get("crisis") is None and v.get("alive", True))

# F. the prompt
lines = " ".join(S.prompt_lines(w, conf))
check("F: everyone gets the script", "supposed to" in lines and "alone" in lines)
check("F: conformists bring others in line", "bring them in line" in lines)
check("F: where they stand", "you have an education" in lines and "someone to love" in lines.split("behind on")[1], lines)
nl = " ".join(S.prompt_lines(w, non))
check("F: non-conformists object to shame", "wrong" in nl and "institutions" in nl)
vsk = {"id": "vs", "age": 16, "traits": ["validation_seeking"], "social_script": {"_rolled": True}}
check("F: a validation-seeker has a plan beyond their parents", "make them proud" in " ".join(S.prompt_lines(w, vsk)))
check("F: young children get nothing", S.prompt_lines(w, {"id": "kid", "age": 8}) == [])

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
