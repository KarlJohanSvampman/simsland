"""
social/frustration.py -- accumulated dissatisfaction (design section 3). Not standing: you can think highly of
someone and be fed up with them.

Two levels, on A's relationship with B:

    rel["frustration"] = {"general": F, "issues": {issue_id: F}}
    F = {"score": 0..100      how much has built up (slow to fade)
         "intensity": 0..100  how worked up they are right now (the old "agitation"; fades by INTENSITY_DECAY_PER_DAY)
         "persistence": 0..1  how resistant it is to fading (grows each time it's fed)
         "tick", "apologies": [ticks of apologies not yet borne out]}

Fed by violated expectations, ignored requests, broken promises, refusals to take responsibility, feeling exploited or
disrespected, others reinforcing it. Eased by resolution, acknowledgement, an accepted apology, changed behaviour,
renegotiation, an explanation that changes the picture, and quiet time. An apology alone doesn't wipe it: it calms the
moment, and if the same thing happens again soon after, it lands harder than before.
"""

from social.core import DAY, clamp, emit, now, rel, note

SCORE_DECAY_PER_DAY = 6.0          # at persistence 0; a persistent frustration hardly fades
INTENSITY_DECAY_PER_DAY = 15.0     # the X of "agitation goes away by X points per day"
APOLOGY_WINDOW = 7 * DAY
_RELAPSE_KINDS = {"violation", "ignored", "broken_promise", "repeat", "unmet_expectation", "contract_violated"}


def _blank(t):
    return {"score": 0.0, "intensity": 0.0, "persistence": 0.1, "tick": t, "apologies": []}


def _decayed(f, t):
    days = max(0, t - (f.get("tick") or t)) / DAY
    if days:
        f["score"] = round(max(0.0, f["score"] - SCORE_DECAY_PER_DAY * (1 - f.get("persistence", 0.1)) * days), 2)
        f["intensity"] = round(max(0.0, f["intensity"] - INTENSITY_DECAY_PER_DAY * days), 2)
        f["tick"] = t
    return f


def _store(c, oid, world, issue_id=None, create=True):
    r = rel(c, oid, create=create)
    fr = r.get("frustration")
    if not isinstance(fr, dict):
        if not create:
            return None
        fr = r["frustration"] = {"general": _blank(now(world)), "issues": {}}
        a = r.pop("agitation", None)            # the old fast number becomes general intensity
        if isinstance(a, dict) and a.get("value"):
            fr["general"]["intensity"] = float(a["value"])
            fr["general"]["tick"] = a.get("tick") or now(world)
    if issue_id is None:
        return _decayed(fr["general"], now(world))
    f = fr["issues"].get(issue_id)
    if f is None:
        if not create:
            return None
        f = fr["issues"][issue_id] = _blank(now(world))
    return _decayed(f, now(world))


def value(c, oid, world, issue_id=None):
    f = _store(c, oid, world, issue_id, create=False) if c else None
    if f is None:
        a = (rel(c, oid, create=False) or {}).get("agitation") if c else None
        if issue_id is None and isinstance(a, dict):
            days = max(0, now(world) - (a.get("tick") or 0)) / DAY
            return {"score": 0.0, "intensity": max(0.0, a.get("value", 0) - INTENSITY_DECAY_PER_DAY * days)}
        return {"score": 0.0, "intensity": 0.0}
    return {"score": f["score"], "intensity": f["intensity"], "persistence": f.get("persistence", 0.1)}


def by_issue(c, oid, world):
    fr = (rel(c, oid, create=False) or {}).get("frustration") or {}
    return {iid: value(c, oid, world, iid) for iid in (fr.get("issues") or {})}


def _bump(f, amount):
    f["score"] = round(clamp(f["score"] + amount * (1 - f["score"] / 130), 0, 100), 2)
    f["intensity"] = round(clamp(f["intensity"] + amount * 1.2, 0, 100), 2)
    f["persistence"] = round(min(0.9, f.get("persistence", 0.1) + 0.04), 3)


def raise_(c, oid, world, amount, issue_id=None, cause=None, kind=None):
    """c is more frustrated with oid (about issue_id, which also feeds the general level at half)."""
    if not oid or oid == c.get("id") or amount <= 0:
        return 0.0
    t = now(world)
    if issue_id:
        f = _store(c, oid, world, issue_id)
        if kind in _RELAPSE_KINDS and any(t - a < APOLOGY_WINDOW for a in f.get("apologies") or []):
            amount *= 1.5                                   # sorry, and then the same again
            f["apologies"] = []
        _bump(f, amount)
        _bump(_store(c, oid, world), amount * 0.5)
    else:
        _bump(_store(c, oid, world), amount)
    emit("FrustrationChanged", {"observer_id": c.get("id"), "target_id": oid, "issue_id": issue_id,
                                "delta": amount, "kind": kind})
    if cause:
        note(c, oid, world, cause)
    return amount


def calm(c, oid, world, amount, issue_id=None, cause=None, kind=None):
    """It eases. kind: "apology" (calms the moment, remembered in case it happens again), "acknowledged",
    "explained", "behaviour_change", "renegotiated", "resolved" (the issue's frustration mostly goes), "time"."""
    if not oid or oid == c.get("id"):
        return
    targets = [_store(c, oid, world, issue_id)] if issue_id else []
    targets.append(_store(c, oid, world))
    for i, f in enumerate(targets):
        share = 1.0 if (i == 0) else 0.5
        if kind == "apology":
            f["intensity"] = max(0.0, f["intensity"] - amount * share)
            f["score"] = max(0.0, f["score"] - amount * 0.25 * share)
            f.setdefault("apologies", []).append(now(world))
        elif kind == "resolved" and i == 0 and issue_id:
            f["score"] = round(f["score"] * 0.3, 2)
            f["intensity"] = 0.0
            f["persistence"] = 0.1
        else:
            f["score"] = round(max(0.0, f["score"] - amount * share), 2)
            f["intensity"] = round(max(0.0, f["intensity"] - amount * share), 2)
            if kind == "behaviour_change":
                f["apologies"] = []
    emit("FrustrationChanged", {"observer_id": c.get("id"), "target_id": oid, "issue_id": issue_id,
                                "delta": -amount, "kind": kind})
    if cause:
        note(c, oid, world, cause)


def word(intensity):
    return "furious" if intensity >= 80 else "angry" if intensity >= 60 else "irritated" if intensity >= 30 \
        else "a little put out" if intensity >= 10 else "calm"
