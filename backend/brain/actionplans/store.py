"""simulations/<sim>/behaviour.json -- loaded once and re-read when the file changes (the admin page writes it)."""

import json
import os

from core.definitions import BASE

KINDS = ("drives", "intentions", "requirements", "plans", "variables")
_cache = {}          # sim_id -> (mtime, data)


def path(sim_id="default"):
    return BASE / sim_id / "behaviour.json"


def load(sim_id="default"):
    p = path(sim_id)
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return {k: [] for k in KINDS}
    hit = _cache.get(sim_id)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    for k in KINDS:
        data.setdefault(k, [])
    _cache[sim_id] = (mtime, data)
    return data


def save(data, sim_id="default"):
    p = path(sim_id)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)
    _cache.pop(sim_id, None)


def by_id(data, kind):
    return {o["id"]: o for o in data.get(kind) or []}


def get(data, kind, oid):
    return by_id(data, kind).get(oid)
