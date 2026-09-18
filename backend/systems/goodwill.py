"""
systems/goodwill.py

The positive counterpart to systems/grievances.py -- a real, itemized
ledger for things that BUILD a relationship, mirroring that module's
shape exactly (weighted list, per-target score, slow decay, a real
threshold). Where a grievance grounds a negative shared_event pairing in
real tension, a goodwill score grounds a pleasant one in real warmth.

Crossing BOND_THRESHOLD is stamped once (re-armed only after the score
decays back down), the same re-arm convention grievances.py's own
confrontation_desired uses -- a hook point for a future round to hang a
"wants to deepen this friendship" intention on. Not built further than
the ledger + score this round.
"""

import uuid

# ── Thresholds ────────────────────────────────────────────────────────────
BOND_THRESHOLD = 30.0   # total weighted score → wants to deepen the bond
DECAY_RATE     = 0.997  # per tick (mirrors grievances.py's own slow decay)

# ── Severity presets for common positive events ────────────────────────────
GOODWILL_SEVERITY = {
    "complimented":              5.0,
    "helped_out":                8.0,
    "shared_laugh":               6.0,
    "supported_through_hardship": 15.0,
    "gave_gift":                  9.0,
    "kept_a_promise":             7.0,
    "comforted":                  8.0,
    "shared_good_news":           5.0,
    "spent_quality_time":         6.0,
}


def add_goodwill(c, caused_by_id, event_type, world, severity=None, details=None):
    """Record a new goodwill entry on character c toward caused_by_id.
    severity overrides the default for event_type."""
    c.setdefault("goodwill", [])

    base_severity = severity if severity is not None else GOODWILL_SEVERITY.get(event_type, 5.0)

    # Trait modifiers -- mirrors grievances.py's own sensitivity skew,
    # applied in the same direction (a sensitive character feels warmth
    # more strongly too, not just slights).
    if "sensitive" in c.get("traits", []):
        base_severity *= 1.3
    if "cold" in c.get("traits", []):
        base_severity *= 0.6

    c["goodwill"].append({
        "id":         f"good_{uuid.uuid4().hex[:8]}",
        "caused_by":  caused_by_id,
        "event_type": event_type,
        "severity":   base_severity,
        "weight":     base_severity,   # weight decays; severity is the original
        "tick":       world["tick"],
        "details":    details or {},
    })


def get_goodwill_score(c, toward_id):
    """Sum of current (decayed) weights of all goodwill entries toward toward_id."""
    return sum(
        g["weight"] for g in c.get("goodwill", [])
        if g["caused_by"] == toward_id
    )


def decay_goodwill(c):
    """Apply per-tick decay and remove fully faded goodwill entries."""
    remaining = []
    for g in c.get("goodwill", []):
        g["weight"] *= DECAY_RATE
        if g["weight"] > 0.5:
            remaining.append(g)
    c["goodwill"] = remaining


def check_bond_thresholds(c, world):
    """For each character c has goodwill toward, check if the score
    crosses BOND_THRESHOLD. Stamps _bond_emitted once per target (mirrors
    grievances.py::check_grievance_thresholds' fired-set re-arm pattern)
    for a future round to hang a "wants to deepen this friendship"
    intention on -- not consumed anywhere yet this round."""
    scores = {}
    for g in c.get("goodwill", []):
        scores[g["caused_by"]] = scores.get(g["caused_by"], 0) + g["weight"]

    emitted = c.setdefault("_bond_emitted", [])

    for target_id, score in scores.items():
        if score >= BOND_THRESHOLD and target_id not in emitted:
            emitted.append(target_id)
        elif score < BOND_THRESHOLD * 0.5 and target_id in emitted:
            emitted.remove(target_id)


def update_goodwill(world):
    """Called from sim_loop on the same cadence as update_grievances."""
    for c in world.get("characters", {}).values():
        decay_goodwill(c)
        if c.get("alive") is False or c.get("posture") == "incapacitated":
            continue
        check_bond_thresholds(c, world)
