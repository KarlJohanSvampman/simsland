"""
Checking in, and remembering what you talk about with each person (systems/catch_up.py).

A. A check-in is due with someone you know the first time you see them on a new day, or after a few hours apart --
   not with strangers, not again right after talking.
B. It makes the act a check-in INQUIRY: how they're doing, plans / yesterday / the weekend by the day and hour, and news
   on an earlier topic.
C. Topic memory: topics from a finished conversation (the AI's subject and tags) and from each act are kept per person,
   newest last, capped; the same topic again refreshes it.
D. The topic to ask about: talked about a while ago, plans first, not asked about again right away.
E. A delivered line: both have talked now (no check-in), the topic is remembered on both sides.
F. The prompt lists what they've talked about before.

Run inside the backend container:   python tests/test_catch_up.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import core.clock as clock
T = {"now": 100 * 86400 + 9 * 3600}              # day 100, 09:00
clock.now_ts = lambda world: T["now"]
import systems.catch_up as C
import systems.conversation_acts as A
A._now = lambda world: T["now"]

def person(cid, name, **kw):
    c = {"id": cid, "name": name, "age": 35, "age_group": "adult", "traits": [], "emotional_temperature": 35,
         "emotion": "calm", "stress": 10, "household_id": "h", "hobbies": [], "active_intentions": [], "relationships": {}}
    c.update(kw)
    return c

world = {"tick": 0, "calendar": {"weekday": "Tuesday", "hour": 9}, "characters": {}, "conversations": {}, "social_issues": {}}
ant = person("a", "Anthony Carter"); reb = person("r", "Rebecca Carter")
stranger = person("s", "Sam Stranger", household_id="other")
ant["relationships"] = {"r": {"kinship": "spouse", "friendship": 40, "trust": 40, "respect": 30}, "s": {"familiarity": 2}}
world["characters"] = {"a": ant, "r": reb, "s": stranger}

# A
check("A: never talked today -> due", C.checkin_due(ant, reb, world) == "first time today")
check("A: not with a stranger", C.checkin_due(ant, stranger, world) is None)
C.note_talk(ant, "r", world)
T["now"] += 3600
check("A: not again an hour after talking", C.checkin_due(ant, reb, world) is None)
T["now"] += 4 * 3600
check("A: after a few hours apart -> due", C.checkin_due(ant, reb, world) == "a few hours since you last talked")
T["now"] += 86400
check("A: a new day -> due", C.checkin_due(ant, reb, world) == "first time today")

# C
C.on_conversation_read(world, {"participants": ["a", "r"], "subject": "Alexander's school trip", "topic_tags": ["school", "money"]})
check("C: subject and tags kept for both", C.recent_topics(ant, "r") == ["money", "school", "Alexander's school trip"]
      and "school" in C.recent_topics(reb, "a"), (C.recent_topics(ant, "r"), C.recent_topics(reb, "a")))
C.note_topic(ant, "r", "school", world)
check("C: the same topic again moves to the front", C.recent_topics(ant, "r")[0] == "school"
      and [e for e in ant["talk_topics"]["r"] if e["topic"] == "school"][0]["times"] == 2)
check("C: generic topics aren't kept", C.note_topic(ant, "r", "general", world) is None)
for i in range(30):
    C.note_topic(ant, "s", f"topic {i}", world)
check("C: capped per person", len(ant["talk_topics"]["s"]) == C.TOPICS_KEPT)

# D
T["now"] += 13 * 3600
t = C.update_topic(ant, "r", world, mark=True)
check("D: a while later, plans / events first (not 'money')", t in ("school", "Alexander's school trip"), t)
check("D: not asked about again right away", C.update_topic(ant, "r", world) != t)

# B
world["calendar"] = {"weekday": "Friday", "hour": 18}
T["now"] += 2 * 86400
sc = A.score(ant, reb, world)
best = max(sc, key=lambda k: sc[k][0])
check("B: a due check-in makes it an inquiry", best == "inquiry" and sc["inquiry"][1].startswith("checking in"), (best, sc["inquiry"]))
check("B: ... on a Friday evening, about the weekend", "this weekend" in sc["inquiry"][1], sc["inquiry"][1])
world["calendar"] = {"weekday": "Wednesday", "hour": 8}
check("B: ... on a weekday morning, about yesterday and today", "yesterday" in C.checkin_topic(ant, reb, world))

# E
C.on_line(world, ant, reb, topic="the broken dishwasher", act="request")
check("E: both have talked now -- no check-in", C.checkin_due(ant, reb, world) is None and C.checkin_due(reb, ant, world) is None)
check("E: the act's topic remembered on both sides", C.recent_topics(ant, "r")[0] == "the broken dishwasher"
      and C.recent_topics(reb, "a")[0] == "the broken dishwasher")

# F
T["now"] += 86400
world["conversations"] = {"cv": {"active": True, "participants": ["a", "r"], "history": []}}
lines = A.prompt_lines(ant, world)
check("F: the prompt lists what they've talked about before",
      any(l.startswith("What you've talked about with Rebecca before: the broken dishwasher") for l in lines), lines)
check("F: and it's a check-in", any("checking in" in l for l in lines), lines)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
