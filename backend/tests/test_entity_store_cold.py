"""
Characters persisted hot/cold (core/entity_store.py, 2026-11-23): a touch used to re-render the whole ~1 MB character
every flush. Now cold keys (memories, logs, sessions...) are rows of their own, rendered only when they look changed or
their turn comes round. Checked without a database (a fake db module), so it runs anywhere:

A. Saved and loaded back identical -- key order inside each character included.
B. A touch to a hot key writes the small hot row only.
C. Appending to a cold list writes that cold row (and not the others).
D. An in-place edit that keeps the length is written within COLD_RECHECK_FLUSHES flushes.
E. An old one-row save loads identical, and its first flush writes it split.
F. A cold key that goes away is deleted.
G. Size: a big character, touched, writes a few KB, not the character.

Run:   python tests/test_entity_store_cold.py
"""
import contextlib, json, os, sys, types
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

# ---- a fake db: rows kept in a dict -------------------------------------------------------------------------------
ROWS = {}
class _Cur:
    def execute(self, *a, **k): pass
    def fetchall(self): return [(k, i, json.loads(t)) for (k, i), t in ROWS.items()]
    def __enter__(self): return self
    def __exit__(self, *a): return False
class _Conn:
    def cursor(self): return _Cur()
    def __enter__(self): return self
    def __exit__(self, *a): return False
fake = types.ModuleType("db"); fake._conn_lock = contextlib.nullcontext(); fake.conn = _Conn(); fake._STATIC_WORLD_KEYS = ()
sys.modules["db"] = fake

from core import entity_store as ES
SIM = "cold_test"

def flush(world, only=None):
    ups, dels, _m = ES.diff(SIM, world, only=only)
    ES.note_written(SIM, ups, dels)
    ROWS.update(ups)
    for k in dels:
        ROWS.pop(k, None)
    return ups, dels

def same(a, b):
    return json.dumps(a) == json.dumps(b)

def touched(*cids):
    return {("characters", c) for c in cids}

world = {
    "tick": 1,
    "characters": {
        "amy": {"id": "amy", "x": 1, "memories": [{"t": "a"}], "hunger": 10, "conversation_log": [], "mood": "ok"},
        "bob": {"id": "bob", "memories": [{"t": "b"}], "x": 5},
    },
    "props": [{"id": "p1"}],
}
ups, _ = flush(world)
check("A: the first flush writes hot rows and one row per cold key",
      {("characters", "amy"), ("char_cold", "amy/memories"), ("char_cold", "amy/conversation_log"),
       ("characters", "bob"), ("char_cold", "bob/memories")} <= set(ups), sorted(ups))
check("A: the hot row keeps a marker where the cold key was",
      json.loads(ups[("characters", "amy")]) == {"id": "amy", "x": 1, "memories": {"$cold": 1}, "hunger": 10,
                                                 "conversation_log": {"$cold": 1}, "mood": "ok"})
ES.forget(SIM)
back = ES.load(SIM)
check("A: it loads back identical, key order included", same(back, world), back)

# from here on, the world as loaded is the live one (as in the sim)
world = back
world["characters"]["amy"]["x"] = 2
ups, _ = flush(world, only=touched("amy"))
check("B: a hot change writes only the hot row", set(ups) == {("characters", "amy")}, sorted(ups))

world["characters"]["amy"]["memories"].append({"t": "a2"})
ups, _ = flush(world, only=touched("amy"))
check("C: appending to memories writes that cold row only", set(ups) == {("char_cold", "amy/memories")}, sorted(ups))

world["characters"]["amy"]["memories"][-1]["t"] = "edited in place"
seen = False
for _ in range(ES.COLD_RECHECK_FLUSHES):
    ups, _ = flush(world, only=touched("amy"))
    if ("char_cold", "amy/memories") in ups:
        seen = True
        break
check("D: an in-place edit is written within COLD_RECHECK_FLUSHES flushes", seen)

del world["characters"]["amy"]["conversation_log"]
ups, dels = flush(world, only=touched("amy"))
check("F: a cold key that went away is deleted", ("char_cold", "amy/conversation_log") in dels, (sorted(ups), dels))
ES.forget(SIM)
check("F: ...and the load matches", same(ES.load(SIM), world))

# E. an old save: one full row per character
ROWS.clear(); ES.forget(SIM)
old = {"tick": 3, "characters": {"cat": {"id": "cat", "memories": [{"t": "c"}], "x": 9, "speech_log": [{"u": "hi"}]}}}
ROWS[("meta", "manifest")] = json.dumps({"keys": ["tick", "characters"],
                                         "collections": {"characters": {"type": "dict", "order": ["cat"]}}})
ROWS[("key", "tick")] = json.dumps(3)
ROWS[("characters", "cat")] = json.dumps(old["characters"]["cat"])
w2 = ES.load(SIM)
check("E: an old one-row save loads identical", same(w2, old), w2)
ups, _ = flush(w2, only=set())                 # untouched: the full compare is what picks it up
ups2, _ = flush(w2)
allups = set(ups) | set(ups2)
check("E: its first full flush writes it split",
      {("characters", "cat"), ("char_cold", "cat/memories"), ("char_cold", "cat/speech_log")} <= allups, sorted(allups))
check("E: ...and the stored hot row now has markers", json.loads(ROWS[("characters", "cat")])["memories"] == {"$cold": 1})
ES.forget(SIM)
check("E: ...and it loads back identical from the split rows", same(ES.load(SIM), old))

# G. size
ROWS.clear(); ES.forget(SIM)
big = {"id": "big", "x": 0, "hunger": 1,
       "memories": [{"text": "m" * 400, "i": i} for i in range(1500)],
       "conversation_log": [{"lines": [{"t": "l" * 200}] * 20} for _ in range(60)],
       "_llm_session": {"history": [{"text": "h" * 300}] * 20}}
w3 = {"tick": 1, "characters": {"big": big}}
ups, _ = flush(w3)
full = sum(len(t) for t in ups.values())
big["x"] = 1; big["hunger"] = 2
ups, _ = flush(w3, only=touched("big"))
size = sum(len(t) for t in ups.values())
print(f"     whole character {full // 1024} KB, a touch writes {size} bytes")
check("G: a touch writes a few KB, not the character", size < 5000 and full > 500_000, (size, full))

# H. a throttled world key (the stock market) is written at most every THROTTLED_KEYS flushes
ROWS.clear(); ES.forget(SIM)
w4 = {"tick": 1, "stocks": {"ACME": [1]}}
flush(w4)
writes = 0
for i in range(ES.THROTTLED_KEYS["stocks"] * 2):
    w4["stocks"]["ACME"].append(i)
    ups, _ = flush(w4, only={("key", "stocks")})
    writes += ("key", "stocks") in ups
check("H: the stock market is written once a throttle period, not every flush", 1 <= writes <= 3, writes)

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
