"""
systems/reputation.py — public reputation engine

Reputation is the *world's perception* of a character or faction,
separate from individual relationship scores (trust/friendship per contact).

Character:
    c["reputation"] = {
        "global":       0.5,   # 0–1: general public perception
        "community":    0.5,   # neighbourhood/local perception
        "by_faction":   {},    # faction_id -> float 0–1
        "notoriety":    0.0,   # criminal fame (separate from moral rep)
        "last_event":   None,  # brief text of most recent rep-shifting event
        "last_updated": 0,     # tick
    }

Faction:
    world["factions"][fid]["reputation"] = {
        "public":        0.5,
        "among_rivals":  0.3,
        "among_allies":  0.8,
        "notoriety":     0.0,
        "last_updated":  0,
    }
"""

import random

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN = 0.0
_MAX = 1.0
_NEUTRAL = 0.5

# How much reputation drifts toward neutral each day (natural regression)
_DAILY_REGRESSION = 0.002

# Event impact magnitudes
EVENT_IMPACTS = {
    # positive
    "heroic_act":        +0.08,
    "community_service": +0.03,
    "public_kindness":   +0.02,
    "promotion":         +0.02,
    "marriage":          +0.01,
    "charitable_donation": +0.04,
    # negative
    "arrested":          -0.12,
    "convicted":         -0.18,
    "assault":           -0.10,
    "public_scandal":    -0.08,
    "fired":             -0.03,
    "domestic_dispute":  -0.04,
    "drug_use_public":   -0.05,
    "evicted":           -0.02,
    # notoriety (criminal fame — goes up, not down, for crimes)
    "notoriety_crime":   +0.06,
    "notoriety_violence":+0.10,
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def ensure_reputation(c):
    """Stamp default reputation block onto a character if missing."""
    c.setdefault("reputation", {
        "global":       _NEUTRAL,
        "community":    _NEUTRAL,
        "by_faction":   {},
        "notoriety":    0.0,
        "last_event":   None,
        "last_updated": 0,
    })
    rep = c["reputation"]
    rep.setdefault("global",       _NEUTRAL)
    rep.setdefault("community",    _NEUTRAL)
    rep.setdefault("by_faction",   {})
    rep.setdefault("notoriety",    0.0)
    rep.setdefault("last_event",   None)
    rep.setdefault("last_updated", 0)
    return rep


def ensure_faction_reputation(faction):
    faction.setdefault("reputation", {
        "public":        _NEUTRAL,
        "among_rivals":  0.3,
        "among_allies":  0.8,
        "notoriety":     0.0,
        "last_updated":  0,
    })
    return faction["reputation"]


# ---------------------------------------------------------------------------
# Apply a named event to a character's reputation
# ---------------------------------------------------------------------------

def apply_reputation_event(c, event_type, world, magnitude_override=None, faction_id=None):
    """
    Shift a character's reputation based on a named event.

    event_type     – key from EVENT_IMPACTS (or any string with magnitude_override)
    faction_id     – if set, also shift by_faction score for this faction
    magnitude_override – override the default impact amount
    """
    rep    = ensure_reputation(c)
    tick   = world.get("tick", 0)
    amount = magnitude_override if magnitude_override is not None else EVENT_IMPACTS.get(event_type, 0.0)

    is_notoriety = event_type.startswith("notoriety_")

    if is_notoriety:
        rep["notoriety"] = _clamp(rep["notoriety"] + abs(amount))
        # Notoriety also slightly lowers moral reputation
        rep["global"]    = _clamp(rep["global"] - abs(amount) * 0.3)
        rep["community"] = _clamp(rep["community"] - abs(amount) * 0.4)
    else:
        rep["global"]    = _clamp(rep["global"]    + amount)
        rep["community"] = _clamp(rep["community"] + amount * 1.2)  # local hits harder

    if faction_id:
        current = rep["by_faction"].get(faction_id, _NEUTRAL)
        rep["by_faction"][faction_id] = _clamp(current + amount)

    rep["last_event"]   = event_type
    rep["last_updated"] = tick


# ---------------------------------------------------------------------------
# Apply to faction
# ---------------------------------------------------------------------------

def apply_faction_reputation_event(faction, event_type, world, magnitude_override=None):
    rep    = ensure_faction_reputation(faction)
    tick   = world.get("tick", 0)
    amount = magnitude_override if magnitude_override is not None else EVENT_IMPACTS.get(event_type, 0.0)

    if event_type.startswith("notoriety_"):
        rep["notoriety"] = _clamp(rep["notoriety"] + abs(amount))
        rep["public"]    = _clamp(rep["public"] - abs(amount) * 0.2)
    else:
        rep["public"]       = _clamp(rep["public"]       + amount)
        rep["among_rivals"] = _clamp(rep["among_rivals"] + amount * 0.3)
        rep["among_allies"] = _clamp(rep["among_allies"] + amount * 0.5)

    rep["last_updated"] = tick


# ---------------------------------------------------------------------------
# Daily tick — natural regression toward neutral + noise
# ---------------------------------------------------------------------------

def tick_reputation(world):
    """
    Called once per simulated day.
    Slowly drifts all reputations back toward 0.5, with tiny random noise.
    """
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        rep = c.get("reputation")
        if not rep:
            continue
        noise = random.uniform(-0.001, 0.001)
        rep["global"]    = _regress(rep["global"],    noise)
        rep["community"] = _regress(rep["community"], noise)
        # by_faction also regresses
        for fid in list(rep.get("by_faction", {})):
            rep["by_faction"][fid] = _regress(rep["by_faction"][fid], 0)

    for faction in world.get("factions", {}).values():
        rep = faction.get("reputation")
        if not rep:
            continue
        rep["public"]       = _regress(rep["public"],       0)
        rep["among_rivals"] = _regress(rep["among_rivals"], 0)
        rep["among_allies"] = _regress(rep["among_allies"], 0)


# ---------------------------------------------------------------------------
# Context helper — returns a short rep summary for LLM context
# ---------------------------------------------------------------------------

def get_reputation_summary(c):
    """
    Returns a compact dict for inclusion in LLM character context.
    """
    rep = c.get("reputation", {})
    if not rep:
        return None
    g = rep.get("global",    _NEUTRAL)
    lc = rep.get("community", _NEUTRAL)
    n  = rep.get("notoriety", 0.0)
    return {
        "public_reputation":    _label(g),
        "community_standing":   _label(lc),
        "notoriety":            _notoriety_label(n),
        "last_rep_event":       rep.get("last_event"),
        "raw": {"global": round(g,2), "community": round(lc,2), "notoriety": round(n,2)},
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(v):
    return max(_MIN, min(_MAX, v))

def _regress(v, noise):
    delta = (_NEUTRAL - v) * _DAILY_REGRESSION + noise
    return _clamp(v + delta)

def _label(v):
    if v >= 0.85: return "beloved"
    if v >= 0.70: return "respected"
    if v >= 0.55: return "well-regarded"
    if v >= 0.45: return "average"
    if v >= 0.35: return "questionable"
    if v >= 0.20: return "disreputable"
    return "notorious"

def _notoriety_label(v):
    if v < 0.05: return "none"
    if v < 0.20: return "minor"
    if v < 0.40: return "known"
    if v < 0.65: return "feared"
    return "infamous"
