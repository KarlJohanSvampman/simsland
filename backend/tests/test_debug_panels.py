"""
Debug panels (systems/debug_panels.py, api/debug_panels.py): templates (widgets), who they apply to, per-entity
layouts (one active, up to 5 alternatives), and reading any path into an entity.

Run inside the backend container:   python tests/test_debug_panels.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from systems import debug_panels as dp

tmp = Path(tempfile.mkdtemp())
dp.path = lambda sim_id="default": tmp / "debug_panels.json"      # never touch the real file
data = dp.load()
check("no file yet: nothing", data == {"templates": [], "entities": {}})

check("a bad template is refused", dp.check_template({"id": "Bad Id", "type": "radar"}) != [])
traits = {"id": "trait_log", "name": "Trait changes", "type": "table", "source": {"path": "trait_log", "refresh_s": 5},
          "assign": {"scope": "kinds", "kinds": ["character"]}, "default_state": "enabled"}
hunger = {"id": "hunger", "name": "Hunger", "type": "text", "source": {"path": "body"}, "assign": {"scope": "entities",
          "entities": ["character:joseph"]}, "default_state": "on_demand"}
lamp = {"id": "lamp_state", "name": "Lamp", "type": "tree", "source": {"path": ""}, "assign": {"scope": "kinds", "kinds": ["prop"]}}
for t in (traits, hunger, lamp):
    check(f"template {t['id']} is fine", dp.check_template(t) == [], str(dp.check_template(t)))
    dp.put_template(data, t)
dp.save(data)
data = dp.load()

j = dp.for_entity(data, "character", "joseph")
s = dp.for_entity(data, "character", "susan")
p = dp.for_entity(data, "prop", "lamp1")
check("Joseph: the character template and the one assigned to him, in their default states",
      sorted(t["id"] for t in j["templates"]) == ["hunger", "trait_log"] and j["states"] == {"trait_log": "enabled", "hunger": "on_demand"}, str(j["states"]))
check("Susan: only the character template", [t["id"] for t in s["templates"]] == ["trait_log"])
check("a prop: only the prop template", [t["id"] for t in p["templates"]] == ["lamp_state"])

# Susan gets the lamp panel added just for her, and two layouts
probs = dp.set_layouts(data, "character", "susan", {"active": "Social", "layouts": {
    "Default": {"panels": {"trait_log": "enabled"}},
    "Social": {"panels": {"trait_log": "disabled", "lamp_state": "on_demand"}}}})
check("saving two layouts", probs == [], str(probs))
s = dp.for_entity(data, "character", "susan")
check("... the active one decides: trait log off, the panel added just for her on demand",
      s["active"] == "Social" and s["states"] == {"trait_log": "disabled", "lamp_state": "on_demand"}, str(s))
check("... and only for her", "lamp_state" not in [t["id"] for t in dp.for_entity(data, "character", "joseph")["templates"]])
too_many = {f"L{i}": {"panels": {}} for i in range(7)}
check("seven layouts (one active + six) are refused", dp.set_layouts(data, "character", "susan", {"active": "L0", "layouts": too_many}) != [])
check("an active layout that isn't one of them is refused", dp.set_layouts(data, "character", "susan",
      {"active": "Nope", "layouts": {"A": {"panels": {}}}}) != [])
dp.delete_template(data, "lamp_state")
check("deleting a template takes it out of every layout", "lamp_state" not in dp.for_entity(data, "character", "susan")["states"])

# data paths
ent = {"body": {"hunger": 61.5}, "trait_log": [{"tick": 1, "added": ["witty"]}, {"tick": 2, "removed": ["shy"]}], "name": "J"}
check("a path into the entity", dp.data_at(ent, "body.hunger") == 61.5 and dp.data_at(ent, "trait_log.-1.tick") == 2
      and dp.data_at(ent, "") is ent and dp.data_at(ent, "nope.x") is None)
f = dp.fields(ent)
check("the outline for picking a path", f["body"]["type"] == "object" and f["trait_log"]["type"] == "list"
      and f["trait_log"]["size"] == 2 and "item" in f["trait_log"], str(f))

from house_world import make_world
w = make_world()
w["props"][0]["storage"] = {"resources": [{"id": "item_apple_1", "template_id": "apple", "quantity": 2}]}
check("entities of every kind are found", dp.find_entity(w, "character", "joseph")["name"].startswith("Joseph")
      and dp.find_entity(w, "prop", w["props"][0]["id"]) is w["props"][0]
      and dp.find_entity(w, "household", "lind")["id"] == "lind"
      and dp.find_entity(w, "item", "item_apple_1")["template_id"] == "apple")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
