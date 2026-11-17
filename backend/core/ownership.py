"""
core/ownership.py -- which partition owns which entity (docs/step5b_plan.md: partitioned ownership).

Partition 0 is the core: the world-level keys and services, and every entity no household owns (conversations, CPL
conversations and requests, public props, characters without a household). Partitions 1..n-1 each own a share of the
households: the household, its members, and the props in its buildings.

    assign(world, n)                  spread the households over partitions 1..n-1 (n=1: everything is partition 0)
    owner_of(world, kind, id)         the owning partition (0 for anything not in the map)
    owned_by(world, p)                {(kind, id)} partition p owns (besides partition 0's everything-else)
    move_household(world, hid, p)     hand a household and what comes with it to another partition

world["_owners"] = {"n": n, "characters": {id: p}, "households": {id: p}, "props": {id: p}} -- on the world, so every
partition reads the same map from its replica.
"""

KINDS = ("characters", "households", "props")


def _map(world):
    m = world.get("_owners")
    if m is None:
        world["_owners"] = m = {"n": 1, "characters": {}, "households": {}, "props": {}}
    return m


def _members(world, hid):
    h = (world.get("households") or {}).get(hid) or {}
    return list(h.get("members") or [])


def _props_of(world, hid):
    h = (world.get("households") or {}).get(hid) or {}
    bids = set(h.get("building_ids") or [])
    return [p.get("id") for p in list.__iter__(world.get("props") or []) if isinstance(p, dict)
            and p.get("id") and p.get("building_id") in bids]


def assign(world, n):
    """Spread households round-robin over partitions 1..n-1, in id order (deterministic)."""
    m = {"n": int(n), "characters": {}, "households": {}, "props": {}}
    world["_owners"] = m
    if n <= 1:
        return m
    for i, hid in enumerate(sorted(dict.keys(world.get("households") or {}))):
        _give(world, m, hid, 1 + i % (n - 1))
    return m


def _give(world, m, hid, p):
    m["households"][hid] = p
    for cid in _members(world, hid):
        c = dict.get(world.get("characters") or {}, cid) or {}
        if not c.get("is_workplace_npc"):
            m["characters"][cid] = p
    for pid in _props_of(world, hid):
        m["props"][pid] = p


def owner_of(world, kind, eid):
    return ((world.get("_owners") or {}).get(kind) or {}).get(eid, 0)


def owned_by(world, p):
    m = world.get("_owners") or {}
    return {(k, i) for k in KINDS for i, q in (m.get(k) or {}).items() if q == p}


def move_household(world, hid, p):
    """Hand a household (members, props) to partition p. The caller sees to the handover of their state (slice 4)."""
    m = _map(world)
    for k in KINDS:
        for eid in [e for e, q in m[k].items() if (k == "households" and e == hid)
                    or (k == "characters" and e in _members(world, hid))
                    or (k == "props" and e in _props_of(world, hid))]:
            del m[k][eid]
    _give(world, m, hid, p)
    return m
