"""Shared bits for social/: where a pair's state lives, names, events, the history line."""

from core.event_bus import emit as _emit

DAY = 86400
LOG_CAP = 160


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def now(world):
    return world.get("tick", 0)


def chars(world):
    return world.get("characters") or {}


def name(world, cid):
    c = chars(world).get(cid)
    return (c or {}).get("name") or "someone"


def first(world, cid):
    return name(world, cid).split(" ")[0]


def rel(c, oid, create=True):
    rels = c.setdefault("relationships", {}) if create else (c.get("relationships") or {})
    if create:
        return rels.setdefault(oid, {})
    return rels.get(oid) or {}


def emit(kind, data):
    try:
        _emit(kind, data)
    except Exception:
        pass


def id_by_name(world, nm, among=None):
    """A character id from a name the AI wrote ("Robert", "Robert Okafor")."""
    if not nm:
        return None
    nm = str(nm).strip().lower()
    pool = among if among is not None else list(chars(world).keys())
    for cid in pool:
        n = (chars(world).get(cid) or {}).get("name") or ""
        if n.lower() == nm:
            return cid
    for cid in pool:
        n = (chars(world).get(cid) or {}).get("name") or ""
        if n and n.split(" ")[0].lower() == nm.split(" ")[0]:
            return cid
    return None


def note(c, oid, world, cause):
    """A point on c's history with oid: standing, frustration and how worked up they are, and why it moved."""
    if not oid or oid == c.get("id"):
        return
    from social import standing, frustration
    r = rel(c, oid)
    log = r.setdefault("standing_log", [])
    f = frustration.value(c, oid, world)
    log.append({"tick": now(world), "standing": round(standing.score(c, oid), 1),
                "frustration": round(f["score"], 1), "agitation": round(f["intensity"], 1),
                "cause": str(cause or "")[:160]})
    del log[:-LOG_CAP]
