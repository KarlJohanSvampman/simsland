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
    "neglected_plants":   2.5,
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
    # Suspicion of a partner's unexplained absences (systems/
    # absence_suspicion.py) that a confrontation failed to put to rest --
    # a real caught lie about it (excuses.py::_handle_caught_lying) hits
    # much harder than an unresolved-but-not-provably-false confrontation.
    "absence_unresolved":             10.0,
    "absence_lie_caught":             20.0,
}


# ── Core API ──────────────────────────────────────────────────────────────

def add_grievance(c, caused_by_id, event_type, world, severity=None, details=None):
    """
    Record a new grievance on character c against caused_by_id.
    severity overrides the default for event_type.
    """
    sync_social_decay(c, world.get("tick", 0) if world else 0)      # what is left of the old ones first
    if world is not None:
        _wake_for_next_check(c, world)                              # the thresholds are looked at next period
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

    # systems/mentality.py -- Phase I's wired consequence: a FIRM ('>')
    # negative principle toward the person who caused this gives real
    # prejudice its teeth -- the same minor slight lands harder from
    # someone c already firmly distrusts, and a lighter slight from
    # someone c firmly identifies WITH gets more benefit of the doubt.
    caused_by = world.get("characters", {}).get(caused_by_id)
    if caused_by:
        from systems.mentality import principle_stance_toward
        stance = principle_stance_toward(c, caused_by, world)
        if stance and stance.get("op") == ">":
            base_severity *= 1.5 if stance["sentiment"] == "unfavorable" else 0.7

    gid = f"griev_{uuid.uuid4().hex[:8]}"
    c["grievances"].append({
        "id":          gid,
        "caused_by":   caused_by_id,
        "event_type":  event_type,
        "severity":    base_severity,
        "weight":      base_severity,   # weight decays; severity is the original
        "tick":        world["tick"],
        "details":     details or {},
    })
    # The incident is evidence on the issue between them (social/issues.py: the persistent problem, which a
    # later conversation picks up), and it feeds c's frustration about that issue -- not their standing directly.
    _to_issue(c, caused_by_id, event_type, base_severity, gid, details or {}, world)


def _to_issue(c, caused_by_id, event_type, severity, gid, details, world):
    chars = world.get("characters", {})
    if caused_by_id not in chars or caused_by_id == c.get("id"):
        return
    from social import issues as I, frustration
    try:
        from systems.fights import ISSUE_PHRASES
        subject = ISSUE_PHRASES.get(event_type) or str(event_type).replace("_", " ")
    except Exception:
        subject = str(event_type).replace("_", " ")
    issue, created = I.find_or_open(world, [c["id"], caused_by_id], subject, I.category_for(event_type),
                                    created_by=c["id"], affected=[c["id"]])
    text = subject + (f" ({details.get('commitment')})" if details.get("commitment") else "")
    if details.get("trigger"):
        text += f": {details['trigger']}"            # what brought it up (systems/life_comparison.py::on_reminded)
    I.add_evidence(world, issue, "incident", text, by=c["id"], ref=gid)
    if not I.position(issue, c["id"]):
        I.set_position(world, issue, c["id"], f"{chars[caused_by_id].get('name', 'they')}: {subject}",
                       stance="opposed", confidence=0.6, investment=min(1.0, severity / 15), basis="observed")
    frustration.raise_(c, caused_by_id, world, min(40.0, severity * 2), issue_id=issue["id"],
                       kind="repeat" if not created else None, cause=f"{subject}")


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
    """Called from sim_loop on a medium cadence.

    Live bug report: an unconscious/incapacitated character was found
    re-emitting confrontation_desired (and re-starting, re-suppressing a
    conflict) every single cycle for hours of sim time, since nothing
    here checked whether the character was even capable of walking over
    and confronting anyone -- unlike sim_loop.py's own per-tick agent
    loop, which already excludes posture=="incapacitated" from running
    at all. Grievances can still accumulate/decay while down, but
    deciding to confront (and the conflict pipeline it spawns) requires
    actually being conscious."""
    for c in world.get("characters", {}).values():
        decay_grievances(c)
        if c.get("alive") is False or c.get("posture") == "incapacitated":
            continue
        check_grievance_thresholds(c, world)


# ── step 5a: grievances, goodwill and guilt as the character's own lazy values ───────────────────────────────────────
# They decayed by a fixed factor on every 15-second run of a sweep over everyone. Now they are brought up to date in the
# character's own update (the periods since the last time, applied at once -- the same result), the thresholds are
# checked there, and a wake is set for the next period at which a score falls through one. A score only rises when a
# grievance or goodwill is added: that brings the values up to date first and wakes the character for the next period.

SOCIAL_DECAY_EVERY_TICKS = 15


def _periods(c, tick):
    last = c.get("_social_decay_tick")
    c["_social_decay_tick"] = tick
    if last is None:
        return 0
    return max(0, tick // SOCIAL_DECAY_EVERY_TICKS - last // SOCIAL_DECAY_EVERY_TICKS)


def sync_social_decay(c, tick):
    n = _periods(c, tick)
    if not n:
        return
    from systems import goodwill as GW
    from systems.offense_rationalization import _GUILT_PARANOIA_DECAY
    for key, rate in (("grievances", DECAY_RATE), ("goodwill", GW.DECAY_RATE)):
        if c.get(key):
            f = rate ** n
            kept = []
            for g in c[key]:
                g["weight"] *= f
                if g["weight"] > 0.5:
                    kept.append(g)
            c[key] = kept
    level = c.get("_guilt_paranoia", 0.0)
    if level > 0:
        rate = 0.90 if c.get("_offense_rationalization") is None else _GUILT_PARANOIA_DECAY
        c["_guilt_paranoia"] = max(0.0, level * rate ** n)


def _next_grid(tick):
    return (tick // SOCIAL_DECAY_EVERY_TICKS + 1) * SOCIAL_DECAY_EVERY_TICKS


def social_checks_for(c, world):
    """The character's own update: values brought up to date, thresholds checked, the next crossing woken for."""
    import math
    tick = world.get("tick", 0)
    sync_social_decay(c, tick)
    if c.get("alive") is False or c.get("posture") == "incapacitated":
        return
    check_grievance_thresholds(c, world)
    from systems.goodwill import check_bond_thresholds, BOND_THRESHOLD, DECAY_RATE as GW_RATE
    check_bond_thresholds(c, world)
    waits = []
    for key, rate, thresholds in (("grievances", DECAY_RATE, (CONFRONT_THRESHOLD, COLD_SHOULDER_THRESHOLD,
                                                              COLD_SHOULDER_THRESHOLD * 0.5)),
                                  ("goodwill", GW_RATE, (BOND_THRESHOLD * 0.5,))):
        scores = {}
        for g in c.get(key) or []:
            scores[g["caused_by"]] = scores.get(g["caused_by"], 0) + g["weight"]
        for score in scores.values():
            for thr in thresholds:
                if score >= thr > 0:
                    waits.append(math.floor(math.log(thr / score) / math.log(rate)) + 1)
    if waits:
        from brain import agent_wake
        at = (tick // SOCIAL_DECAY_EVERY_TICKS + min(waits)) * SOCIAL_DECAY_EVERY_TICKS
        agent_wake.wake_at(c, world, agent_wake.at_tick(world, max(at, _next_grid(tick))), "social_decay")


def _wake_for_next_check(c, world):
    from brain import agent_wake
    agent_wake.wake_at(c, world, agent_wake.at_tick(world, _next_grid(world.get("tick", 0))), "social_added")
