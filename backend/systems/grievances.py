"""
systems/grievances.py

Each character accumulates grievances against others when they observe
behaviour that conflicts with their needs, values, or social contracts.

Grievances decay slowly over time but compound when the same behaviour
repeats. When total grievance score against a specific character crosses
CONFRONT_THRESHOLD the character emits 'confrontation_desired' so the
conflict pipeline can schedule a face-to-face.

Behaviour analysis is intentionally lightweight: systems that detect a
harmful event call add_grievance() directly. Contract violations are
handled by social_contracts.py and also route here.
"""

import uuid
import random

# ── Thresholds ────────────────────────────────────────────────────────────
CONFRONT_THRESHOLD    = 30.0   # total weighted score → want to confront
COLD_SHOULDER_THRESHOLD = 15.0 # start avoiding without confronting
DECAY_RATE            = 0.997  # per tick (very slow — memories linger)
CONTRACT_MULTIPLIER   = 2.5    # broken promises hurt more

# ── Severity presets for common events ────────────────────────────────────
SEVERITY = {
    "insulted":           8.0,
    "threatened":        12.0,
    "betrayed":          15.0,
    "contract_violated": 10.0,
    "ate_my_food":        6.0,
    "stole":             14.0,
    "loud_at_night":      4.0,
    "left_mess":          3.0,
    "flirting_with_partner": 12.0,
    "excluded":           4.0,
    "lied":               7.0,
    "broke_promise":      8.0,
    "disrespected":       5.0,
    # Missed self-expectations (systems/expectations.py) attributed to a
    # specific responsible person -- see systems/expectation_planner.py's
    # requires_others completion check.
    "family_dinner_skipped":   6.0,
    "promised_errand_broken":  9.0,
    # Convenience/stability loss (systems/convenience.py) attributed to a
    # specific responsible person -- e.g. a parent restricting freedom.
    "restricted_freedom":      5.0,
    # Personal/persona expectations of a specific individual
    # (systems/persona_expectations.py) -- generic value-alignment clash,
    # plus the pre-existing religious_repression.py conflict types now
    # wired into the same grievance pipeline.
    "value_clash":             7.0,
    "identity_shame":         12.0,
    "porn_shame":              7.0,
    "sexual_curiosity_shame":  6.0,
    # Favor ledger (systems/favors.py) -- committed to helping repeatedly
    # with nothing given back.
    "favor_unreciprocated":    8.0,
    # Life comparison (systems/life_comparison.py) -- repeated
    # unfavorable-to-self comparisons crossing the jealousy threshold.
    "life_envy":               6.0,
    # Rival sports fandom (systems/sports.py) -- opposing-team supporters
    # sharing a game-day event, scaled up by a loss.
    "team_rivalry":            5.0,
    "gang_violence":           10.0,
    "resource_conflict":  5.0,
    "ignored_me":         3.0,
    "romantic_envy":     10.0,
    "partner_jealousy":   9.0,
    "status_envy":        5.0,
    "career_envy":        6.0,
    "social_envy":        4.0,
    "opportunity_envy":   5.5,
    "rejected_advance":   4.0,
    "ignored_rejection":       14.0,   # pushed advance after clear rejection
    "witnessed_transgression":   6.0,   # heard via gossip that someone did this
    "romantic_rivalry":         10.0,   # rival revealed attraction to same person
    "fight_loss_humiliation":   12.0,   # lost a physical fight (public humiliation)
    # Pregnancy drama
    "family_pregnancy_shock":         14.0,
    "family_abortion_conflict":       18.0,
    "family_adoption_grief":          12.0,
    "family_pregnancy_obligation":    10.0,
    "family_social_shame":            10.0,
    "family_birth_event":              6.0,
    "father_family_blamed":           15.0,
    "mother_family_blamed":           15.0,
    # Harassment
    "sexual_harassment":              14.0,
    "partner_harassed":               12.0,
    "verbal_harassment":               9.0,
}


# ── Core API ──────────────────────────────────────────────────────────────

def add_grievance(c, caused_by_id, event_type, world, severity=None, details=None):
    """
    Record a new grievance on character c against caused_by_id.
    severity overrides the default for event_type.
    """
    c.setdefault("grievances", [])

    base_severity = severity if severity is not None else SEVERITY.get(event_type, 5.0)

    # Trait modifiers — sensitive sims feel things more strongly
    if "sensitive" in c.get("traits", []):
        base_severity *= 1.3
    if "forgiving" in c.get("traits", []):
        base_severity *= 0.6
    if "petty" in c.get("traits", []):
        base_severity *= 1.4

    # Contract violations carry extra weight
    if event_type == "contract_violated":
        base_severity *= CONTRACT_MULTIPLIER

    c["grievances"].append({
        "id":          f"griev_{uuid.uuid4().hex[:8]}",
        "caused_by":   caused_by_id,
        "event_type":  event_type,
        "severity":    base_severity,
        "weight":      base_severity,   # weight decays; severity is the original
        "tick":        world["tick"],
        "details":     details or {},
    })


def get_grievance_score(c, against_id):
    """Sum of current (decayed) weights of all grievances against against_id."""
    return sum(
        g["weight"] for g in c.get("grievances", [])
        if g["caused_by"] == against_id
    )


def get_top_grievances(c, against_id, limit=3):
    """Return the most severe active grievances for use in conflict context."""
    relevant = [
        g for g in c.get("grievances", [])
        if g["caused_by"] == against_id and g["weight"] > 1.0
    ]
    relevant.sort(key=lambda g: g["weight"], reverse=True)
    return relevant[:limit]


def decay_grievances(c):
    """Apply per-tick decay and remove fully faded grievances."""
    remaining = []
    for g in c.get("grievances", []):
        g["weight"] *= DECAY_RATE
        if g["weight"] > 0.5:
            remaining.append(g)
    c["grievances"] = remaining


def check_grievance_thresholds(c, world):
    """
    For each character c has grievances against, check if the score
    crosses confrontation threshold. Emits 'confrontation_desired' once
    per target (uses a fired-set to avoid spamming).
    """
    from core.event_bus import emit

    scores = {}
    for g in c.get("grievances", []):
        scores[g["caused_by"]] = scores.get(g["caused_by"], 0) + g["weight"]

    fired = c.setdefault("_confrontation_emitted", [])

    for target_id, score in scores.items():
        if score >= CONFRONT_THRESHOLD and target_id not in fired:
            fired.append(target_id)
            emit("confrontation_desired", {
                "initiator_id": c["id"],
                "target_id":    target_id,
                "score":        score,
            })
        elif score < COLD_SHOULDER_THRESHOLD * 0.5 and target_id in fired:
            # Recovered enough — allow re-firing later
            fired.remove(target_id)

        # Cold shoulder (avoid without confronting) — just flag, no event needed
        cold_shoulder = c.setdefault("cold_shoulder_towards", [])
        if COLD_SHOULDER_THRESHOLD <= score < CONFRONT_THRESHOLD:
            if target_id not in cold_shoulder:
                cold_shoulder.append(target_id)
        elif target_id in cold_shoulder:
            cold_shoulder.remove(target_id)


def update_grievances(world):
    """Called from sim_loop on a medium cadence."""
    for c in world.get("characters", {}).values():
        decay_grievances(c)
        check_grievance_thresholds(c, world)
