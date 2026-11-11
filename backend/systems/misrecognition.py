"""
systems/misrecognition.py

Mistaking one person for another. Someone seen far off (near the edge of the distance at which you can still tell
who someone is), in poor light, or a voice heard only faintly, can be taken for somebody else you know who is much
the same: same sex, a similar age. The mistake is what they believe -- the name they see in their prompt is the
wrong one -- while the person really there is still who acts on them (speaking to "Sam" reaches Bob, who is the one
standing there). It holds for a couple of minutes (one draw per pair per MISTAKE_WINDOW) so it doesn't flicker, and
goes away as they get close or the voice gets clear.

    seen:   no chance within SAFE_SHARE of the recognition range, rising to SEEN_MAX at its edge, more at night and
            when they're hard to see (visibility)
    heard:  only while the speaker can just about be told (clarity HEARD_CLEAR_FROM .. HEARD_CLEAR_TO), rising to
            HEARD_MAX at the unclear end
"""

import hashlib

from core.clock import MINUTE

MISTAKE_WINDOW = 2 * MINUTE
SAFE_SHARE = 0.5
SEEN_MAX = 0.25
HEARD_CLEAR_FROM, HEARD_CLEAR_TO, HEARD_MAX = 0.3, 0.55, 0.3
AGE_GAP = 15


def _draw(*parts):
    h = hashlib.sha1(":".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _lookalike(c, other, world, kind):
    """Someone c knows who could be taken for other (same sex, similar age, not other, not c), or None."""
    chars = world.get("characters") or {}
    known = [chars[k] for k in (c.get("relationships") or {}) if k in chars]
    age = other.get("age")
    pool = []
    for k in known:
        if k["id"] in (other["id"], c["id"]) or k.get("alive") is False:
            continue
        if k.get("sex") != other.get("sex"):
            continue
        if age is not None and k.get("age") is not None and abs(k["age"] - age) > AGE_GAP:
            continue
        if age is not None and k.get("age") is not None and (k["age"] < 18) != (age < 18):
            continue
        pool.append(k)
    if not pool:
        return None
    pool.sort(key=lambda k: k["id"])
    window = world.get("tick", 0) // MISTAKE_WINDOW
    return pool[int(_draw(c["id"], other["id"], kind, window, "who") * len(pool)) % len(pool)]


def seen_as(c, other, world, distance, recognize, visibility):
    """The person c takes other for when seen at this distance -- other themselves, or a lookalike."""
    if recognize <= 0 or distance <= recognize * SAFE_SHARE:
        return other
    share = min(1.0, (distance / recognize - SAFE_SHARE) / (1 - SAFE_SHARE))
    chance = share * SEEN_MAX
    from brain.perception import _is_night
    if _is_night(world):
        chance *= 1.5
    if visibility is not None and visibility < 0.5:
        chance *= 1.3
    window = world.get("tick", 0) // MISTAKE_WINDOW
    if _draw(c["id"], other["id"], "seen", window) >= chance:
        return other
    return _lookalike(c, other, world, "seen") or other


def heard_as(c, other, world, clarity):
    """The person c takes a voice for -- the speaker, or a lookalike voice."""
    if clarity < HEARD_CLEAR_FROM or clarity >= HEARD_CLEAR_TO:
        return other
    chance = (HEARD_CLEAR_TO - clarity) / (HEARD_CLEAR_TO - HEARD_CLEAR_FROM) * HEARD_MAX
    window = world.get("tick", 0) // MISTAKE_WINDOW
    if _draw(c["id"], other["id"], "heard", window) >= chance:
        return other
    return _lookalike(c, other, world, "heard") or other
