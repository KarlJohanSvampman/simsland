"""
One conversation act, picked from the situation; the AI writes the conversation inside it (systems/conversation_acts.py).

A. The situation picks the act: a grievance and a bad mood -> criticism; the same, but they look sad and you're
   empathetic -> you hold back (inquiry / praise); a parent with a misbehaving child -> discipline; adults drawn to each
   other -> flirt (never family, not when they're upset); furious with a grievance -> rage (not when calm); a shared
   hobby and a good mood -> suggest; a plan that needs them -> request; a request they turned down -> negotiate.
B. A reply follows what the other just did: criticism -> debate / compromise; request -> negotiate; flirt -> flirt.
C. choose(): the conversation partner first, then who spoke, then people close by (only if something is worth saying);
   the pick is remembered for a while.
D. The line to that person carries the act: conv_act, and the older speech act (praise -> compliment, rage -> insult).
E. The prompt says the act, the topic and how.

Run inside the backend container:   python tests/test_conversation_acts.py
"""
import os, sys, random
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import systems.conversation_acts as A
A._now = lambda world: 1000.0

def rel(**kw):
    r = {"friendship": 20, "trust": 20, "respect": 20, "hostility": 0, "resentment": 0, "attraction": 0, "chemistry": 0,
         "kinship": None, "labels": []}
    r.update(kw)
    return r

def person(cid, name, **kw):
    c = {"id": cid, "name": name, "age": 35, "age_group": "adult", "traits": [], "emotional_temperature": 35,
         "emotion": "calm", "stress": 10, "household_id": None, "hobbies": [], "active_intentions": [], "relationships": {}}
    c.update(kw)
    return c

def top(c, o, world, replying_to=None):
    sc = A.score(c, o, world, replying_to)
    return max(sc, key=lambda k: sc[k][0]), sc

W = {"tick": 0, "characters": {}, "social_issues": {}, "conversations": {}}

# A: criticism, and empathy holding it back
ant = person("a", "Anthony Carter", emotional_temperature=70, emotion="annoyed", stress=60,
             grievances=[{"caused_by": "r", "event_type": "left_mess", "weight": 14}])
reb = person("r", "Rebecca Carter", emotion="calm")
ant["relationships"]["r"] = rel()
act, sc = top(ant, reb, W)
check("A: a grievance and a bad mood -> criticism, about the grievance", act == "criticism" and "mess" in sc["criticism"][1], (act, sc["criticism"]))
kind = dict(ant, traits=["empathetic", "compassionate"], emotional_temperature=50, emotion="calm")
sad = dict(reb, emotion="sad")
act, sc = top(kind, sad, W)
check("A: ... but she looks sad and he's empathetic -> he holds back (inquiry / praise)", act in ("inquiry", "praise"), (act, {k: v[0] for k, v in sc.items()}))
check("A: ... the inquiry is about how she's doing", "seem sad" in sc["inquiry"][1], sc["inquiry"])

# discipline
dad = person("d", "Patrick Moore", traits=["disciplined"], emotional_temperature=55, household_id="h",
             grievances=[{"caused_by": "k", "event_type": "loud_at_night", "weight": 10}])
kid = person("k", "Alexander Carter", age=12, age_group="child", household_id="h")
dad["relationships"]["k"] = rel(kinship="parent")
act, sc = top(dad, kid, W)
check("A: a parent with a misbehaving child -> discipline", act == "discipline", (act, {k: v[0] for k, v in sc.items()}))

# flirt
m = person("m", "Daniel Martinez", traits=["flirtatious"], emotion="cheerful", hobbies=["salsa"])
f = person("f", "Margaret Moore", emotion="content", hobbies=["salsa"])
m["relationships"]["f"] = rel(attraction=70)
act, sc = top(m, f, W)
check("A: adults drawn to each other -> flirt (shared hobby as the opening)", act == "flirt" and "salsa" in sc["flirt"][1], (act, sc.get("flirt")))
m2 = dict(m, relationships={"f": rel(attraction=70, kinship="sibling")})
check("A: never with family", "flirt" not in A.score(m2, f, W))
act, _ = top(m, dict(f, emotion="sad"), W)
check("A: not when they're upset", act != "flirt", act)

# rage
hot = person("h", "Rebecca Carter", traits=["hot_tempered"], emotional_temperature=95, emotion="furious",
             grievances=[{"caused_by": "a", "event_type": "insulted", "weight": 20}])
hot["relationships"]["a"] = rel(hostility=60, resentment=60, friendship=-30, trust=-30)
act, sc = top(hot, ant, W)
check("A: furious with a grievance -> rage", act == "rage", (act, {k: v[0] for k, v in sc.items()}))
calm = dict(hot, emotional_temperature=40, emotion="calm")
check("A: no rage when calm", "rage" not in A.score(calm, ant, W))

# suggest
p1 = person("p", "Pamela Martinez", emotion="cheerful", hobbies=["chess", "hiking"])
p2 = person("q", "Rachel Martinez", emotion="content", hobbies=["chess"])
p1["relationships"]["q"] = rel(friendship=60, trust=60)
act, sc = top(p1, p2, W)
check("A: a shared hobby and a good mood -> suggest it", act == "suggest" and "chess" in sc["suggest"][1], (act, sc["suggest"]))

# request
mom = person("mo", "Rachel Martinez", stress=50, active_intentions=[{"type": "pick_up_kid", "target_id": "da", "reason": "pick up Pamela from school"}])
da = person("da", "Daniel Martinez")
mom["relationships"]["da"] = rel(friendship=50, trust=50)
act, sc = top(mom, da, W)
check("A: a plan that needs them -> request", act == "request" and "Pamela" in sc["request"][1], (act, sc.get("request")))

# negotiate
W2 = dict(W, cpl_requests={"x": {"from": "mo", "to": "da", "status": "rejected", "summary": "taking the car tonight"}})
act, sc = top(person("mo", "Rachel Martinez", relationships={"da": rel()}), da, W2)
check("A: a request they turned down -> negotiate", act == "negotiate" and "car" in sc["negotiate"][1], (act, sc.get("negotiate")))

# B: replies
act, _ = top(person("x", "Chris", relationships={"y": rel()}), person("y", "Yan"), W, replying_to="criticism")
check("B: criticised -> debate or compromise", act in ("debate", "compromise"), act)
act, _ = top(person("x", "Chris", relationships={"y": rel()}), person("y", "Yan"), W, replying_to="request")
check("B: asked for something -> negotiate", act == "negotiate", act)
act, _ = top(dict(m), f, W, replying_to="flirt")
check("B: flirted with, and drawn to them -> flirt back", act == "flirt", act)

# C: choose
w = {"tick": 0, "social_issues": {}, "characters": {}, "conversations": {}}
c1 = person("c1", "Anthony Carter", emotional_temperature=70, emotion="annoyed",
            grievances=[{"caused_by": "c2", "event_type": "left_mess", "weight": 14}],
            perception={"visible_people": [{"id": "c3", "distance": 2}, {"id": "c2", "distance": 4}]})
c2 = person("c2", "Rebecca Carter"); c3 = person("c3", "Pamela Martinez")
c1["relationships"] = {"c2": rel(), "c3": rel(friendship=0, trust=0, respect=0)}
w["characters"] = {"c1": c1, "c2": c2, "c3": c3}
w["conversations"] = {"cv": {"active": True, "participants": ["c1", "c2"],
                             "history": [{"speaker": "c2", "utterance": "Why are you always on my case?", "conv_act": "criticism"}]}}
picks = A.choose(c1, w)
check("C: the conversation partner first, answering what she did", picks and picks[0]["with"] == "c2" and picks[0]["replying_to"] == "criticism", picks)
check("C: nobody close by gets an act unless something is worth saying", all(p["with"] != "c3" for p in picks) or
      any(p["with"] == "c3" and p["score"] >= A.MIN_UNPROMPTED for p in picks))
check("C: the pick is remembered", c1["_conv_acts"]["c2"]["act"] == picks[0]["act"])

# D: stamping the line
sp = {"utterance": "Fine, then let's split it.", "speech_act": "declare", "target": None}
c1["_conv_acts"]["c2"] = {"act": "praise", "topic": "the dinner", "ts": 1000.0}
check("D: the line carries the act", A.stamp_speech(c1, sp, w, "c2") == "praise" and sp["conv_act"] == "praise"
      and sp["speech_act"] == "compliment" and sp["topic"] == "the dinner", sp)
sp2 = {"utterance": "x", "speech_act": "insult"}
A.stamp_speech(c1, sp2, w, "c2")
check("D: a speech act already decided (an INTENT) is kept", sp2["speech_act"] == "insult")
c1["_conv_acts"]["c2"]["ts"] = 1000.0 - A.ACT_TTL_S - 1
check("D: an old pick doesn't stamp", A.stamp_speech(c1, {"utterance": "x", "speech_act": "declare"}, w, "c2") is None)

# E: the prompt
lines = A.prompt_lines(c1, w)
check("E: the prompt says who did what, the act, the topic, how", lines and lines[0].startswith("Rebecca criticised you. Answer what Rebecca said")
      and any(lbl in lines[0] for lbl in A.LABEL.values()) and lines[-1].startswith("Write what you say"), lines)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
