"""
Feelings about someone heal with time, and a line only counts as hurtful when it is (systems/relationship_recovery.py;
live 2026-11-27: every relationship among the families "enemy", 936 of 1,149 impacts "insults" on ordinary lines).

A. Hostility / resentment / fear fade toward 0 (halving every 2 sim days).
B. Trust / friendship / respect / comfort climb back toward the resting level: the household bond for family living
   together, 0 for others; feelings above it aren't touched.
C. recover() is lazy (by sim time since last), and relabels the relationship (enemy -> not).
D. INTENT "hurt": kept for a hostile line or a heated speaker; dropped (and the insult with it) for a worried or
   friendly line -- "We need to check on the kids, I'm getting really worried."
E. repair_preview() changes nothing; repair() applies N days.

Run inside the backend container:   python tests/test_relationship_recovery.py
"""
import os, sys, copy
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import systems.relationship_recovery as R
from brain.relationships import _default_relationship
DAY = R.DAY

def rel(**kw):
    r = _default_relationship(); r.update(kw); return r

world = {"tick": 0, "characters": {}}
ant = {"id": "a", "name": "Anthony Carter", "household_id": "h", "relationships": {}}
reb = {"id": "r", "name": "Rebecca Carter", "household_id": "h", "relationships": {}}
nb = {"id": "n", "name": "Daniel Martinez", "household_id": "h2", "relationships": {}}
world["characters"] = {"a": ant, "r": reb, "n": nb}
ant["relationships"]["r"] = rel(kinship="spouse", labels=["spouse"], trust=-80, friendship=-100, respect=-100,
                                hostility=100, resentment=100, fear=20, state="enemy")
ant["relationships"]["n"] = rel(trust=-60, friendship=40, hostility=80, resentment=40)

# A / B
r = copy.deepcopy(ant["relationships"]["r"])
R.recover_relationship(ant, "r", r, world, 2 * DAY)
check("A: hostility halves in two sim days", abs(r["hostility"] - 50) < 0.5 and abs(r["resentment"] - 50) < 0.5, r)
rest = R.resting_level(ant, "r", ant["relationships"]["r"], world)
check("B: a spouse at home rests at the household bond", rest["trust"] == 70 and rest["friendship"] == 65 and rest["respect"] >= 35, rest)
R.recover_relationship(ant, "r", r, world, 30 * DAY)
check("B: ... and gets back there, hostility gone", abs(r["trust"] - 70) < 1 and r["hostility"] < 1, r)
n = copy.deepcopy(ant["relationships"]["n"])
R.recover_relationship(ant, "n", n, world, 8 * DAY)
check("B: a neighbour rests at 0 -- trust climbs back toward it (-60 -> -15 in 8 days)", abs(n["trust"] + 15) < 0.5, n)
check("B: friendship above the resting level isn't touched", n["friendship"] == 40, n)

mom = {"id": "m", "name": "Rebecca Carter", "household_id": "h", "age_group": "adult", "relationships": {}}
kid = {"id": "k", "name": "Alexander Carter", "household_id": "h", "age_group": "child", "relationships": {}}
world["characters"].update(m=mom, k=kid)
check("B: no kinship label, but an adult and a child at home -> rests as parent and child",
      R.resting_level(mom, "k", rel(), world)["trust"] == 60 and R.resting_level(kid, "m", rel(), world)["trust"] == 65)

# C
from core import clock
T = {"now": 1000.0}
clock.now_ts = lambda w: T["now"]
R.recover(ant, world)                               # stamps
T["now"] += 6 * DAY
moved = R.recover(ant, world)
check("C: recover() by the sim time since the last time", moved == 2 and ant["relationships"]["r"]["hostility"] < 20)
check("C: ... and relabels them -- no longer enemies", ant["relationships"]["r"]["state"] != "enemy", ant["relationships"]["r"]["state"])

# D
c = {"id": "a", "emotional_temperature": 40, "_conv_acts": {}}
w = {}
sp = {"utterance": "We need to check on the kids, I'm getting really worried.", "speech_act": "insult",
      "intent": {"valence": "hurt", "target_description": "Rebecca"}}
check("D: a worried line marked 'hurt' is dropped, and the insult with it", R.check_intent(c, sp, w, "r")
      and "intent" not in sp and sp["speech_act"] == "declare", sp)
sp2 = {"utterance": "You're pathetic, you never listen.", "speech_act": "insult", "intent": {"valence": "hurt"}}
check("D: a hostile line keeps it", not R.check_intent(c, sp2, w, "r") and sp2["speech_act"] == "insult")
hot = dict(c, emotional_temperature=80)
sp3 = {"utterance": "I said no.", "speech_act": "insult", "intent": {"valence": "hurt"}}
check("D: a heated speaker keeps it", not R.check_intent(hot, sp3, w, "r"))
hot2 = dict(hot, _conv_acts={"r": {"act": "compromise"}})
sp4 = {"utterance": "Fine, you choose tonight.", "speech_act": "insult", "intent": {"valence": "hurt"}}
check("D: ... but not while offering a compromise", R.check_intent(hot2, sp4, w, "r"))
check("D: counted", w["_intent_check"]["hurt_dropped"] == 2)

# E
world2 = copy.deepcopy(world)
world2["characters"]["a"]["relationships"]["r"].update(hostility=100, trust=-80)
before = copy.deepcopy(world2["characters"]["a"]["relationships"]["r"])
rows = R.repair_preview(world2, 3)
check("E: the preview changes nothing", world2["characters"]["a"]["relationships"]["r"] == before and rows
      and rows[0]["after"]["hostility"] < rows[0]["before"]["hostility"], rows[:1])
R.repair(world2, 3)
check("E: repair applies it", world2["characters"]["a"]["relationships"]["r"]["hostility"] < 40)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
