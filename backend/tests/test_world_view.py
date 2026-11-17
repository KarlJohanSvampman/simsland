"""
The WorldView façade (core/world_view.py): the resident world and its entity collections are dict / list subclasses
that note which entities are reached, so a flush renders only those (core/entity_store.py). Checked here: what counts
as touching (item access, get, values, items, writes; not iterating keys; not reading the props list), that the world
still behaves -- and serialises -- as a plain dict, that assigned collections are wrapped, that untracked observers touch
nothing, and that a change made without going through the world is caught by a full comparison and reported.

Run inside the backend container:   python tests/test_world_view.py
"""

import copy
import json
import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import world_view as WV, entity_store as ES

plain = {"tick": 1, "characters": {"a": {"id": "a", "x": 1}, "b": {"id": "b", "x": 2}},
         "households": {"h": {"id": "h"}}, "props": [{"id": "p1"}, {"id": "p2"}], "weather": {"sun": True}}
w = WV.install(copy.deepcopy(plain), "wv_test")
WV.take_touched("wv_test")

check("the world is still a dict, its collections dicts/lists", isinstance(w, dict) and isinstance(w["characters"], dict)
      and isinstance(w["props"], list))
check("... and serialises exactly like the plain world", json.dumps(w) == json.dumps(plain))
WV.take_touched("wv_test")

_ = w["characters"]["a"]["x"]
t = WV.take_touched("wv_test")
check("reaching a character touches it (and only it)", ("characters", "a") in t and ("characters", "b") not in t, t)
list(w["characters"])
t = WV.take_touched("wv_test")
check("iterating the ids touches no entity", not any(k[0] == "characters" for k in t), t)
for c in w["characters"].values():
    pass
t = WV.take_touched("wv_test")
check("values() touches every entity", {("characters", "a"), ("characters", "b")} <= t, t)
[p for p in w["props"]]
t = WV.take_touched("wv_test")
check("reading the props list notes none (the list is compared whole: '*list' marker)",
      not any(k[0] == "props" for k in t) and ("*list", "props") in t, t)
w["props"].append({"id": "p3"})
t = WV.take_touched("wv_test")
check("appending a prop notes it", ("props", "p3") in t, t)
_ = w["tick"]
check("a top-level key reached is noted", ("key", "tick") in WV.take_touched("wv_test"))
w["characters"] = {"z": {"id": "z"}}
check("an assigned collection is wrapped", isinstance(w["characters"], WV.EntityMap))
WV.take_touched("wv_test")
with WV.untracked():
    for c in w["characters"].values():
        pass
    _ = w["weather"]
check("an untracked observer touches nothing", WV.take_touched("wv_test") == {("*list", "props")})
check("copies are plain", type(copy.deepcopy(w)) is dict and type(copy.deepcopy(w)["characters"]) is dict)

# a change made without going through the world: caught by a full comparison
ES.forget("wv_test")
ups, dels, _m = ES.diff("wv_test", w)
ES.note_written("wv_test", ups, dels)
ref = dict.__getitem__(dict.__getitem__(w, "characters"), "z")        # a reference kept around
WV.take_touched("wv_test")
ref["x"] = 99                                                         # changed behind the façade's back
only = WV.take_touched("wv_test")
ups_touched, _, _ = ES.diff("wv_test", w, only=only)
ups_full, _, _ = ES.diff("wv_test", w)
missed = [k for k in ups_full if k not in only and k[0] != "meta"]
check("a change made behind the façade is missed by the touched diff ...", ("characters", "z") not in ups_touched)
check("... and found by the full comparison", missed == [("characters", "z")], missed)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
