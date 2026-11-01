"""
1. Walking to a room: "move | towards the kitchen" resolves to the kitchen of the building the character is in
   (systems/room_targets.py, brain/action_resolver.py, systems/action_validator.py).
2. A thought is had once: a repeat isn't stored again -- one "can't think of anything else" thought instead, and the
   focused intention gets more pressing with every repeat (systems/thought_repeat.py, brain/intentions.py).

Live case (2026-11-01): Kathleen Okafor stood still while "I head toward towards the kitchen, to grab a glass of
water." filled her short-term memory.

Run inside the backend container:   python tests/test_room_moves_and_thoughts.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def tiles(*coords):
    return [{"x": x, "y": y} for x, y in coords]


# The rooms of the real starter_house floorplan that matter here (local tile coordinates).
STARTER_HOUSE = {
    "width": 20, "height": 20,
    "rooms": [
        {"id": "kitchen_0", "type": "kitchen",
         "tiles": tiles(*[(x, y) for y in (3, 4, 5) for x in range(6, 13)])},
        {"id": "dining_room_1", "type": "dining_room",
         "tiles": tiles(*[(x, y) for y in range(6, 12) for x in range(9, 13)])},
        {"id": "restroom_2", "type": "restroom",
         "tiles": tiles(*[(x, y) for y in (6, 7) for x in range(13, 17)])},
        {"id": "living_room_4", "type": "living_room",
         "tiles": tiles(*[(x, y) for y in range(2, 7) for x in range(0, 5)])},
        {"id": "laundry_6", "type": "laundry", "tiles": tiles((3, 10), (3, 11), (4, 10), (4, 11), (3, 12), (4, 12))},
        {"id": "laundry_7", "type": "laundry",
         "tiles": tiles(*[(x, y) for y in (10, 11, 12) for x in range(0, 5)])},
    ],
}


def make_world():
    return {
        "tick": 18977,
        "definitions": {"floorplan_templates": {"starter_house": STARTER_HOUSE}},
        "buildings": [{"id": "starter_house_2", "x": 50, "y": 0, "rotation": 0, "template": "starter_house"}],
        "characters": {},
        "props": [{"id": "prop_counter", "template": "kitchen_counter", "x": 58, "y": 3}],
    }


# ---- 1. rooms as somewhere to walk to ----------------------------------------------------------------------------
from systems.room_targets import match_room, room_destination, describe_room_target
from brain.action_resolver import resolve_target
from systems.action_validator import validate_target
from brain.llm_brain import _canned_narration

world = make_world()
kathleen = {"id": "kathleen", "building_id": "starter_house_2", "room_id": "starter_house_2:restroom_2",
            "x": 64, "y": 6}
world["characters"]["kathleen"] = kathleen
desc = "towards the kitchen, where I can grab a glass of water to wash down the stale taste in my mouth"

check("Kathleen's own sentence names the kitchen",
      match_room(kathleen, world, desc) == "room:starter_house_2:kitchen_0", match_room(kathleen, world, desc))
check("'the toilet' is the restroom", match_room(kathleen, world, "the toilet") == "room:starter_house_2:restroom_2")
check("'living room' wins over a bare 'room'",
      match_room(kathleen, world, "go to the living room") == "room:starter_house_2:living_room_4")
check("a word inside another word doesn't count ('hallmark' is not the hall)",
      match_room(kathleen, world, "the hallmark card") is None)
check("a place the building doesn't have is no match", match_room(kathleen, world, "the garage") is None)
check("nothing room-like is no match", match_room(kathleen, world, "Susan Moreau") is None)
check("outside any building there are no rooms",
      match_room({"id": "x", "x": 0, "y": 0}, world, "the kitchen") is None)

two = match_room(kathleen, world, "the laundry")
check("of two laundry rooms the nearer one is picked", two in ("room:starter_house_2:laundry_6",
                                                               "room:starter_house_2:laundry_7"), two)
in_kitchen = dict(kathleen, room_id="starter_house_2:kitchen_0")
check("already in the only kitchen: still the kitchen (nothing else to pick)",
      match_room(in_kitchen, world, "the kitchen") == "room:starter_house_2:kitchen_0")

dest = room_destination(world, "room:starter_house_2:kitchen_0")
check("the destination is a kitchen tile in world coordinates",
      dest is not None and 56 <= dest[0] <= 62 and 3 <= dest[1] <= 5, str(dest))
check("a room that doesn't exist has no destination", room_destination(world, "room:starter_house_2:pool") is None)
check("the narration name of a room target", describe_room_target(world, "room:starter_house_2:kitchen_0") == "the kitchen")

available = {"interactable_props": [
    {"id": "prop_counter", "template": "kitchen_counter", "tags": ["furniture", "food_storage", "free"],
     "interactions": ["prepare_food"]},
    {"id": "prop_toilet", "template": "toilet_a", "tags": ["bathroom", "usable", "free"], "interactions": ["use_toilet"]},
], "nearby_characters": [{"id": "robert", "name": "Robert Okafor"}]}

r = resolve_target(kathleen, world, "move", desc, available)
check("move: the kitchen sentence resolves to the kitchen", r["id"] == "room:starter_house_2:kitchen_0", str(r))
r = resolve_target(kathleen, world, "jog_to", "the kitchen", available)
check("jog_to 'the kitchen' ends up in the kitchen (the counter matches directly; the room is the fallback)",
      r["id"] in ("room:starter_house_2:kitchen_0", "prop_counter"), str(r))
r = resolve_target(kathleen, world, "jog_to", "hurry to the living room", available)
check("jog_to resolves rooms too", r["id"] == "room:starter_house_2:living_room_4", str(r))
r = resolve_target(kathleen, world, "move", "Robert Okafor", available)
check("a person still wins when one is named", r["id"] == "robert", str(r))
r = resolve_target(kathleen, world, "move", "the toilet_a", available)
check("a prop still wins when one is named", r["id"] == "prop_toilet", str(r))
r = resolve_target(kathleen, world, "speak", "the kitchen", available)
check("only move-type actions get rooms", not str(r["id"] or "").startswith("room:"), str(r))
r = resolve_target(kathleen, world, "move", "the kitchen", {})
check("with nothing nearby at all, a named room still resolves", r["id"] == "room:starter_house_2:kitchen_0", str(r))

check("the validator accepts a room target for move",
      validate_target(world, {"type": "move", "target": "room:starter_house_2:kitchen_0"}, kathleen))
check("... and not for interact",
      not validate_target(world, {"type": "interact", "target": "room:starter_house_2:kitchen_0"}, kathleen))
check("... and not for a room that doesn't exist",
      not validate_target(world, {"type": "move", "target": "room:starter_house_2:pool"}, kathleen))

check("no more 'I head toward towards'",
      _canned_narration("move", "towards the kitchen, to grab a glass of water")
      == "I head toward the kitchen, to grab a glass of water.",
      _canned_narration("move", "towards the kitchen, to grab a glass of water"))
check("a plain target is untouched", _canned_narration("move", "the fridge") == "I head toward the fridge.")

# ---- 2. a thought is had once ------------------------------------------------------------------------------------
from systems.thought_repeat import handle_thought, FIXATION_STEP, FIXATION_MAX, REPEAT_WINDOW_TICKS
from brain.memory import store_memory
from brain import intentions as intents

thought = "I head toward the kitchen, to grab a glass of water."
world = make_world()
world["tick"] = 1000
intents.set_current_tick(1000)
c = {"id": "kathleen", "memories": [], "active_intentions": []}
intents.add_intention(c, {"type": "play_with_friend", "category": "social", "priority": 40,
                          "reason": "Susan Moreau lives close by and you feel like playing together"})
intents.add_intention(c, {"type": "drink", "category": "social", "priority": 30})
c["selected_situation"] = {"situations": [{"type": "play_with_friend"}]}
focus = next(i for i in c["active_intentions"] if i["type"] == "play_with_friend")
before = intents.final_priority(focus, c)


def think(t):
    world["tick"] = t
    if handle_thought(c, world, thought):
        store_memory(c, text=thought, tags=["thought"], importance=0.3, tick=t, source="internal")


think(1000)
check("a new thought is stored", sum(1 for m in c["memories"] if m.get("text") == thought) == 1)
for t in range(1001, 1011):
    think(t)
same = [m for m in c["memories"] if m.get("text") == thought]
fix = [m for m in c["memories"] if "fixation" in (m.get("tags") or [])]
check("ten repeats later it is still stored once", len(same) == 1, str(len(same)))
check("there is one 'can't think of anything else' thought", len(fix) == 1, str([m.get("text") for m in fix]))
check("... and it names what they're focused on, in their own words",
      fix and fix[0]["text"] == "I can't seem to think of anything else -- "
                                 "Susan Moreau lives close by and I feel like playing together.",
      fix and fix[0]["text"])
focus = next(i for i in c["active_intentions"] if i["type"] == "play_with_friend")
check("the focus got more pressing, up to the cap", focus.get("fixation_boost") == FIXATION_MAX,
      str(focus.get("fixation_boost")))
check("final_priority includes it", intents.final_priority(focus, c) == min(
    before + FIXATION_MAX, intents.CATEGORY_PRIORITY.get("social", 0) * 1000 + 100), str(intents.final_priority(focus, c)))
other = next(i for i in c["active_intentions"] if i["type"] == "drink")
check("an intention they aren't focused on is untouched", not other.get("fixation_boost"))

think_also = "I should wait and observe."
for t in (1011, 1012, 1013):
    world["tick"] = t
    if handle_thought(c, world, think_also):
        store_memory(c, text=think_also, tags=["thought"], importance=0.3, tick=t, source="internal")
fix = [m for m in c["memories"] if "fixation" in (m.get("tags") or [])]
check("a second repeated thought about the same focus adds no second 'can't think' thought",
      len(fix) == 1, str([m.get("text") for m in fix]))

c3 = {"id": "brenda", "memories": [], "active_intentions": []}
intents.add_intention(c3, {"type": "expectation:get_kids_to_school", "category": "social", "priority": 50,
                           "reason": "You still need to get the kids to school"})
w3 = {"tick": 50}
handle_thought(c3, w3, "Hmm.")
store_memory(c3, text="Hmm.", tags=["thought"], tick=50)
handle_thought(c3, w3, "Hmm.")
fix3 = [m["text"] for m in c3["memories"] if "fixation" in (m.get("tags") or [])]
check("a reason written to the character ('You still need ...') becomes first person",
      fix3 == ["I can't seem to think of anything else -- I still need to get the kids to school."], str(fix3))

intents.add_intention(c, {"type": "play_with_friend", "category": "social", "priority": 42})
focus = next(i for i in c["active_intentions"] if i["type"] == "play_with_friend")
check("a refresh of the intention keeps the built-up pressure", focus.get("fixation_boost") == FIXATION_MAX)

think(1000 + REPEAT_WINDOW_TICKS + 5)
check("long after, the same thought can be had (and stored) again",
      sum(1 for m in c["memories"] if m.get("text") == thought) == 2)

c2 = {"id": "x", "memories": [], "active_intentions": []}
w2 = {"tick": 5}
check("a first thought with no intentions at all is fine", handle_thought(c2, w2, "Hmm."))
store_memory(c2, text="Hmm.", tags=["thought"], tick=5)
check("a repeat with no intentions at all is fine", handle_thought(c2, w2, "hmm") is False)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
