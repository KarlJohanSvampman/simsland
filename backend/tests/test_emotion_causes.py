"""
Moods that come and go, and what they're about (live 2026-11-27: every character at temperature 100, "furious" --
26 likes and comments a day each added 3 degrees, and nothing ever cooled them down).

A. The temperature relaxes toward a calm baseline with sim time (halving its distance every 45 min); stress and sleep
   debt raise the baseline; the active mood's range always holds.
B. Being appreciated (a like, a comment) soothes instead of heating.
C. Every push records why; causes() ranks them, recent ones weighing most; explain() says it in words.
D. A grievance and a provocation heat them up, with who and what as the cause; unmet needs and a text say which.
E. update_emotion relaxes and relabels: furious at 100 is calm a few hours later.
F. Their prompt says what they're worked up about.

Run inside the backend container:   python tests/test_emotion_causes.py
"""
import os, sys, types
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from brain import emotion as E
import core.clock as clock

T = {"now": 1_000_000.0}
clock.now_ts = lambda world: T["now"]
world = {"tick": 0, "characters": {}, "definitions": {"mood_templates": {}}}

def person(**kw):
    c = {"id": "a", "name": "Anthony Carter", "emotional_temperature": 100.0, "stress": 0, "body": {"sleep_debt": 0}}
    c.update(kw)
    world["characters"][c["id"]] = c
    return c

# A
c = person()
E.relax(c, world)                                  # first call just stamps the time
T["now"] += 45 * 60; E.relax(c, world)
check("A: halfway to the baseline after 45 sim minutes", abs(c["emotional_temperature"] - (30 + 70 * 0.5)) < 0.1, c["emotional_temperature"])
T["now"] += 6 * 3600; E.relax(c, world)
check("A: ... and settled at the baseline hours later", abs(c["emotional_temperature"] - 30) < 0.5, c["emotional_temperature"])
check("A: stress and sleep debt raise the baseline", E.baseline({"stress": 80, "body": {"sleep_debt": 65}}) == 30 + 20 + 10)
c2 = person(id="b", emotional_temperature=100.0, mood={"name": "Content", "emotional_temperature_range": [0, 35]})
E.relax(c2, world)
check("A: the mood's range holds (Content: at most 35)", c2["emotional_temperature"] <= 35, c2["emotional_temperature"])

# B
import systems.validation as V
c3 = person(id="v", emotional_temperature=60.0)
try:
    V.receive_validation(c3, world, source="like")
except Exception as exc:                          # side systems (popularity, needs) may want more world
    print("   (receive_validation side effect:", repr(exc), ")")
check("B: a like soothes instead of heating", c3["emotional_temperature"] < 60, c3["emotional_temperature"])

# C
c4 = person(id="c", emotional_temperature=40.0)
E.nudge(c4, 15, "Rebecca: shouting at you", world)
T["now"] += 4 * 3600
E.nudge(c4, 10, "unmet needs: exercise", world)
E.nudge(c4, 6, "Rebecca: shouting at you", world)
found = E.causes(c4, world)
check("C: recorded with why", [e["why"] for e in c4["emotion_causes"]] == ["Rebecca: shouting at you", "unmet needs: exercise", "Rebecca: shouting at you"])
check("C: ranked, recent pushes weighing most", [w for w, _ in found] == ["unmet needs: exercise", "Rebecca: shouting at you"], found)
check("C: explained in words", E.explain(c4, world) == "unmet needs: exercise; Rebecca: shouting at you", E.explain(c4, world))
check("C: soothing isn't a cause", all(w for w, _ in E.causes(c3, world)) and not any("appreciated" in w for w, _ in E.causes(c3, world)))
c4["mood"] = {"name": "Furious", "emotional_temperature_range": [80, 100]}
check("C: an angry mood is named first", E.causes(c4, world)[0][0] == "in a furious mood")

# D
import systems.grievances as G
G.sync_social_decay = lambda *a, **k: None
G._wake_for_next_check = lambda *a, **k: None
G._to_issue = lambda *a, **k: None
import systems.mentality as M
M.principle_stance_toward = lambda *a, **k: None
reb = person(id="r", name="Rebecca Carter", emotional_temperature=30.0)
ant = person(id="a2", name="Anthony Carter", emotional_temperature=30.0)
G.add_grievance(ant, "r", "insult", world)
check("D: a grievance heats them, the cause says who and what", ant["emotional_temperature"] > 30
      and ant["emotion_causes"][-1]["why"].startswith("Rebecca:"), ant.get("emotion_causes"))
import systems.target_reactions as TR
TR.sample_reaction = lambda target, kind: ("anger", {"anger": 1.0})
import brain.cognition_scheduler as cs
cs.wake_character = lambda *a, **k: None
before = reb["emotional_temperature"]
TR.flag_provocation(reb, world, ant, list(TR._VERB_PHRASE)[0])
check("D: being provoked heats them, with who did what", reb["emotional_temperature"] > before
      and reb["emotion_causes"][-1]["why"].startswith("Anthony "), reb.get("emotion_causes"))
import systems.lt_needs as LT
pat = person(id="p", emotional_temperature=30.0, lt_needs={"exercise": {"frustration": 0.9}, "nature": {"frustration": 0.7}, "play": {"frustration": 0.1}})
LT._apply_lt_frustration(pat, 0.8)
check("D: unmet needs say which", pat["emotion_causes"][-1]["why"] == "unmet needs: exercise, nature", pat.get("emotion_causes"))
import systems.sms_emotion as SMS
SMS.apply_sms_emotion(pat, {"id": "r", "name": "Rebecca Carter"}, "you idiot")
check("D: a text says from whom", "text from Rebecca" in pat["emotion_causes"][-1]["why"], pat["emotion_causes"][-1])

# E
d = person(id="d", emotional_temperature=100.0)
E.update_emotion(d, world)
check("E: furious at 100", d["emotion"] == "furious")
T["now"] += 4 * 3600
E.update_emotion(d, world)
check("E: calm a few hours later", d["emotion"] in ("calm", "content"), (d["emotion"], d["emotional_temperature"]))

# F
import brain.context_builder as CB
f = person(id="f", emotional_temperature=92.0, emotion="furious", traits=[], age_group="adult")
E.nudge(f, 5, "Rebecca: shouting at you", world)
f["emotional_temperature"] = 92.0
try:
    text = CB._sec_identity(f, world) or ""
except Exception as exc:
    text = f"(section failed: {exc!r})"
check("F: the prompt says what they're worked up about", "Right now you feel furious -- Rebecca: shouting at you." in text, text[-300:])

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
