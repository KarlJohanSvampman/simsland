"""
Who a line is for (systems/addressing.py) and what that does to the ledger, child grudges, and where spawned people stand.

Run inside the backend container:   python tests/test_addressing.py
"""

import os
import random
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from systems import addressing as ad
from systems import grudges
from systems import relationship_ledger as rl

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, name, age=30, **extra):
    d = {"id": cid, "name": name, "age": age, "traits": [], "memories": [], "relationships": {}, "alive": True, "x": 1, "y": 1}
    d.update(extra)
    return d


maja, oskar, anna = person("maja", "Maja Lindqvist", 9), person("oskar", "Oskar Lindqvist", 6), person("anna", "Anna Lindqvist", 36)
maja["relationships"] = {"oskar": {"kinship": "sibling"}, "anna": {"kinship": "child"}}
oskar["relationships"] = {"maja": {"kinship": "sibling"}, "anna": {"kinship": "child"}}
w = {"tick": 5000, "characters": {c["id"]: c for c in (maja, oskar, anna)}, "definitions": {}}


def elsewhere(speaker, listener, text):
    return ad.addressed_elsewhere(w, speaker, listener, text)


# ---- who a line is for -------------------------------------------------------------------------------------------------------------
check("'Daddy, can we play?' said to a sibling is for somebody else", elsewhere("maja", "oskar", '"Daddy, can we have a playtime? I wanna play with you!"'))
check("'Mommy, ...' said to a sibling too", elsewhere("maja", "oskar", "Mommy, what's Maja doing?"))
check("'Mom, ...' said to the mother is for her", not elsewhere("maja", "anna", "Mom, can we go inside now, please? I'm cold!"))
check("a name that is somebody else's", elsewhere("oskar", "maja", "Hey Anna, can we get some warm clothes?"))
check("a name that is the listener's own", not elsewhere("oskar", "maja", "Hi Maja! What's on your phone?"))
check("fillers are skipped", not elsewhere("oskar", "maja", "Excuse me, Maja, may I play on the computer?"))
check("... and a different name after them is somebody else's", elsewhere("oskar", "maja", "Excuse me, Anna, may I play on the computer?"))
check("a trailing vocative", elsewhere("maja", "oskar", "Can we go inside now, Dad?"))
check("no vocative at all is for the listener", not elsewhere("oskar", "maja", "Do you want to play a game with me?"))
check("a kin term in the middle of a sentence is not a vocative", not elsewhere("oskar", "maja", "I think the cat ate my mom's cake yesterday"))
check("empty or unknown characters are never 'elsewhere'", not elsewhere("oskar", "maja", "") and not elsewhere("nobody", "maja", "Daddy!"))
check("grandma is for a grandparent", not ad.addressed_elsewhere(
    {"characters": {"a": dict(person("a", "Al", 7), relationships={"g": {"kinship": "grandchild"}}), "g": person("g", "Gran", 70)}}, "a", "g", "Grandma, look!"))

# ---- the ledger ----------------------------------------------------------------------------------------------------------------------
random.seed(1)
data = {"conv_id": "c1", "speaker_id": "maja", "ignorer_id": "oskar", "heard": True, "utterance": '"Daddy, can we have a playtime?"'}
rl._on_conversation_ignored(data, w)
event_bus.flush(w)
check("an ignored line that was meant for a parent writes nothing against the sibling", rl.get_ledger(w, "oskar", "maja", create=False) is None)
rl._on_conversation_ignored(dict(data, utterance="Oskar, do you want to play?"), w)
event_bus.flush(w)
led = rl.get_ledger(w, "oskar", "maja", create=False)
check("one really aimed at them still counts", led is not None and any(e["kind"].startswith("ignored") for e in led["entries"]), str(led))

# ---- a child's grudge ---------------------------------------------------------------------------------------------------------------
said = []
import systems.expressions as expr
with mock.patch.object(expr, "express", lambda holder, world, spec: said.append(spec)):
    random.seed(2)
    g = {"short_term_until": 10 ** 9, "jabbed": -10 ** 9, "offender": "maja", "aware": False, "priority": 5}
    oskar["traits"] = ["hot_tempered", "aggressive"]
    oskar["perception"] = {"visible_people": [{"id": "maja"}]}
    for _ in range(40):
        g["jabbed"] = -10 ** 9
        grudges._behave(w, oskar, maja, g, 5000)
    check("a six-year-old with a grudge sulks, however hot-tempered", said and all(s["speech_act"] in ("mutter", "sigh") for s in said), str(said[:3]))
    check("and never at the other child as an insult", all(s.get("target") is None and "hurt" not in str(s.get("intent")) for s in said))
    check("in a child's words", all(len(s["utterance"]) < 40 for s in said) and any("mad" in s["utterance"] or "Hmph" in s["utterance"] for s in said))
    said.clear()
    anna["traits"] = ["hot_tempered"]
    anna["perception"] = {"visible_people": [{"id": "maja"}]}
    for _ in range(60):
        g["jabbed"] = -10 ** 9
        grudges._behave(w, anna, maja, g, 5000)
    check("a grown-up with the same temper can still jab", any(s["speech_act"] == "insult" for s in said))

# ---- spawned people stand inside ----------------------------------------------------------------------------------------------------
import db
live = db.load_world("default")
from systems.navigation import find_building_at, get_room_at_position
house = live["buildings"][0]
fp_rooms = live["definitions"]["floorplan_templates"][house["template"]]["rooms"]
tile = fp_rooms[1]["tiles"][0]
b, _ = find_building_at(live, house["x"] + tile["x"], house["y"] + tile["y"])
check("a point on a room tile is found inside its building", b and b["id"] == house["id"])
check("and resolves to that room", get_room_at_position(b, house["x"] + tile["x"], house["y"] + tile["y"]) == f'{house["id"]}:{fp_rooms[1]["id"]}')
out, _ = find_building_at(live, house["x"] + 30, house["y"] + 30)
check("a point outside every building is in none", out is None or out["id"] != house["id"])
from systems.room_assignment import assign_character_room
c = {"x": house["x"] + tile["x"], "y": house["y"] + tile["y"]}
try:
    room = assign_character_room(house, c)
    ok = c["building_id"] == house["id"] and room == f'{house["id"]}:{fp_rooms[1]["id"]}'
except Exception as exc:                                   # noqa: BLE001
    ok = False
    print("   ", repr(exc))
check("assign_character_room works (it used to pass an id where a building belongs)", ok)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
