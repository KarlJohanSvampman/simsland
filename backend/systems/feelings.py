"""
systems/feelings.py -- kept for older callers; how one character feels about another now lives in social/:

  standing(c, other_id)            social/standing.py's score (stored, directional, -100..100)
  agitation(c, other_id, world)    how worked up c is at them right now: general frustration intensity
                                   (social/frustration.py), fading by INTENSITY_DECAY_PER_DAY
  agitate(c, other_id, world, amount, cause)   raise (or, negative, ease) that
  note(c, other_id, world, cause)  a point on rel["standing_log"] (the Standing tab's chart)

A daily snapshot of every relationship (timeout event "feelingsday") keeps the line going when nothing happens.
"""

from core import scheduler
from social import standing as _standing, frustration as _frustration
from social.core import note as _note, DAY

AGITATION_DECAY_PER_DAY = _frustration.INTENSITY_DECAY_PER_DAY


def standing(c, other_id):
    return round(_standing.score(c, other_id), 1)


def agitation(c, other_id, world):
    return round(_frustration.value(c, other_id, world)["intensity"], 1)


def agitate(c, other_id, world, amount, cause=None):
    if amount >= 0:
        _frustration.raise_(c, other_id, world, amount, cause=cause)
    else:
        _frustration.calm(c, other_id, world, -amount, cause=cause)


def note(c, other_id, world, cause):
    _note(c, other_id, world, cause)


def _daily(world, entry):
    chars = world.get("characters") or {}
    for c in chars.values():
        if c.get("is_workplace_npc") or c.get("alive") is False:
            continue
        for oid in list((c.get("relationships") or {}).keys()):
            if oid in chars:
                _note(c, oid, world, "")                # a plain point on the line: nothing in particular happened


# (scheduled from core/flow.py)
