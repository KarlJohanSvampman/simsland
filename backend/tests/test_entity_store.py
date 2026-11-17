"""
The world persisted as per-entity records (core/entity_store.py): a flush writes only the entities whose JSON changed,
deletes the ones that are gone, and writes the manifest that keeps every collection's order -- in one transaction, so
what is read back is the world as of one flush. Checked here against a real Postgres (DATABASE_URL), on a sim id of
its own, then through core/world_state.py (the resident world's write-behind and the loader in db.py).

Run inside the backend container:   python tests/test_entity_store.py
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


import db
from core import entity_store as ES, world_state as WS

SIM = "test_entities"


def wipe():
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            ES.ensure_tables(cur)
            cur.execute("DELETE FROM entities WHERE sim_id=%s", (SIM,))
            cur.execute("DELETE FROM entity_commits WHERE sim_id=%s", (SIM,))
    ES.forget(SIM)


def flush(world, tick):
    ups, dels, _m = ES.diff(SIM, world)
    ES.note_written(SIM, ups, dels)
    ES.write(SIM, ups, dels, tick)
    return ups, dels


def same(a, b):
    return json.dumps(a) == json.dumps(b)                # order included


wipe()
world = {
    "tick": 7, "sim_time": 1000.5,
    "characters": {"zed": {"id": "zed", "x": 1, "mood": None}, "amy": {"id": "amy", "x": 2, "memories": [{"t": "a"}]}},
    "households": {"h1": {"id": "h1", "members": ["zed", "amy"]}},
    "props": [{"id": "p2", "kind": "sofa"}, {"id": "p1", "kind": "lamp"}],
    "timers": [{"owner": "x", "due": 3}],
    "weather": {},
}
ups, dels = flush(world, 7)
check("the first flush writes every entity and the manifest",
      set(ups) == {("characters", "zed"), ("characters", "amy"), ("households", "h1"), ("props", "p2"), ("props", "p1"),
                   ("key", "tick"), ("key", "sim_time"), ("key", "timers"), ("key", "weather"), ("meta", "manifest")}, sorted(ups))
ES.forget(SIM)
back = ES.load(SIM)
check("it loads back identical, in the same order (keys, collections, list order)", same(back, world), back)

world["characters"]["amy"]["x"] = 3
world["tick"] = 8
ups, dels = flush(world, 8)
check("a change writes only what changed", set(ups) == {("characters", "amy"), ("key", "tick")} and not dels, (sorted(ups), dels))
del world["characters"]["zed"]
world["props"].reverse()
ups, dels = flush(world, 9)
check("a removed entity is deleted; a reordered list rewrites only the manifest",
      dels == [("characters", "zed")] and set(ups) == {("meta", "manifest")}, (sorted(ups), dels))
ES.forget(SIM)
check("... and reads back that way", same(ES.load(SIM), world), ES.load(SIM))
ups, dels = flush(world, 10)
check("nothing changed: nothing written", not ups and not dels, (ups, dels))

# queued diffs are merged, never dropped
a = ("entities", {("k", "1"): "A", ("k", "2"): "B"}, [("k", "3")])
b = ("entities", {("k", "3"): "C"}, [("k", "2")])
m = WS._merge_payloads(a, b)
check("two queued diffs merge (later wins; a delete cancels an upsert and the other way)",
      m[1] == {("k", "1"): "A", ("k", "3"): "C"} and m[2] == [("k", "2")], m)

# ── through world_state: the resident world, write-behind, and db's loader ─────────────────────────────────────────
wipe()
fresh = copy.deepcopy(world)
fresh["characters"]["bob"] = {"id": "bob", "x": 9}
WS._replace_entities(SIM, fresh, 10)
ES.forget(SIM)
check("a whole new world saved from outside replaces the sim's rows", same(ES.load(SIM), fresh))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
wipe()
sys.exit(1 if failures else 0)
