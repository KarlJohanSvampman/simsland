"""
systems/spotted.py

What a character knows is around -- not only what is in front of them right now.

Since walls block sight, a character in the bedroom no longer sees the fridge, so "I'm hungry, I'll get something
from the fridge" had nothing to reach for. People don't plan from what's in view: they're hungry, they think of the
kitchen and the fridge in it. Two things make that possible here:

  - their own home is familiar: everything in it is known, wherever they are;
  - elsewhere they remember what they happened to notice (c["spotted"]): each time they look around
    (perception, every few ticks) a thing in view that they don't know yet is noticed by chance -- likelier close
    up -- and a thing they already know is refreshed (where it is now, when they last saw it). Things used or
    examined are always noticed. People in view have where they were last seen kept (c["last_seen"]).
    Old sightings are dropped past MAX_SPOTTED.

How it's used:

  - what they need, most pressing first, brings to mind the known things that would help (what satisfies each
    intention: brain/intention_needs.py), and where they are
    ("To eat: the fridge and the microwave in your kitchen.") -- prompt section "known_places";
  - a pressing plan about a person brings to mind where that person was last seen;
  - a remembered thing can be named as a target (brain/action_resolver.py's "remembered_props" pool): walking to
    it, or using it, works the same as for a thing in view -- they walk there first.

Spontaneous choices still come from what is seen (the "Things here" list) -- or from being reminded of something.
"""

import random
import re

MAX_SPOTTED = 80
NOTICE_CHANCE = 0.04            # per look (every few ticks), for a thing in view they don't know yet...
NOTICE_CHANCE_CLOSE = 0.15      # ...or one within CLOSE_TILES
CLOSE_TILES = 2.5
RECALL_PER_NEED = 3
NEEDS_SHOWN = 3

# =========================================================
# NOTICING
# =========================================================

def _prop_entry(world, p, tick):
    from brain.perception import build_prop_tags
    from systems.room_assignment import room_at
    tags, interactions = build_prop_tags(p, world.get("definitions", {}))
    return {"template": p.get("template"), "tags": list(tags or []), "interactions": list(interactions or []),
            "x": p.get("x"), "y": p.get("y"), "room_id": room_at(world, p.get("x", 0), p.get("y", 0)),
            "tick": tick}


def notice(c, world, prop):
    """c takes note of this prop (always -- used, examined, looked at closely)."""
    if not prop or not prop.get("id"):
        return
    known = c.setdefault("spotted", {})
    known[prop["id"]] = _prop_entry(world, prop, world.get("tick", 0))
    _trim(known)


def _trim(known):
    if len(known) > MAX_SPOTTED:
        for pid, _ in sorted(known.items(), key=lambda kv: kv[1].get("tick", 0))[:len(known) - MAX_SPOTTED]:
            known.pop(pid, None)


def on_perceive(c, world, visible_props, visible_people):
    """After a look around (brain/perception.perceive): notice some of what's in view, refresh what's known."""
    from systems.props import get_prop_by_id
    tick = world.get("tick", 0)
    known = c.setdefault("spotted", {})
    home = _home_buildings(c, world)
    for vp in visible_props or []:
        pid = vp.get("id")
        if not pid:
            continue
        if pid in known:
            known[pid]["tick"] = tick
            p = get_prop_by_id(world, pid)
            if p and (known[pid].get("x"), known[pid].get("y")) != (p.get("x"), p.get("y")):
                known[pid].update(_prop_entry(world, p, tick))
            continue
        p = get_prop_by_id(world, pid)
        if not p or p.get("building_id") in home:
            continue                                 # their own home's things are known anyway
        chance = NOTICE_CHANCE_CLOSE if (vp.get("distance") or 99) <= CLOSE_TILES else NOTICE_CHANCE
        if random.random() < chance:
            known[pid] = _prop_entry(world, p, tick)
    _trim(known)
    last = c.setdefault("last_seen", {})
    chars = world.get("characters") or {}
    for person in visible_people or []:
        other = chars.get(person.get("id"))
        if other:
            last[other["id"]] = {"room_id": other.get("room_id"), "building_id": other.get("_in_building"),
                                 "x": other.get("x"), "y": other.get("y"), "tick": tick}


# =========================================================
# WHAT THEY KNOW OF
# =========================================================

def _home_buildings(c, world):
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    out = set(hh.get("building_ids") or [])
    if hh.get("home_id"):
        out.add(hh["home_id"])
    residence = c.get("temporary_residence") or {}
    host = (world.get("characters") or {}).get(residence.get("host_id"))
    if host:
        host_hh = (world.get("households") or {}).get(host.get("household_id")) or {}
        out |= set(host_hh.get("building_ids") or [])
        if host_hh.get("home_id"):
            out.add(host_hh["home_id"])
    return out


def known_props(c, world):
    """{prop id: entry} of everything c knows is around: their home, and what they've noticed elsewhere."""
    from systems.room_assignment import room_at
    from systems.navigation import find_building_at
    out = {}
    home = _home_buildings(c, world)
    if home:
        tick = world.get("tick", 0)
        for p in world.get("props") or []:
            bid = p.get("building_id") or (str(p.get("room_id")).split(":", 1)[0] if p.get("room_id") else None)
            if bid is None and p.get("x") is not None:
                b, _ = find_building_at(world, int(round(p["x"])), int(round(p["y"])))
                bid = b["id"] if b else None
            if bid in home:
                entry = (c.get("spotted") or {}).get(p["id"]) or _prop_entry(world, p, tick)
                out[p["id"]] = entry
    for pid, entry in (c.get("spotted") or {}).items():
        out.setdefault(pid, entry)
    return out


def _where(c, world, entry):
    room_id = entry.get("room_id")
    if not room_id:
        return "outside"
    bid, room = room_id.split(":", 1) if ":" in room_id else (None, room_id)
    room_label = re.sub(r"_\d+$", "", room).replace("_", " ")
    if bid in _home_buildings(c, world):
        return f"your {room_label}"
    for hh in (world.get("households") or {}).values():
        if hh.get("home_id") == bid or bid in (hh.get("building_ids") or []):
            name = re.sub(r"^the (\w+) household$", r"the \1s'", hh.get("name") or "", flags=re.I)
            return f"{name or 'someone else'}'s {room_label}" if not name.endswith("'") else f"{name} {room_label}"
    return f"the {room_label}"


def _label(entry):
    return re.sub(r"_[a-z]$", "", str(entry.get("template") or "thing")).replace("_", " ")


def things_for(c, world, intention_type, exclude=()):
    """[(prop id, entry)] of known things that would help with this intention (brain/intention_needs.py's
    SATISFIED_BY): the better kind first, the nearer of a kind first."""
    from brain.intention_needs import satisfied_by
    wants = satisfied_by(intention_type)
    if not wants:
        return []
    rank = {w: n for n, w in enumerate(wants)}
    cx, cy = c.get("x", 0), c.get("y", 0)
    hits = []
    for pid, e in known_props(c, world).items():
        if pid in exclude:
            continue
        offered = [rank[i] for i in e.get("interactions") or [] if i in rank]
        if offered:
            hits.append((min(offered), (e.get("x", 0) - cx) ** 2 + (e.get("y", 0) - cy) ** 2, pid, e))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [(pid, e) for _, _, pid, e in hits[:RECALL_PER_NEED]]


def remembered_pool(c, world, exclude=()):
    """Known things not in view, nearest first, as target candidates for brain/action_resolver.py."""
    cx, cy = c.get("x", 0), c.get("y", 0)
    items = sorted(known_props(c, world).items(),
                   key=lambda kv: (kv[1].get("x", 0) - cx) ** 2 + (kv[1].get("y", 0) - cy) ** 2)
    return [{"id": pid, "template": e.get("template"), "tags": e.get("tags") or [],
             "interactions": e.get("interactions") or [], "remembered": True, "where": _where(c, world, e)}
            for pid, e in items if pid not in exclude]


def context_lines(c, world):
    """What their pressing needs and plans bring to mind: the known things that would help (not already in view),
    and where; for a plan about a person, where they were last seen."""
    from systems.todo import todo_list
    in_view = {p.get("id") for p in (c.get("perception") or {}).get("visible_props") or []}
    visible_people = {p.get("id") for p in (c.get("perception") or {}).get("visible_people") or []}
    chars = world.get("characters") or {}
    lines, said_people, said_props = [], set(), set()
    for i in todo_list(c)["pressing"][:NEEDS_SHOWN]:
        target = chars.get(i.get("target_id"))
        if target and target["id"] not in visible_people and target["id"] not in said_people:
            seen = (c.get("last_seen") or {}).get(target["id"])
            if seen:
                minutes = max(0, (world.get("tick", 0) - seen.get("tick", 0)) // 60)
                ago = "just now" if minutes < 1 else (f"{minutes} minutes ago" if minutes < 120 else
                                                      f"{minutes // 60} hours ago")
                lines.append(f"You last saw {target.get('name')} in {_where(c, world, seen)}, {ago}.")
                said_people.add(target["id"])
            continue
        hits = [(pid, e) for pid, e in things_for(c, world, i.get("type"), exclude=in_view) if pid not in said_props]
        if not hits:
            continue
        said_props.update(pid for pid, _ in hits)
        need = re.sub(r"^expectation:", "", str(i.get("type") or "")).replace("_", " ")
        things = ", ".join(f"the {_label(e)} ({_where(c, world, e)})" for _, e in hits)
        lines.append(f"For {need}, you know of: {things}.")
    return lines
