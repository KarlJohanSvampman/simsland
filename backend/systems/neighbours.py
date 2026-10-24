"""
systems/neighbours.py -- who a character already knows from the street.

A character who appears in a household next to others doesn't start out as a stranger to everyone around them: a
child has friends two doors down and has played with them for years, the parents nod to the other parents. Without
this a new world starts with every relationship at zero and a lonely six-year-old.

When a character is created (editor spawn, a generated world, a relative) -- or, for characters that already exist,
the first time this runs -- they are given ties to the people of OTHER households nearby (within NEIGHBOUR_RADIUS tiles
of their home):

  children and teenagers (4-17)   up to MAX_KID_FRIENDS friends among the other children of about their age (within
        MAX_AGE_GAP years): friendship, familiarity, trust and comfort at a level that depends on how close in age they
        are, how near they live and how many hobbies they share, plus a small memory of it ("X lives nearby and we play
        together sometimes")
  grown-ups                       up to MAX_ADULT_ACQUAINTANCES acquaintances among the nearest other adults: they
        recognise each other and have nodded hello, nothing more

Ties are mutual and tagged with the label "neighbour". Nothing existing is lowered, family is left alone, and a pair
that has already interacted for real keeps whatever it has. The ties come with a plain history count (a few past
interactions), so they read as people who know each other, not as fresh strangers. The contact-designation ladder
(hours spent together) is left to run on its own.
"""

import random

from brain.relationships import ensure_relationship, update_relationship_state, _default_relationship

NEIGHBOUR_RADIUS = 40                  # tiles between the two homes
KID_AGES = (4, 17)
MAX_AGE_GAP = 3
MAX_KID_FRIENDS = 3
MAX_ADULT_ACQUAINTANCES = 5
SHARED_HOBBY_BONUS = 0.12
FRIEND_SCALE = {"familiarity": (14, 14), "friendship": (10, 22), "trust": (6, 10), "comfort": (3, 7)}      # (base, spread) x strength
ACQUAINTANCE_SCALE = {"familiarity": (6, 6), "friendship": (2, 5), "trust": (1, 4), "comfort": (0, 2)}


def _is_person(c):
    return not (c.get("is_workplace_npc") or c.get("is_service_worker")) and c.get("alive") is not False


def home_position(world, household_id):
    """(x, y) of a household's home, or None if it can't be told."""
    if not household_id:
        return None
    for b in world.get("buildings", []):
        if b.get("owner_household_id") == household_id and b.get("x") is not None:
            return (b["x"], b["y"])
    h = (world.get("households") or {}).get(household_id) or {}
    home = h.get("home_id")
    for b in world.get("buildings", []):
        if home and b.get("id") == home and b.get("x") is not None:
            return (b["x"], b["y"])
    return None


def _distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def nearby_people(world, c, radius=NEIGHBOUR_RADIUS):
    """[(distance, other)] of people in OTHER households whose home is within `radius` tiles, nearest first."""
    mine = home_position(world, c.get("household_id"))
    if mine is None:
        return []
    out = []
    homes = {}
    for o in world.get("characters", {}).values():
        if o["id"] == c["id"] or not _is_person(o) or not o.get("household_id") or o["household_id"] == c.get("household_id"):
            continue
        pos = homes.setdefault(o["household_id"], home_position(world, o["household_id"]))
        if pos is None:
            continue
        d = _distance(mine, pos)
        if d <= radius:
            out.append((d, o))
    return sorted(out, key=lambda t: (t[0], t[1]["id"]))


def _friends(c):
    return [oid for oid, r in (c.get("relationships") or {}).items() if (r.get("friendship", 0) or 0) >= 10 and not r.get("kinship")]


def _tie(world, a, b, scale, strength, label="neighbour"):
    """Mutual tie. Never lowers anything, skips kin and pairs that already have real history. True if created."""
    ra, rb = ensure_relationship(a, b["id"]), ensure_relationship(b, a["id"])
    for rel in (ra, rb):                               # a partly filled entry (an older save) gets its missing fields
        for key, value in _default_relationship().items():
            rel.setdefault(key, value)
    if label and (label in (ra.get("labels") or []) and label in (rb.get("labels") or [])):
        return False                                   # already tied
    if ra.get("kinship") or rb.get("kinship") or (ra.get("interaction_count", 0) or 0) > 5 or (rb.get("interaction_count", 0) or 0) > 5:
        return False
    for me, other, rel in ((a, b, ra), (b, a, rb)):
        wobble = random.uniform(0.9, 1.1)
        for field, (base, spread) in scale.items():
            value = round((base + spread * strength) * wobble, 2)
            if value > (rel.get(field, 0) or 0):
                rel[field] = value
        rel["interaction_count"] = max(rel.get("interaction_count", 0) or 0, 3)
        rel["positive_interactions"] = max(rel.get("positive_interactions", 0) or 0, 3)
        if label and label not in (rel.get("labels") or []):
            rel.setdefault("labels", []).append(label)
        update_relationship_state(me, other["id"])
    return True


def _kid_score(c, o, distance):
    gap = abs((c.get("age") or 0) - (o.get("age") or 0))
    shared = len(set(c.get("hobbies") or []) & set(o.get("hobbies") or []))
    closeness = max(0.0, 1.0 - gap / (MAX_AGE_GAP + 1.0))
    nearness = max(0.0, 1.0 - distance / (NEIGHBOUR_RADIUS * 1.5))
    strength = max(0.3, min(1.0, 0.35 + 0.35 * closeness + 0.2 * nearness + SHARED_HOBBY_BONUS * shared))
    return strength + random.uniform(0, 0.05), strength


def seed_neighbour_ties(world, c):
    """Give `c` the ties described at the top of the module. Returns the ids of the people they were tied to."""
    if not _is_person(c) or not c.get("household_id"):
        return []
    tick = world.get("tick", 0)
    age = c.get("age")
    tied = []
    people = nearby_people(world, c)
    if age is not None and KID_AGES[0] <= age <= KID_AGES[1]:
        want = MAX_KID_FRIENDS - len(_friends(c))
        candidates = []
        for d, o in people:
            oa = o.get("age")
            if oa is None or not (KID_AGES[0] <= oa <= KID_AGES[1]) or abs(oa - age) > MAX_AGE_GAP:
                continue
            if len(_friends(o)) > MAX_KID_FRIENDS:
                continue
            score, strength = _kid_score(c, o, d)
            candidates.append((score, strength, o))
        for score, strength, o in sorted(candidates, key=lambda t: -t[0]):
            if want <= 0:
                break
            if _tie(world, c, o, FRIEND_SCALE, strength):
                tied.append(o["id"])
                want -= 1
                _remember_friend(c, o, tick)
                _remember_friend(o, c, tick)
    elif age is None or age > KID_AGES[1]:
        known = {oid for oid, r in (c.get("relationships") or {}).items() if (r.get("familiarity", 0) or 0) >= ACQUAINTANCE_SCALE["familiarity"][0]}
        count = 0
        for d, o in people:
            if count >= MAX_ADULT_ACQUAINTANCES:
                break
            if (o.get("age") is not None and o["age"] <= KID_AGES[1]) or o["id"] in known:
                continue
            strength = max(0.2, 1.0 - d / (NEIGHBOUR_RADIUS * 1.2))
            if _tie(world, c, o, ACQUAINTANCE_SCALE, strength):
                tied.append(o["id"])
                count += 1
    c["_neighbours_seeded"] = tick
    return tied


def _remember_friend(c, o, tick):
    try:
        from brain.memory import store_memory
        store_memory(c, f"{o['name']} lives nearby and we play together sometimes.", importance=0.25,
                     tags=["neighbour", "friend"], people=[o["id"]], tick=tick, source="internal")
    except Exception:
        pass


def tick_seed_neighbours(world):
    """Scheduled job: whoever hasn't been given their street yet gets it (covers every way a character can appear:
    a generated world, the editor, a relative, a reset)."""
    for c in list(world.get("characters", {}).values()):
        if c.get("_neighbours_seeded") is None and _is_person(c) and c.get("household_id"):
            seed_neighbour_ties(world, c)
