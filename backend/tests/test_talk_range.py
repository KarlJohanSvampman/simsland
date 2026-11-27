"""
Talking needs the same room and talking distance; further away or from another room it takes a yell
(systems/conversation_reach.py, cpl/participants.py::earshot, systems/action_router.py; the user, 2026-11-27).

A. Same room, within TALK_RANGE_TILES: heard at a normal voice.
B. Same room, further: not heard at a normal voice ("too far to talk normally"); a yell reaches -- if it carries.
C. Another room: not heard at a normal voice; a yell reaches if it carries through the walls.
D. "YELL:" at the start of a line raises the voice and is taken off the words.
E. The conversation acts: only people within talking range nearby; a partner out of range -> "go over, or yell".

Run inside the backend container:   python tests/test_talk_range.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import brain.perception as P
import systems.room_assignment as RA
ROOMS = {}
RA.room_at = lambda world, x, y: ROOMS.get("default") if x < 10 else ROOMS.get("east")
P.los_trace = lambda a, b, w: {"ok": True, "hit": None, "by": None}
MUFFLE = {"v": 1.0}
P.sound_modifier = lambda listener, speaker, volume: MUFFLE["v"]
import systems.conversation_reach as CR
from cpl import participants as PP

def at(x, y, cid="x"):
    return {"id": cid, "name": cid.title(), "x": x, "y": y, "senses": {}}

world = {"tick": 0}
ROOMS.update(default="kitchen", east="kitchen")
a, b = at(1, 1, "anthony"), at(4, 1, "rebecca")
heard, r = PP.earshot(world, a, b, "medium")
check("A: same room, 3 tiles: heard normally", heard and r["talking_range"], r)

b = at(8, 1, "rebecca")
heard, r = PP.earshot(world, a, b, "medium")
check("B: same room, 7 tiles: not at a normal voice -- 'too far to talk normally'", not heard and "too far to talk normally" in r["why_not"], r)
heard, r = PP.earshot(world, a, b, "high")
check("B: ... a yell reaches", heard, r)
far = at(9.5, 13, "rebecca")
heard, r = PP.earshot(world, a, far, "high")
check("B: ... but not beyond what a yell carries", not heard and r["why_not"] == "further than a yell carries", r)

ROOMS.update(default="kitchen", east="living room")
a, b = at(8, 1, "anthony"), at(11, 1, "rebecca")
heard, r = PP.earshot(world, a, b, "medium")
check("C: another room, 3 tiles: not heard normally -- 'in another room'", not heard and r["why_not"] == "in another room", r)
heard, r = PP.earshot(world, a, b, "high")
check("C: ... a yell reaches", heard, r)
MUFFLE["v"] = 0.2                                  # thick walls
heard, r = PP.earshot(world, at(2, 1, "a"), at(11, 1, "r"), "high")
check("C: ... unless the walls stop it", not heard, r)
MUFFLE["v"] = 1.0

# D: YELL: prefix
import re
src = open("systems/action_router.py").read()
m = re.search(r'_yell = re\.match\(r"(.+?)", utterance', src)
pat = re.compile(m.group(1).replace("\\\\", "\\"), re.I) if m else None
check("D: 'YELL:' at the start is recognised and taken off", pat and pat.match("YELL: Dinner's ready!")
      and "Dinner's ready!" == "YELL: Dinner's ready!"[pat.match("YELL: Dinner's ready!").end():].strip())
check("D: ... and raises the voice to a yell", 'volume = "high"' in src.split("_yell = re.match", 1)[1][:400])

# E: conversation acts
import systems.conversation_acts as A
A._now = lambda w: 0.0
ROOMS.update(default="kitchen", east="living room")
me = at(2, 1, "anthony"); me.update(perception={"visible_people": [{"id": "rebecca", "distance": 9}, {"id": "kid", "distance": 2}]},
                                    relationships={}, traits=[], emotion="calm", emotional_temperature=35)
reb, kid = at(11, 1, "rebecca"), at(3, 1, "kid")
w2 = {"tick": 0, "characters": {"anthony": me, "rebecca": reb, "kid": kid}, "conversations": {}}
ps = [p[0]["id"] for p in A.partners(me, w2)]
check("E: only people within talking range count as nearby", ps == ["kid"], ps)
w2["conversations"] = {"cv": {"active": True, "participants": ["anthony", "rebecca"], "history": [{"speaker": "rebecca", "utterance": "Can you come here?", "conv_act": "request"}]}}
lines = A.prompt_lines(me, w2)
check("E: a partner in another room -> go over, or yell", any("Rebecca is in another room -- not close enough to talk normally" in l and "YELL:" in l for l in lines), lines)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
