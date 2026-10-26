"""
Vision levels (Normal, Exceptional, Impaired, Blind), glasses, the settings, and what a character can make out
(systems/vision.py, brain/perception.py, systems/impulse.py::within_reach).

Run inside the backend container:   python tests/test_vision.py
"""

import os
import random
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from brain import perception as pc
from db import load_definitions
from systems import impulse
from systems import vision as vs
from systems.character_gen import generate_character
from systems.vision import Vision

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def world(hour=12, **settings):
    w = {"tick": 1000, "calendar": {"hour": hour, "minute": 0}, "characters": {}, "definitions": {}}
    if settings:
        vs.set_settings(w, settings)
    return w


def person(cid="a", x=0, y=0, **extra):
    d = {"id": cid, "name": cid.title(), "x": x, "y": y, "age": 30, "sex": "male", "relationships": {}, "alive": True}
    d.update(extra)
    return d


# ---- the levels -------------------------------------------------------------------------------------------------------------------
check("four levels", Vision.ALL == ("normal", "exceptional", "impaired", "blind") and Vision.NORMAL == "normal" and Vision.BLIND == "blind")
check("blind is never generated", Vision.BLIND not in Vision.GENERATED)

# ---- settings ----------------------------------------------------------------------------------------------------------------------
w = world()
s = vs.settings(w)
check("defaults: normal < exceptional, impaired much shorter, detection twice", s["impaired_m"] < s["normal_m"] < s["exceptional_m"] and s["detect_factor"] == 2.0)
now = vs.set_settings(w, {"normal_m": 30, "impaired_m": 5})
check("settings are set in metres and kept on the world", now["normal_m"] == 30 and w["settings"]["vision"]["impaired_m"] == 5 and vs.settings(w)["exceptional_m"] == s["exceptional_m"])
for bad, why in (({"normal_m": -1}, "negative"), ({"normal_m": "far"}, "not a number"), ({"colour": 3}, "unknown"), ({"detect_factor": 0.5}, "below 1"), ({"tile_meters": 0}, "zero")):
    try:
        vs.set_settings(w, bad)
        check(f"a {why} value is refused", False)
    except ValueError:
        check(f"a {why} value is refused", True)
check("and leaves what was set", vs.settings(w)["normal_m"] == 30)

# ---- ranges --------------------------------------------------------------------------------------------------------------------------
w = world(normal_m=20, exceptional_m=40, impaired_m=6)
outdoors = lambda lvl, **kw: person(vision=lvl, **kw)
check("recognition distance by level, outdoors by day", [vs.recognize_tiles(outdoors(l), w) for l in (Vision.NORMAL, Vision.EXCEPTIONAL, Vision.IMPAIRED, Vision.BLIND)] == [20, 40, 6, 0])
check("seen at all: twice as far", vs.detect_tiles(outdoors(Vision.NORMAL), w) == 40 and vs.detect_tiles(outdoors(Vision.EXCEPTIONAL), w) == 80)
check("a blind character recognises and detects nothing", vs.recognize_tiles(outdoors(Vision.BLIND), w) == 0 and vs.detect_tiles(outdoors(Vision.BLIND), w) == 0)
check("indoors the range is shortened", abs(vs.recognize_tiles(outdoors(Vision.NORMAL, building_id="b"), w) - 20 * 8 / 14) < 1e-9)
night = world(hour=23, normal_m=20, exceptional_m=40, impaired_m=6)
check("and at night", abs(vs.recognize_tiles(outdoors(Vision.NORMAL), night) - 7.0) < 1e-9 and abs(vs.recognize_tiles(outdoors(Vision.NORMAL, building_id="b"), night) - 20 * 8 / 14 * 0.55) < 1e-9)
w2 = world(normal_m=20, tile_meters=2.0)
check("a tile can be more than a metre", vs.recognize_tiles(outdoors(Vision.NORMAL), w2) == 10)
check("the settings are what decides it", vs.recognize_tiles(outdoors(Vision.NORMAL), world(normal_m=33)) == 33)

# ---- glasses ---------------------------------------------------------------------------------------------------------------------------
imp = person(vision=Vision.IMPAIRED, glasses={"owned": True})
check("glasses lift an impaired character to normal", vs.effective_level(imp) == Vision.NORMAL and vs.recognize_tiles(imp, w) == 20)
imp["activity"] = {"type": "sleep"}
check("asleep or in the shower they are off", vs.effective_level(imp) == Vision.IMPAIRED)
imp["activity"] = {"type": "take_shower"}
check("... shower", vs.effective_level(imp) == Vision.IMPAIRED)
imp["activity"] = None
check("without any, impaired", vs.effective_level(person(vision=Vision.IMPAIRED, glasses={"owned": False})) == Vision.IMPAIRED and vs.effective_level(person(vision=Vision.IMPAIRED)) == Vision.IMPAIRED)
check("glasses do nothing for exceptional or blind", vs.effective_level(person(vision=Vision.EXCEPTIONAL, glasses={"owned": True})) == Vision.EXCEPTIONAL
      and vs.effective_level(person(vision=Vision.BLIND, glasses={"owned": True})) == Vision.BLIND)
check("an older character without the field falls back on their traits",
      vs.natural_level(person(physical_traits=["poor_eyesight"])) == Vision.IMPAIRED and vs.natural_level(person(physical_traits=["keen_eyesight"])) == Vision.EXCEPTIONAL
      and vs.natural_level(person()) == Vision.NORMAL)

# ---- who gets what ------------------------------------------------------------------------------------------------------------------------
rng = random.Random(7)
def share(age, level, n=6000, traits=()):
    return sum(vs.random_vision(age, traits, rng) == level for _ in range(n)) / n
check("hardly any children or young adults are impaired", share(8, Vision.IMPAIRED) < 0.12 and share(25, Vision.IMPAIRED) < 0.15)
check("from forty on a decent share need glasses, and more with age", share(45, Vision.IMPAIRED) > 0.30 and share(55, Vision.IMPAIRED) > share(45, Vision.IMPAIRED) and share(70, Vision.IMPAIRED) > 0.70,
      f"{share(45, Vision.IMPAIRED):.2f} {share(55, Vision.IMPAIRED):.2f} {share(70, Vision.IMPAIRED):.2f}")
check("a few are exceptional", 0.01 < share(25, Vision.EXCEPTIONAL) < 0.08)
check("nobody is generated blind", all(vs.random_vision(a, (), rng) != Vision.BLIND for a in range(3, 90) for _ in range(100)))
check("poor eyesight means impaired, keen eyesight exceptional", share(20, Vision.IMPAIRED, 100, ["poor_eyesight"]) == 1 and share(70, Vision.EXCEPTIONAL, 100, ["keen_eyesight"]) == 1)
owned = [vs.random_glasses(Vision.IMPAIRED, rng)["owned"] for _ in range(4000)]
check("most impaired characters own glasses, some do not", 0.8 < sum(owned) / len(owned) < 0.9)
check("nobody else does", not any(vs.random_glasses(l, rng)["owned"] for l in (Vision.NORMAL, Vision.EXCEPTIONAL) for _ in range(200)))
old = person(age=60)
check("a character from before this gets a level and glasses once", vs.ensure_vision(old, rng) and old["vision"] in Vision.GENERATED and "glasses" in old and not vs.ensure_vision(old, rng))

defs = load_definitions("default")
gen = [generate_character(defs, {"age": 58}) for _ in range(200)]
check("generated characters carry a vision level and glasses", all(c["vision"] in Vision.GENERATED and "owned" in c["glasses"] for c in gen))
check("most of the over-fifties are impaired by nature, and nobody is blind", sum(c["vision"] == Vision.IMPAIRED for c in gen) > 60 and not any(c["vision"] == Vision.BLIND for c in gen))
check("an override wins", generate_character(defs, {"age": 30, "vision": Vision.BLIND})["vision"] == Vision.BLIND)

# ---- what is made out ------------------------------------------------------------------------------------------------------------------------
w = world(normal_m=20, exceptional_m=40, impaired_m=6)
w["characters"] = {}
me = person("me", 0, 0, vision=Vision.NORMAL)
def at(d, **kw):
    other = person("o", d, 0, **kw)
    w["characters"] = {"me": me, "o": other}
    return other

with mock.patch.object(pc, "line_of_sight", return_value=True):
    at(10)
    check("a person 10 m away is recognised", [p["id"] for p in pc.perceive_people(me, w)] == ["o"] and pc.perceive_glimpsed(me, w) == [])
    at(25, sex="female", age=30)
    g = pc.perceive_glimpsed(me, w)
    check("at 25 m they are not recognised", pc.perceive_people(me, w) == [])
    check("but made out: a figure, with what they are doing", len(g) == 1 and g[0]["tier"] == "figure" and g[0]["what"] == "a woman, standing there" and g[0]["distance_m"] == 25 and g[0]["direction"] == "east", str(g))
    check("and never named", "id" not in g[0] and "name" not in g[0])
    at(35)
    g = pc.perceive_glimpsed(me, w)
    check("further out, only a shape", len(g) == 1 and g[0]["tier"] == "silhouette" and "person" in g[0]["what"] and "man" not in g[0]["what"], str(g))
    at(41)
    check("beyond twice the recognition range, nothing", pc.perceive_glimpsed(me, w) == [] and pc.perceive_people(me, w) == [])
    at(25, age=8)
    check("a child is a child", pc.perceive_glimpsed(me, w)[0]["what"].startswith("a child"))
    at(25, is_moving=True)
    check("moving is noticed", "moving about" in pc.perceive_glimpsed(me, w)[0]["what"])
    me_imp = person("me", 0, 0, vision=Vision.IMPAIRED, glasses={"owned": False})
    other = at(8)
    w["characters"]["me"] = me_imp
    check("short-sighted without glasses, 8 m is only a figure", pc.perceive_people(me_imp, w) == [] and pc.perceive_glimpsed(me_imp, w)[0]["tier"] == "figure")
    other["x"] = 10
    check("and 10 m only a shape", pc.perceive_glimpsed(me_imp, w)[0]["tier"] == "silhouette")
    other["x"] = 8
    me_imp["glasses"] = {"owned": True}
    check("with glasses, a face", [p["id"] for p in pc.perceive_people(me_imp, w)] == ["o"])
    me_ex = person("me", 0, 0, vision=Vision.EXCEPTIONAL)
    at(35)
    w["characters"]["me"] = me_ex
    check("exceptional sight recognises at 35 m", [p["id"] for p in pc.perceive_people(me_ex, w)] == ["o"])
    me_bl = person("me", 0, 0, vision=Vision.BLIND)
    at(2)
    w["characters"]["me"] = me_bl
    check("blind: nobody, not even next to them", pc.perceive_people(me_bl, w) == [] and pc.perceive_glimpsed(me_bl, w) == [])
    me_n = person("me", 0, 0, vision=Vision.NORMAL, off_grid=False)
    other = at(25)
    other["off_grid"] = True
    check("someone away is not seen", pc.perceive_glimpsed(me_n, w) == [])
check("without a line of sight, not even a shape", (lambda: (at(25), mock.patch.object(pc, "line_of_sight", return_value=False).start(), pc.perceive_glimpsed(me, w))[2] == [])())
mock.patch.stopall()

# the context lines
from brain.context_builder import _sec_glimpsed
lines = _sec_glimpsed({"perception": {"glimpsed": [{"tier": "figure", "distance_m": 25, "direction": "east", "what": "a woman, standing there"}]}}, w)
check("the prompt lists them without names", lines and "a woman, standing there, about 25 m to the east (too far to tell who)" in lines[1], str(lines))
check("and says nothing when there is nobody", _sec_glimpsed({"perception": {"glimpsed": []}}, w) is None and _sec_glimpsed({}, w) is None)

# ---- an outburst reaches as far as they can see -------------------------------------------------------------------------------------------------
w = world(normal_m=20, exceptional_m=40, impaired_m=6)
a = person("a", 0, 0, building_id="b1", vision=Vision.NORMAL)
b = person("b", 10, 0, building_id="b1")
check("someone in the same building within what they can recognise indoors (11 tiles)", impulse.within_reach(a, b, w))
b["x"] = 13
check("not when they are farther than that", not impulse.within_reach(a, b, w))
a["vision"] = Vision.EXCEPTIONAL
check("an exceptional eye reaches farther (22 tiles indoors)", impulse.within_reach(a, b, w))
a["vision"], b["x"] = Vision.IMPAIRED, 5
check("a short-sighted one without glasses, not 5 tiles away (3.4 indoors)", not impulse.within_reach(a, b, w))
a["glasses"] = {"owned": True}
check("with glasses they can", impulse.within_reach(a, b, w))
a["vision"] = Vision.BLIND
check("a blind one cannot, whoever is near", not impulse.within_reach(a, b, w))
a["vision"] = Vision.NORMAL
b["building_id"] = "b2"
check("another building: never", not impulse.within_reach(a, b, w))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
