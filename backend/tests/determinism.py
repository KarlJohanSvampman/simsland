"""
Deterministic seeded runs of the real simulation, for differential tests.

    from tests.determinism import run_sim, diff, norm

run_sim(ticks, start="2026-11-01T23:50:00", setup=None, checkpoint_every=None, before_tick=None)
returns (world, errors, checkpoints). The clock, uuids and worker threads are made
deterministic, the LLM is a fixed "wait", and the world starts from /tmp/backup_world.json
(a populated snapshot from backups/) with the live static map data.
"""

import collections
import itertools
import json
import random
import sys
import time
import traceback
import uuid

import os
os.environ.setdefault("COGNITION_MODE", "local")     # never reach a live cognition worker
sys.path.insert(0, "/app")

from db import load_world, _STATIC_WORLD_KEYS
from core.definitions import load_definitions
import core.event_handlers  # noqa: F401
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]

STATIC = set(_STATIC_WORLD_KEYS)
ERROR_TRACES = {}                       # last line of an exception -> its first full traceback (see run_sim)
_real_time = time.time
_installed = False


class _Clock:
    t = 1.7e9
    counter = itertools.count(1)


class _U:
    def __init__(self, i):
        self.hex = f"{i:032x}"
        self.int = i

    def __str__(self):
        return f"{self.hex[:8]}-0000-0000-0000-{self.hex[-12:]}"


def _install():
    global _installed
    if _installed:
        return
    _installed = True
    time.time = lambda: _Clock.t
    uuid.uuid4 = lambda: _U(next(_Clock.counter))
    import brain.cognition_actor as ca

    class _Inline:
        def submit(self, fn, *a, **k):
            fn(*a, **k)
    ca._pool = _Inline()
    import brain.llm_brain as lb
    lb.think = lambda context, char_id=None, session=None, priority=None: {"thought": "ok", "action": {"type": "wait", "reason": "x"}}
    from systems import bg_llm
    bg_llm.submit = lambda key, fn, *a: (bg_llm._done.__setitem__(key, None), True)[1]


def _fixture_path():
    """/tmp/backup_world.json if someone put one there, else the populated snapshot in the mounted backups/ folder."""
    import glob
    import os
    if os.path.exists("/tmp/backup_world.json"):
        return "/tmp/backup_world.json"
    found = sorted(glob.glob("/backups/world_default_before_reset_*.json"), reverse=True)    # newest first
    if not found:
        raise FileNotFoundError("no /tmp/backup_world.json and no /backups/world_default_before_reset_*.json (mount ./backups)")
    return found[0]


def fixture(start=None):
    live = load_world("default")
    w = json.load(open(_fixture_path(), encoding="utf-8"))
    for k in STATIC:
        if k in live:
            w[k] = live[k]
    w["definitions"] = load_definitions("default")
    # Rooms must resolve the same way in every process, whatever the live world's buildings were or whichever branch
    # of the world loader ran (it depends on whether another process loaded the world in the last 5 seconds).
    from systems.building_manager import prime_nav_cache
    prime_nav_cache(w, force=True)
    for c in w["characters"].values():
        c["off_grid"] = False
        c["travel_state"] = None
        c.pop("_body_lazy", None)
    w.pop("timers", None)
    if start:
        from datetime import datetime
        w["sim_time"] = datetime.fromisoformat(start).timestamp()
    return w


def run_sim(ticks, start="2026-11-01T23:50:00", seed=1234, setup=None, checkpoint_every=None, checkpoint_fn=None):
    _install()
    import sim_loop
    import brain.intentions as _bi
    from systems.schema_defaults import ensure_world_defaults
    _Clock.t = 1.7e9
    _Clock.counter = itertools.count(1)
    random.seed(seed)
    _bi._intention_seq = 0
    w = fixture(start)
    if setup:
        setup(w)
    errs = collections.Counter()
    checkpoints = []
    for i in range(ticks):
        ensure_world_defaults(w)
        _Clock.t += 1.0
        try:
            sim_loop.tick(w)
        except Exception:
            text = traceback.format_exc().strip()
            errs[text.splitlines()[-1]] += 1
            ERROR_TRACES.setdefault(text.splitlines()[-1], text)         # first full traceback of each kind, for debugging
        if checkpoint_every and (i + 1) % checkpoint_every == 0 and checkpoint_fn:
            checkpoints.append((i + 1, checkpoint_fn(w)))
    return w, errs, checkpoints


def norm(w, drop=("definitions", "_dirty")):
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k not in drop}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    body = {k: v for k, v in w.items() if k not in STATIC and k not in drop}
    return json.loads(json.dumps(strip(body), default=str, sort_keys=True))


def diff(a, b, path="", out=None, limit=40):
    out = out if out is not None else []
    if len(out) >= limit:
        return out
    if type(a) != type(b):
        out.append((path, f"type {type(a).__name__} vs {type(b).__name__}", str(a)[:60], str(b)[:60]))
        return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((f"{path}/{k}", "only in B", "", str(b[k])[:60]))
            elif k not in b:
                out.append((f"{path}/{k}", "only in A", str(a[k])[:60], ""))
            else:
                diff(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, f"len {len(a)} vs {len(b)}", "", ""))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append((path, "value", str(a)[:60], str(b)[:60]))
    return out
