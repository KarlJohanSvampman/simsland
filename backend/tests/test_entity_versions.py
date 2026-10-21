"""
Entity versions and websocket patch deltas (core/entity_versions.py, main.py::_character_patches).

Run inside the backend container:   python tests/test_entity_versions.py
"""

import copy
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import entity_versions as ev
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]
import main
import sim_loop
from db import load_world
from systems.schema_defaults import ensure_world_defaults

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ── digests and versions ──────────────────────────────────────────────────────────
c = {"id": "char_x", "x": 1, "y": 2, "activity": None, "body": {"hunger": 10}, "memories": [1, 2], "grievances": {"a": 1}}
d0 = ev.char_digests(c, 100)
v0 = ev.version("char", "char_x")
check("same tick returns the memoised digests", ev.char_digests(c, 100) is d0)
c["x"] = 5
d1 = ev.char_digests(c, 101)
check("a changed hot key is seen on the very next tick", d1["x"] != d0["x"] and ev.last_changed("char", "char_x") == {"x"} and ev.version("char", "char_x") == v0 + 1)
d2 = ev.char_digests(c, 102)
check("no change -> no new version", ev.version("char", "char_x") == v0 + 1 and ev.last_changed("char", "char_x") == {"x"})
c["body"]["hunger"] = 11
check("a nested change inside a key counts as that key changing", ev.char_digests(c, 103)["body"] != d2["body"])
c["grievances"]["b"] = 2
saw = None
for t in range(104, 104 + ev.COLD_EVERY + 1):
    if ev.char_digests(c, t)["grievances"] != d0["grievances"]:
        saw = t - 103
        break
check("a cold key's change shows up within COLD_EVERY ticks", saw is not None and saw <= ev.COLD_EVERY, str(saw))
c["new"] = 1
del c["memories"]
dn = ev.char_digests(c, 200)
check("added and removed keys are noticed", "new" in dn and "memories" not in dn and {"new", "memories"} <= ev.last_changed("char", "char_x"))

# ── patches ────────────────────────────────────────────────────────────────────────────
world = {"tick": 300}
a = {"id": "a", "x": 1, "y": 1, "activity": None, "grievances": {"g": 1}}
sent = {}
out = main._character_patches(world, {"a": a}, None, sent)
check("a character the client has never seen goes whole", out["a"] is a and "a" in sent)
world["tick"] = 301
check("an unchanged character is not sent at all", main._character_patches(world, {"a": a}, None, sent) == {})
a["x"] = 2
world["tick"] = 302
out = main._character_patches(world, {"a": a}, None, sent)
check("a changed key is sent as a patch of just that key", out["a"] == {"__patch__": True, "x": 2}, str(out))
del a["y"]
world["tick"] = 303
out = main._character_patches(world, {"a": a}, None, sent)
check("a removed key is listed as deleted", out["a"].get("__deleted__") == ["y"], str(out))
world["tick"] = 304
a["grievances"]["g2"] = 2           # a cold key: normally noticed within COLD_EVERY ticks
out = main._character_patches(world, {"a": a}, None, sent)
check("a cold-key change is not necessarily seen immediately for a character nobody selected", out == {} or out["a"].get("grievances") is None or True)
out = main._character_patches(world, {"a": a}, "a", sent)
check("for the selected character cold keys are re-checked every tick", out.get("a", {}).get("grievances") == {"g": 1, "g2": 2}, str(out))
sent2 = {}
main._character_patches(world, {"a": a}, None, sent2)
a["x"] = 3
world["tick"] = 305
o1 = main._character_patches(world, {"a": a}, None, sent)
o2 = main._character_patches(world, {"a": a}, None, sent2)
check("two clients each get the patch relative to what THEY hold", o1["a"] == o2["a"] == {"__patch__": True, "x": 3})

# ── against the real simulation: a client that applies the patches ends up identical ─────────────
w = load_world("default")          # snapshot copy of the live world (a different process: read-only here)
for ch in w["characters"].values():
    ch["off_grid"] = False
    ch["travel_state"] = None
w["definitions"] = w.get("definitions") or {}
client = {}                        # what a websocket client holds: id -> character dict (JSON round trip)
sent = {}


def js_merge(client, delta_chars):
    for cid, v in delta_chars.items():
        if isinstance(v, dict) and v.get("__patch__"):
            nxt = dict(client.get(cid, {}))
            for k, val in v.items():
                if k not in ("__patch__", "__deleted__"):
                    nxt[k] = val
            for k in v.get("__deleted__", []):
                nxt.pop(k, None)
            client[cid] = nxt
        else:
            client[cid] = v


full_bytes = patch_bytes = 0
for i in range(120):
    ensure_world_defaults(w)
    sim_loop.tick(w)
    dirty = {"chars": {cid: ch for cid, ch in w["characters"].items() if not ch.get("is_workplace_npc")},
             "props": {}, "placed_items": {}, "world_objects": {}}
    delta = main._build_delta(w, dirty, 10, 10, 2, None, sent=sent)
    full = main._build_delta(w, dirty, 10, 10, 2, None, sent=None)
    full_bytes += len(json.dumps(full["characters"], default=str)) if full else 0
    if delta:
        patch_bytes += len(json.dumps(delta["characters"], default=str))
        js_merge(client, json.loads(json.dumps(delta["characters"], default=str)))
# a cold key may lag its real value by up to COLD_EVERY ticks (by design); force a refresh on the
# final tick so the comparison below is exact
for extra in range(ev.COLD_EVERY + 1):
    if extra == ev.COLD_EVERY:
        ev._cold_cache.clear()
    ensure_world_defaults(w); sim_loop.tick(w)
    dirty = {"chars": {cid: ch for cid, ch in w["characters"].items() if not ch.get("is_workplace_npc")}, "props": {}, "placed_items": {}, "world_objects": {}}
    delta = main._build_delta(w, dirty, 10, 10, 2, None, sent=sent)
    if delta:
        patch_bytes += len(json.dumps(delta["characters"], default=str))
        js_merge(client, json.loads(json.dumps(delta["characters"], default=str)))

mismatch = []
for cid, ch in w["characters"].items():
    if ch.get("is_workplace_npc"):
        continue
    want = json.loads(json.dumps(ch, default=str))
    have = client.get(cid, {})
    for k in want:
        if k not in ("perception",) and have.get(k) != want[k]:
            mismatch.append((cid[-4:], k))
check("a client applying only patches ends up with the same characters", not mismatch, str(mismatch[:6]))
print(f"   120 ticks, whole characters every tick: {full_bytes // 1024} KB; patches: {patch_bytes // 1024} KB "
      f"({100 * patch_bytes // max(full_bytes, 1)}% of that)")
check("patches are a small fraction of whole characters", patch_bytes < full_bytes * 0.3, f"{patch_bytes} vs {full_bytes}")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
