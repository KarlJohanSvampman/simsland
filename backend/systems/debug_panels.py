"""
systems/debug_panels.py -- debug panels (widgets) for any entity: templates, who they apply to, and per-entity layouts.

Stored in simulations/<sim>/debug_panels.json (a debugging tool's settings, not world state):

    {"templates": [template, ...], "entities": {"character:c1": entity_layouts, ...}}

A template (a widget):
    {"id", "name", "type": "table" | "line" | "pie" | "bar" | "tree" | "text",
     "source": {"path": "trait_log", "refresh_s": 2},      -- a path into the entity (see data_at), refreshed this often
     "options": {...},                                      -- per type (frontend/src/panels/render.js)
     "assign": {"scope": "all" | "kinds" | "entities", "kinds": ["character", ...], "entities": ["character:c1", ...]},
     "default_state": "enabled" | "disabled" | "on_demand"} -- on_demand: shown only while there is something to show

An entity's layouts -- which panels it has and in what state; one active, up to MAX_ALTERNATIVES others:
    {"active": "Default", "layouts": {"Default": {"panels": {template_id: state}}, "Social": {...}}}

A template applies to an entity if its assignment covers it, or if one of the entity's layouts lists it (a panel added to
just this one). With no layouts saved, an entity shows every template that applies, in its default state.
"""

import json
import os
import re

from core.definitions import BASE

TYPES = ("table", "line", "pie", "bar", "tree", "text")
STATES = ("enabled", "disabled", "on_demand")
KINDS = ("character", "prop", "household", "building", "item")
MAX_ALTERNATIVES = 5                    # one active layout + this many others
_cache = {}


def path(sim_id="default"):
    return BASE / sim_id / "debug_panels.json"


def load(sim_id="default"):
    p = path(sim_id)
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return {"templates": [], "entities": {}}
    hit = _cache.get(sim_id)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("templates", [])
    data.setdefault("entities", {})
    _cache[sim_id] = (mtime, data)
    return data


def save(data, sim_id="default"):
    p = path(sim_id)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)
    _cache.pop(sim_id, None)


def entity_key(kind, eid):
    return f"{kind}:{eid}"


# ── templates ──────────────────────────────────────────────────────────────────────────────────────────────────────

def check_template(t):
    """Problems with a template (empty list: fine)."""
    probs = []
    if not re.fullmatch(r"[a-z0-9_\-]{1,64}", str(t.get("id") or "")):
        probs.append("the id must be 1-64 lowercase letters, digits, - or _")
    if t.get("type") not in TYPES:
        probs.append(f"type must be one of {', '.join(TYPES)}")
    if t.get("default_state", "enabled") not in STATES:
        probs.append(f"default_state must be one of {', '.join(STATES)}")
    a = t.get("assign") or {}
    if a.get("scope", "all") not in ("all", "kinds", "entities"):
        probs.append("assign.scope must be all, kinds or entities")
    if any(k not in KINDS for k in a.get("kinds") or []):
        probs.append(f"assign.kinds may only hold {', '.join(KINDS)}")
    if not isinstance((t.get("source") or {}).get("path", ""), str):
        probs.append("source.path must be a string")
    return probs


def put_template(data, t):
    t = dict(t)
    t.setdefault("default_state", "enabled")
    t.setdefault("assign", {"scope": "all"})
    t.setdefault("source", {"path": "", "refresh_s": 2})
    t.setdefault("options", {})
    data["templates"] = [x for x in data["templates"] if x.get("id") != t["id"]] + [t]
    return t


def delete_template(data, tid):
    data["templates"] = [x for x in data["templates"] if x.get("id") != tid]
    for ent in data["entities"].values():                 # and out of every layout that listed it
        for lay in (ent.get("layouts") or {}).values():
            (lay.get("panels") or {}).pop(tid, None)


def _assigned(t, kind, key):
    a = t.get("assign") or {"scope": "all"}
    scope = a.get("scope", "all")
    if scope == "all":
        return True
    if scope == "kinds":
        return kind in (a.get("kinds") or [])
    return key in (a.get("entities") or [])


# ── an entity's panels and layouts ─────────────────────────────────────────────────────────────────────────────────

def for_entity(data, kind, eid):
    """What the entity shows: the templates that apply, its layouts, the active one, and each panel's state in it."""
    key = entity_key(kind, eid)
    ent = data["entities"].get(key) or {}
    layouts = ent.get("layouts") or {}
    listed = {tid for lay in layouts.values() for tid in (lay.get("panels") or {})}
    by_id = {t["id"]: t for t in data["templates"]}
    applicable = [t for t in data["templates"] if _assigned(t, kind, key) or t["id"] in listed]
    active = ent.get("active") if ent.get("active") in layouts else None
    if active:
        # the state saved in the active layout; a template assigned after it was saved shows in its default state
        given = layouts[active].get("panels") or {}
        states = {t["id"]: given.get(t["id"], t.get("default_state", "enabled")) for t in applicable}
    else:
        states = {t["id"]: t.get("default_state", "enabled") for t in applicable}
    return {"key": key, "kind": kind, "id": eid, "templates": applicable, "states": states,
            "active": active or "Default", "layouts": layouts or {"Default": {"panels": dict(states)}},
            "missing": sorted(tid for tid in listed if tid not in by_id)}


def set_layouts(data, kind, eid, body):
    """Save an entity's layouts: {"active": name, "layouts": {name: {"panels": {tid: state}}}}. Returns problems."""
    layouts = body.get("layouts") or {}
    probs = []
    if not layouts:
        probs.append("at least one layout")
    if len(layouts) > 1 + MAX_ALTERNATIVES:
        probs.append(f"at most {1 + MAX_ALTERNATIVES} layouts (one active and {MAX_ALTERNATIVES} alternatives)")
    if body.get("active") not in layouts:
        probs.append("the active layout must be one of the layouts")
    ids = {t["id"] for t in data["templates"]}
    for name, lay in layouts.items():
        if not str(name).strip():
            probs.append("a layout needs a name")
        for tid, st in (lay.get("panels") or {}).items():
            if st not in STATES:
                probs.append(f"{name}: {tid} has state '{st}'")
            if tid not in ids:
                probs.append(f"{name}: no panel template '{tid}'")
    if probs:
        return probs
    data["entities"][entity_key(kind, eid)] = {"active": body["active"],
                                               "layouts": {str(n): {"panels": dict(l.get("panels") or {})} for n, l in layouts.items()}}
    return []


# ── data: a path into any entity ───────────────────────────────────────────────────────────────────────────────────

def find_entity(world, kind, eid):
    if kind == "character":
        return (world.get("characters") or {}).get(eid)
    if kind == "household":
        return (world.get("households") or {}).get(eid)
    if kind == "prop":
        return next((p for p in world.get("props") or [] if p.get("id") == eid), None)
    if kind == "building":
        return next((b for b in world.get("buildings") or [] if b.get("id") == eid), None)
    if kind == "item":                                    # carried by someone, or in a prop's storage
        def walk(o, depth=0):
            if depth > 6:
                return None
            if isinstance(o, dict):
                if o.get("id") == eid and ("template_id" in o or "object_type" in o or "name" in o):
                    return o
                for v in o.values():
                    hit = walk(v, depth + 1)
                    if hit is not None:
                        return hit
            elif isinstance(o, list):
                for v in o:
                    hit = walk(v, depth + 1)
                    if hit is not None:
                        return hit
            return None
        for c in (world.get("characters") or {}).values():
            hit = walk({"inventory": c.get("inventory"), "worn": c.get("worn"), "items": c.get("personal_items")})
            if hit is not None:
                return hit
        for p in world.get("props") or []:
            hit = walk(p.get("storage"))
            if hit is not None:
                return hit
    return None


def data_at(obj, dotted):
    """The value at a dot path ("body.hunger", "trait_log", "memories.3.content"); None if it isn't there."""
    cur = obj
    for part in [p for p in str(dotted or "").split(".") if p != ""]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and re.fullmatch(r"-?\d+", part):
            i = int(part)
            cur = cur[i] if -len(cur) <= i < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def fields(obj, depth=2, list_sample=1):
    """A browsable outline of an entity's data, for picking a path: {key: {"type", "size"?, "children"?}}."""
    def describe(v, d):
        if isinstance(v, dict):
            out = {"type": "object", "size": len(v)}
            if d > 0:
                out["children"] = {str(k): describe(x, d - 1) for k, x in list(v.items())[:200]}
            return out
        if isinstance(v, list):
            out = {"type": "list", "size": len(v)}
            if d > 0 and v and list_sample:
                out["item"] = describe(v[-1], d - 1)       # what an entry looks like (the newest)
            return out
        return {"type": type(v).__name__ if v is not None else "null", "sample": v if isinstance(v, (int, float, bool)) or v is None
                else str(v)[:60]}
    return describe(obj, depth).get("children", {}) if isinstance(obj, dict) else {}
