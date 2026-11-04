"""
systems/feelings.py

How one character feels about another -- standing and agitation -- with a history.
(Not systems/standing.py, which is who children look up to.)

  standing(c, other_id)       the slow number: liking, trust and respect against resentment and hostility
                              (the same formula systems/rifts.py uses; the Inspector's Standing tab shows it)
  agitation(c, other_id, world)  the fast one, 0-100: how worked up c is at them now. Raised by what they do
                              (a grievance, a fight that ended badly, a damning thing heard about them); fades by
                              AGITATION_DECAY_PER_DAY on its own.
  note(c, other_id, world, cause)  record a change: rel["standing_log"] gets {tick, standing, agitation, cause} --
                              what the Standing tab's modal draws over time

Stored on the relationship: rel["agitation"] = {"value", "tick"} (decayed lazily from "tick"), rel["standing_log"].
A daily snapshot of every relationship (timeout event "feelingsday") keeps the line going when nothing happens.
"""

from core import scheduler

AGITATION_DECAY_PER_DAY = 15
DAY = 86400
LOG_CAP = 120


def standing(c, other_id):
    rel = (c.get("relationships") or {}).get(other_id) or {}
    return round((rel.get("friendship") or 0) + 0.5 * (rel.get("trust") or 0) + 0.5 * (rel.get("respect") or 0)
                 + 0.3 * (rel.get("warmth") or 0) - (rel.get("resentment") or 0) - (rel.get("hostility") or 0), 1)


def agitation(c, other_id, world):
    rel = (c.get("relationships") or {}).get(other_id) or {}
    a = rel.get("agitation") or {}
    days = max(0, world.get("tick", 0) - (a.get("tick") or 0)) / DAY
    return max(0.0, round((a.get("value") or 0) - AGITATION_DECAY_PER_DAY * days, 1))


def agitate(c, other_id, world, amount, cause=None):
    """c gets more (or, negative, less) worked up at other_id."""
    if not other_id or other_id == c.get("id"):
        return
    rel = c.setdefault("relationships", {}).setdefault(other_id, {})
    now = agitation(c, other_id, world)
    rel["agitation"] = {"value": max(0.0, min(100.0, now + amount)), "tick": world.get("tick", 0)}
    if cause:
        note(c, other_id, world, cause)


def note(c, other_id, world, cause):
    if not other_id or other_id == c.get("id"):
        return
    rel = c.setdefault("relationships", {}).setdefault(other_id, {})
    log = rel.setdefault("standing_log", [])
    log.append({"tick": world.get("tick", 0), "standing": standing(c, other_id),
                "agitation": agitation(c, other_id, world), "cause": str(cause)[:160]})
    del log[:-LOG_CAP]


def _daily(world, entry):
    chars = world.get("characters") or {}
    for c in chars.values():
        if c.get("is_workplace_npc") or c.get("alive") is False:
            continue
        for oid in list((c.get("relationships") or {}).keys()):
            if oid in chars:
                note(c, oid, world, "")                 # a plain point on the line: nothing in particular happened


scheduler.register_recurring("feelingsday", _daily, DAY, offset=6 * 3600)
