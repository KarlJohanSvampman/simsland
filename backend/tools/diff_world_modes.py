"""
Differential check for the in-memory world (core/world_state.py): run the same seeded sim twice,
once with the old per-tick JSON round trip and once with the world kept in memory, and diff the
final states after normalising both through JSON.

    python tools/diff_world_modes.py [ticks] [start-datetime]
    python tools/diff_world_modes.py 1500 2026-11-01T23:50:00     # crosses a week boundary

Needs a populated world snapshot at /tmp/backup_world.json (a file from backups/). The clock, uuids and
workers are made deterministic. Last run (1500 ticks across Monday midnight): 4 differences, all one
"once per day" guard that compared a tuple with the list it had become after the round trip.
"""

import sys, json, copy, random, time, uuid, itertools, collections, traceback

sys.path.insert(0, "/app")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400

from db import load_world, _STATIC_WORLD_KEYS
from core.definitions import load_definitions
import core.event_handlers  # noqa
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]

# ---- determinism: fake clock, counter uuids, synchronous workers -----------------------------
class Det:
    def __init__(self):
        self.reset()
    def reset(self):
        self.t = 1.7e9
        self.n = itertools.count(1)
DET = Det()
time.time = lambda: DET.t
class _U:
    def __init__(self, i): self.hex = f"{i:032x}"; self.int = i
    def __str__(self): return f"{self.hex[:8]}-0000-0000-0000-{self.hex[-12:]}"
uuid.uuid4 = lambda: _U(next(DET.n))

import brain.cognition_actor as ca
class _Inline:
    def submit(self, fn, *a, **k):
        fn(*a, **k)
ca._pool = _Inline()
import brain.llm_brain as lb
lb.think = lambda context, char_id=None, session=None, priority=None: {"thought": "ok", "action": {"type": "wait", "reason": "x"}}
from systems import bg_llm
bg_llm.submit = lambda key, fn, *a: (bg_llm._done.__setitem__(key, None), True)[1]
import sim_loop
from systems.schema_defaults import ensure_world_defaults

live = load_world("default")
STATIC = set(_STATIC_WORLD_KEYS)


def fixture():
    w = json.load(open("/tmp/backup_world.json", encoding="utf-8"))
    for k in STATIC:
        if k in live:
            w[k] = live[k]
    w["definitions"] = load_definitions("default")
    for c in w["characters"].values():
        c["off_grid"] = False
        c["travel_state"] = None
        c.pop("_body_lazy", None)
    w.pop("timers", None)
    if len(sys.argv) > 2:
        from datetime import datetime
        w["sim_time"] = datetime.fromisoformat(sys.argv[2]).timestamp()
    return w


def roundtrip(w):
    static = {k: w[k] for k in STATIC if k in w}
    rest = json.loads(json.dumps({k: v for k, v in w.items() if k not in STATIC}, default=str))
    rest.update(static)
    return rest


def run(mode):
    DET.reset(); random.seed(1234)
    import brain.intentions as _bi
    _bi._intention_seq = 0
    w = fixture()
    w = roundtrip(w)
    errs = collections.Counter()
    for i in range(N):
        ensure_world_defaults(w)
        DET.t += 1.0
        try:
            sim_loop.tick(w)
        except Exception:
            errs[traceback.format_exc().strip().splitlines()[-1]] += 1
        if mode == "roundtrip":
            w = roundtrip(w)
    return w, errs


def norm(w):
    return json.loads(json.dumps({k: v for k, v in w.items() if k not in STATIC and k not in ("definitions", "_dirty")}, default=str, sort_keys=True))


def diff(a, b, path="", out=None, limit=40):
    out = out if out is not None else []
    if len(out) >= limit:
        return out
    if type(a) != type(b):
        out.append((path, f"type {type(a).__name__} vs {type(b).__name__}", str(a)[:60], str(b)[:60])); return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a: out.append((f"{path}/{k}", "only in resident", "", str(b[k])[:60]))
            elif k not in b: out.append((f"{path}/{k}", "only in roundtrip", str(a[k])[:60], ""))
            else: diff(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, f"len {len(a)} vs {len(b)}", "", ""))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append((path, "value", str(a)[:60], str(b)[:60]))
    return out


t0 = time.perf_counter(); wa, ea = run("roundtrip"); ta = time.perf_counter() - t0
t0 = time.perf_counter(); wb, eb = run("resident"); tb = time.perf_counter() - t0
print(f"{N} ticks: roundtrip {ta:.1f}s (exceptions {dict(ea) or 'none'}) | resident {tb:.1f}s (exceptions {dict(eb) or 'none'})")
d = diff(norm(wa), norm(wb))
print("differences after normalising both through JSON:", len(d) if len(d) < 40 else "40+")
for row in d[:25]:
    print("  ", row)
