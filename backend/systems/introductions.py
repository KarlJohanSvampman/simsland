"""
systems/introductions.py -- meeting people through people you already know.

Two strangers who are both in view of a mutual friend can be introduced by them. The friend vouches: the two start out
with more familiarity, trust and friendship than a cold first meeting gives, and they know who introduced them. This is
how a child meets the friend of a friend and how an adult gets to know a neighbour's colleague.

Every INTRO_CADENCE ticks, for each character M (the introducer) who can see at least two people: a pair (A, B) of those
people qualifies when
  - A and B are both children or both grown-ups, awake, on the grid, not family and have not really met
    (little interaction history, no friendship yet, never introduced);
  - M is on good terms with both (friendship >= MIN_FRIENDSHIP, no hostility, no open grudge either way) and each of
    them thinks well enough of M to take the word of M (friendship >= MIN_VOUCH);
  - M is awake and not doing something that can't be interrupted.
One pair per introducer per check, with probability INTRO_CHANCE (friendly/outgoing traits raise it, shy/reserved lower it).

The introduction ties the pair mutually (systems/neighbours.py::_tie, label "introduced", `introduced_by` on each side),
scaled by how much each trusts M, stores a memory for all three, and is logged in world["introductions"] so it only
happens once per pair.
"""

import random

from systems.neighbours import _is_person, _tie, KID_AGES

INTRO_CHANCE = 0.25
MIN_FRIENDSHIP = 15           # the introducer's regard for each of the two (children: KID_MIN_FRIENDSHIP)
KID_MIN_FRIENDSHIP = 10
MIN_VOUCH = 10                # each newcomer's regard for the introducer
MAX_STRANGER_INTERACTIONS = 1
MAX_STRANGER_FRIENDSHIP = 8
MAX_LOG = 500
INTRO_SCALE = {"familiarity": (6, 6), "friendship": (2, 5), "trust": (2, 5), "comfort": (0, 2)}
OUTGOING = {"extroverted", "friendly", "talkative", "charismatic", "sociable", "warm", "gossipy"}
RESERVED = {"shy", "introverted", "reserved", "secretive", "private", "antisocial", "anxious"}


def _is_child(c):
    age = c.get("age")
    return age is not None and KID_AGES[0] <= age <= KID_AGES[1]


def _rel(c, other_id):
    return (c.get("relationships") or {}).get(other_id) or {}


def _available(c):
    return _is_person(c) and not c.get("off_grid") and (c.get("activity") or {}).get("type") != "sleep"


def _key(a_id, b_id):
    return "|".join(sorted((a_id, b_id)))


def _strangers(world, a, b):
    """True if the two have not really met."""
    if (world.get("introductions") or {}).get(_key(a["id"], b["id"])) is not None:
        return False
    for x, y in ((a, b), (b, a)):
        r = _rel(x, y["id"])
        if r.get("kinship") or (r.get("interaction_count", 0) or 0) > MAX_STRANGER_INTERACTIONS \
                or (r.get("friendship", 0) or 0) >= MAX_STRANGER_FRIENDSHIP or "introduced" in (r.get("labels") or []):
            return False
    return True


def _vouches(world, m, x):
    """How far M can vouch for X, 0 if not at all: M's regard for X, X's regard for M."""
    r_mx, r_xm = _rel(m, x["id"]), _rel(x, m["id"])
    floor = KID_MIN_FRIENDSHIP if _is_child(m) else MIN_FRIENDSHIP
    if (r_mx.get("friendship", 0) or 0) < floor or (r_xm.get("friendship", 0) or 0) < MIN_VOUCH:
        return 0.0
    if (r_mx.get("hostility", 0) or 0) >= 10 or (r_xm.get("hostility", 0) or 0) >= 10:
        return 0.0
    from systems import grudges
    if m["id"] in {g["offender"] for g in grudges.open_grudges(x)} or x["id"] in {g["offender"] for g in grudges.open_grudges(m)}:
        return 0.0
    return max(0.2, min(1.0, ((r_xm.get("trust", 0) or 0) + (r_xm.get("friendship", 0) or 0)) / 80.0))


def _chance(m):
    traits = set(m.get("traits") or [])
    f = 1.0
    if traits & OUTGOING:
        f *= 1.5
    if traits & RESERVED:
        f *= 0.4
    return INTRO_CHANCE * f


def introduce(world, m, a, b, strength):
    """Make the introduction. Returns True if the pair was tied."""
    tick = world.get("tick", 0)
    if not _tie(world, a, b, INTRO_SCALE, strength, label="introduced"):
        return False
    for x in (a, b):
        _rel(x, (b if x is a else a)["id"])["introduced_by"] = m["id"]
    log = world.setdefault("introductions", {})
    log[_key(a["id"], b["id"])] = tick
    for old in sorted(log, key=log.get)[:max(0, len(log) - MAX_LOG)]:
        log.pop(old, None)
    try:
        from brain.memory import store_memory
        store_memory(a, f"{m['name']} introduced me to {b['name']}.", importance=0.35, tags=["introduction"],
                     people=[m["id"], b["id"]], tick=tick, source="heard")
        store_memory(b, f"{m['name']} introduced me to {a['name']}.", importance=0.35, tags=["introduction"],
                     people=[m["id"], a["id"]], tick=tick, source="heard")
        store_memory(m, f"I introduced {a['name']} and {b['name']} to each other.", importance=0.25,
                     tags=["introduction"], people=[a["id"], b["id"]], tick=tick, source="internal")
    except Exception:
        pass
    return True


def tick_introductions(world):
    """Scheduled job: friends in view of two strangers may introduce them."""
    chars = world.get("characters", {})
    for m in list(chars.values()):
        if not _available(m):
            continue
        seen = [chars[p["id"]] for p in (m.get("perception") or {}).get("visible_people", [])
                if p.get("id") in chars and chars[p["id"]] is not m]
        seen = [x for x in seen if _available(x)]
        if len(seen) < 2:
            continue
        vouch = {x["id"]: _vouches(world, m, x) for x in seen}
        pairs = [(a, b) for i, a in enumerate(seen) for b in seen[i + 1:]
                 if vouch[a["id"]] and vouch[b["id"]] and _is_child(a) == _is_child(b) and _strangers(world, a, b)]
        if not pairs or random.random() >= _chance(m):
            continue
        a, b = random.choice(pairs)
        introduce(world, m, a, b, (vouch[a["id"]] + vouch[b["id"]]) / 2.0)
