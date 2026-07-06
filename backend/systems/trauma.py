"""
systems/trauma.py

Trauma tracking, psychological impact, and downstream behavioral consequences.

Trauma events:
  - sexual_assault          (perpetrator forced act on unwilling victim)
  - coercion                (pressure/manipulation used to override refusal)
  - betrayal_intimate       (intimate partner acted in a deeply violating way)
  - witnessed_violence
  - physical_assault
  - (other events can register here via add_trauma_event)

Psychological model:
  - trauma.score (0-1):        cumulative severity, decays slowly with support
  - trauma.ptsd_active (bool): triggered above threshold, causes flashbacks/avoidance
  - trauma.intimacy_avoidance: reluctance modifier applied to all future intimacy
  - trauma.trust_floor:        minimum trust required before any intimate stage
  - trauma.events[]:           full log with perpetrator_id, severity, reported, outcome

Reporting decision:
  - Victim's social support (trusted friends/family/partner in network)
  - Psychological impact severity
  - Prior offenses by same perpetrator already known to victim
  - Random variance (shame, fear of not being believed)
  - If support network is strong → more likely to report
  - If victim has given up (repeated offenses, high trauma) → less likely
  - If reported → triggers law.process_assault_report()

Revenge escalation:
  - Repeated assaults by same perp increase victim's "revenge_urge" against them
  - When revenge_urge crosses threshold, victim may attempt violent retaliation
  - Violence often exceeds intent (revenge_severity > intended_severity)
  - This feeds into conflict_pipeline as "assault" or "attempted_homicide"

Career path influence:
  - High trauma + intimacy_avoidance + certain personality traits → nudge toward
    sex work as a dissociated, controlled form of reclaiming intimacy autonomy
  - This is a statistical tendency, not a deterministic rule
"""

import random
import uuid

from systems.grievances   import add_grievance
from systems.reputation   import apply_reputation_event

# ── Severity presets ──────────────────────────────────────────────────────
TRAUMA_SEVERITY = {
    "sexual_assault":       0.45,
    "coercion":             0.25,
    "betrayal_intimate":    0.20,
    "physical_assault":     0.20,
    "witnessed_violence":   0.10,
    "public_humiliation":   0.08,
    "stalking":             0.15,
    "harassment":           0.10,
}

# Psychological thresholds
PTSD_THRESHOLD            = 0.50   # trauma.score above this activates PTSD
INTIMACY_AVOIDANCE_GAIN   = 0.30   # per sexual assault event
TRUST_FLOOR_GAIN          = 0.25   # per sexual assault event
TRAUMA_DECAY_PER_TICK     = 0.00003  # very slow natural healing

# Reporting decision weights
REPORT_BASE_CHANCE        = 0.35   # baseline before modifiers
SUPPORT_REPORT_BONUS      = 0.20   # per close friend/family who knows victim
PRIOR_OFFENSE_REPORT_BONUS = 0.15  # perp already has a prior offense
HIGH_TRAUMA_REPORT_PENALTY = 0.20  # too traumatised to act
REPEAT_VICTIM_PENALTY      = 0.12  # repeated by same perp → shame/resignation

# Revenge thresholds
REVENGE_URGE_THRESHOLD    = 0.70   # revenge_urge above this may trigger action
REVENGE_EXCESS_FACTOR     = 1.40   # revenge typically escalates 40% beyond intent


# ── Add a trauma event ────────────────────────────────────────────────────

def add_trauma_event(victim, event_type, perpetrator_id, world,
                     severity_override=None, details=None):
    """
    Record a trauma event on the victim.  Updates all psychological fields.
    Returns the trauma event record.
    """
    victim.setdefault("trauma", {
        "score":              0.0,
        "events":             [],
        "ptsd_active":        False,
        "intimacy_avoidance": 0.0,
        "trust_floor":        0.0,
        "revenge_urge":       {},   # {perp_id: float}
    })
    trauma = victim["trauma"]

    severity = severity_override if severity_override is not None \
               else TRAUMA_SEVERITY.get(event_type, 0.10)

    # Trait modifiers
    v_traits = set(victim.get("traits", []) + victim.get("personality_traits", []))
    if "sensitive" in v_traits:
        severity *= 1.3
    if "resilient" in v_traits or "stoic" in v_traits:
        severity *= 0.7

    event = {
        "id":            f"trauma_{uuid.uuid4().hex[:8]}",
        "type":          event_type,
        "perpetrator_id": perpetrator_id,
        "severity":      round(severity, 3),
        "tick":          world.get("tick", 0),
        "reported":      False,
        "report_outcome": None,
        "details":       details or {},
    }
    trauma["events"].append(event)

    # Update cumulative score (diminishing returns on high existing trauma)
    current = trauma["score"]
    gain    = severity * (1.0 - current * 0.4)
    trauma["score"] = round(min(1.0, current + gain), 4)

    # PTSD activation
    if trauma["score"] >= PTSD_THRESHOLD:
        trauma["ptsd_active"] = True

    # Intimacy-specific effects for sexual assault
    if event_type in ("sexual_assault", "coercion"):
        trauma["intimacy_avoidance"] = round(
            min(1.0, trauma.get("intimacy_avoidance", 0.0) + INTIMACY_AVOIDANCE_GAIN), 3
        )
        trauma["trust_floor"] = round(
            min(0.9, trauma.get("trust_floor", 0.0) + TRUST_FLOOR_GAIN), 3
        )

    # Revenge urge — escalates with repeated offenses by same perpetrator
    if perpetrator_id:
        urge  = trauma.setdefault("revenge_urge", {})
        prior = urge.get(perpetrator_id, 0.0)
        urge[perpetrator_id] = round(min(1.0, prior + severity * 1.2), 4)

    # Grievance against perpetrator
    if perpetrator_id:
        add_grievance(
            victim, perpetrator_id,
            event_type,
            world,
            severity=severity * 15,   # grievances scale differently
            details={"trauma_event_id": event["id"]}
        )

    return event


# ── Reporting decision ────────────────────────────────────────────────────

def decide_report(victim, trauma_event, world):
    """
    Decide whether the victim will report this trauma event to authorities.
    Returns True/False.

    Factors:
      - Social support in victim's network
      - Cumulative trauma score (high → paralysis, less likely to report)
      - Repeated offense by same perp (either nudges reporting up, or creates resignation)
      - Personality traits
    """
    chars      = {c["id"]: c for c in world.get("characters", [])}
    perp_id    = trauma_event.get("perpetrator_id")
    v_traits   = set(victim.get("traits", []) + victim.get("personality_traits", []))

    prob = REPORT_BASE_CHANCE

    # Social support — count trusted friends/family in the network
    support_count = sum(
        1 for oid, rel in victim.get("relationships", {}).items()
        if rel.get("trust", 0) >= 50 and rel.get("state") in ("close_friend", "friend")
        and oid in chars
    )
    prob += min(3, support_count) * SUPPORT_REPORT_BONUS

    # Prior offenses by same perp already known
    if perp_id:
        prior_events = [
            e for e in victim.get("trauma", {}).get("events", [])
            if e["perpetrator_id"] == perp_id and e["id"] != trauma_event["id"]
        ]
        if prior_events:
            # First repeat: nudges toward reporting
            if len(prior_events) == 1:
                prob += PRIOR_OFFENSE_REPORT_BONUS
            # Multiple repeats: victim resignation sets in
            elif len(prior_events) >= 2:
                prob -= REPEAT_VICTIM_PENALTY * (len(prior_events) - 1)

    # High trauma → paralysis
    trauma_score = victim.get("trauma", {}).get("score", 0.0)
    if trauma_score > 0.6:
        prob -= HIGH_TRAUMA_REPORT_PENALTY

    # Personality
    if "courageous" in v_traits or "honest" in v_traits:
        prob += 0.10
    if "fearful" in v_traits or "passive" in v_traits or "cowardly" in v_traits:
        prob -= 0.12
    if "determined" in v_traits:
        prob += 0.08

    prob = max(0.02, min(0.95, prob))
    return random.random() < prob


# ── Non-consent assault resolution ────────────────────────────────────────

def resolve_sexual_assault(perpetrator, victim, world):
    """
    Called when a perpetrator ignores rejection and forces an act.

    Victim reaction outcomes (weighted by personality + trauma history):
      - "fled":        victim escaped; act incomplete; perpetrator exposed
      - "fought_back": victim resisted; both may be injured; perpetrator injured
      - "pleaded":     victim verbally resisted; act may have continued partially
      - "submitted":   victim froze/gave up; act completed; highest trauma

    Returns outcome dict.
    """
    vid = victim["id"]
    pid = perpetrator["id"]
    tick = world.get("tick", 0)

    v_traits = set(victim.get("traits", []) + victim.get("personality_traits", []))

    # Prior assault by same perp increases fight/flee response
    prior_by_perp = sum(
        1 for e in victim.get("trauma", {}).get("events", [])
        if e.get("perpetrator_id") == pid
    )

    # Base reaction weights
    weights = {
        "fled":        30,
        "fought_back": 20,
        "pleaded":     25,
        "submitted":   25,
    }

    # Trait modifications
    if "courageous" in v_traits or "aggressive" in v_traits:
        weights["fought_back"] += 20
        weights["fled"]        += 10
        weights["submitted"]   -= 15
    if "passive" in v_traits or "cowardly" in v_traits:
        weights["submitted"]   += 20
        weights["pleaded"]     += 10
        weights["fought_back"] -= 15
    if "fearful" in v_traits or "nervous" in v_traits:
        weights["fled"]        += 15
        weights["submitted"]   += 10
    if "determined" in v_traits:
        weights["fought_back"] += 15
        weights["fled"]        += 5

    # Repeated offense → more likely to fight back or flee (survival instinct)
    if prior_by_perp >= 1:
        weights["fought_back"] += prior_by_perp * 15
        weights["fled"]        += prior_by_perp * 10
        weights["submitted"]   -= prior_by_perp * 12
        weights["pleaded"]     -= prior_by_perp * 8

    # Normalise (floor at 1)
    for k in weights:
        weights[k] = max(1, weights[k])
    total = sum(weights.values())
    r     = random.uniform(0, total)
    cumulative = 0
    reaction = "submitted"
    for k, w in weights.items():
        cumulative += w
        if r <= cumulative:
            reaction = k
            break

    # Trauma severity depends on reaction
    severity_map = {
        "fled":        0.30,
        "fought_back": 0.35,
        "pleaded":     0.40,
        "submitted":   0.50,
    }
    trauma_severity = severity_map[reaction]

    # Add trauma event
    trauma_event = add_trauma_event(
        victim, "sexual_assault", pid, world,
        severity_override=trauma_severity,
        details={"reaction": reaction, "prior_offenses_by_perp": prior_by_perp}
    )

    # Perpetrator reputation and legal risk
    apply_reputation_event(perpetrator, "arrested",   world)   # social knowledge of act
    apply_reputation_event(perpetrator, "notoriety_violence", world)

    # If victim fought back → perpetrator may be injured
    perpetrator_injured = False
    if reaction == "fought_back":
        perpetrator_injured = random.random() < 0.45
        if perpetrator_injured:
            health = perpetrator.setdefault("health", {})
            health["pain"] = min(1.0, health.get("pain", 0.0) + 0.3)

    # Reporting decision
    reported = decide_report(victim, trauma_event, world)
    trauma_event["reported"] = reported

    if reported:
        # Trigger legal report
        _file_assault_report(perpetrator, victim, world, trauma_event)

    # Check for revenge escalation
    revenge_outcome = _check_revenge_escalation(victim, perpetrator, world)

    # Relationship: deep trust collapse
    v_rel = victim.setdefault("relationships", {}).setdefault(pid, {})
    p_rel = perpetrator.setdefault("relationships", {}).setdefault(vid, {})
    v_rel["trust"]    = min(v_rel.get("trust", 0),    -60)
    v_rel["hostility"]= min(100, v_rel.get("hostility", 0) + 40)
    v_rel["fear"]     = min(100, v_rel.get("fear",     0) + 50)
    v_rel.setdefault("conflict_flags", []).append("sexual_assault")

    # Career path nudge (deferred — happens at next job-search opportunity)
    _flag_sexwork_nudge(victim, world)

    # Emit world event
    world.setdefault("events", []).append({
        "type":         "sexual_assault",
        "tick":         tick,
        "perpetrator":  pid,
        "victim":       vid,
        "reaction":     reaction,
        "reported":     reported,
        "perpetrator_injured": perpetrator_injured,
        "revenge_triggered":   revenge_outcome is not None,
    })

    return {
        "reaction":            reaction,
        "trauma_severity":     trauma_severity,
        "reported":            reported,
        "perpetrator_injured": perpetrator_injured,
        "revenge_outcome":     revenge_outcome,
    }


def _file_assault_report(perpetrator, victim, world, trauma_event):
    """Register a criminal report with the law system."""
    try:
        from core.event_handlers import emit_event
        emit_event("sexual_assault_reported", {
            "perpetrator_id": perpetrator["id"],
            "victim_id":      victim["id"],
            "trauma_event_id": trauma_event["id"],
            "tick":           world.get("tick", 0),
        }, world)
    except Exception:
        # Fallback: stamp directly on perpetrator's legal record
        perp_legal = perpetrator.setdefault("legal", {})
        perp_legal.setdefault("record", []).append({
            "offense":    "sexual_assault",
            "reported_at": world.get("tick", 0),
            "victim_id":  victim["id"],
            "status":     "under_investigation",
        })


# ── Revenge escalation ────────────────────────────────────────────────────

def _check_revenge_escalation(victim, perpetrator, world):
    """
    Check if victim's revenge_urge has crossed the action threshold.
    If so, victim attempts violent retaliation.
    Violence escalates beyond intent — may become aggravated assault or worse.
    """
    trauma       = victim.get("trauma", {})
    urge_against = trauma.get("revenge_urge", {}).get(perpetrator["id"], 0.0)

    if urge_against < REVENGE_URGE_THRESHOLD:
        return None

    # Probability of actually acting proportional to urge
    act_prob = (urge_against - REVENGE_URGE_THRESHOLD) / (1.0 - REVENGE_URGE_THRESHOLD)
    if random.random() > act_prob:
        return None

    # Revenge occurs — determine escalation
    v_traits = set(victim.get("traits", []) + victim.get("personality_traits", []))

    # Base intent: scare/hurt the perp
    intended_severity = 0.3 + urge_against * 0.4

    # Violence goes too far — REVENGE_EXCESS_FACTOR
    actual_severity = min(1.0, intended_severity * REVENGE_EXCESS_FACTOR)

    # Classify outcome
    if actual_severity >= 0.85:
        outcome_type = "attempted_homicide"
    elif actual_severity >= 0.60:
        outcome_type = "aggravated_assault"
    else:
        outcome_type = "assault"

    # Apply consequences to perpetrator (now victim of revenge violence)
    perp_health = perpetrator.setdefault("health", {})
    perp_health["pain"] = min(1.0, perp_health.get("pain", 0.0) + actual_severity * 0.8)

    # Reputation + legal for victim (now perpetrator of revenge assault)
    apply_reputation_event(victim, "assault", world)
    if outcome_type in ("aggravated_assault", "attempted_homicide"):
        apply_reputation_event(victim, "notoriety_violence", world)

    # Stamp on victim's legal record
    victim_legal = victim.setdefault("legal", {})
    victim_legal.setdefault("record", []).append({
        "offense":   outcome_type,
        "against":   perpetrator["id"],
        "tick":      world.get("tick", 0),
        "status":    "pending",
        "motive":    "revenge_for_sexual_assault",
    })

    # Reset revenge urge (partially — the anger doesn't fully go away)
    trauma["revenge_urge"][perpetrator["id"]] = max(
        0.0, urge_against - 0.6
    )

    world.setdefault("events", []).append({
        "type":             outcome_type,
        "tick":             world.get("tick", 0),
        "perpetrator":      victim["id"],
        "victim":           perpetrator["id"],
        "motive":           "sexual_assault_revenge",
        "intended_severity": round(intended_severity, 3),
        "actual_severity":   round(actual_severity, 3),
    })

    return {
        "type":             outcome_type,
        "intended_severity": round(intended_severity, 3),
        "actual_severity":   round(actual_severity, 3),
        "went_too_far":     actual_severity > intended_severity * 1.2,
    }


# ── Career path nudge toward sex work ────────────────────────────────────

def _flag_sexwork_nudge(victim, world):
    """
    Flag that this character should have an increased probability of entering
    sex work. The actual job assignment happens in jobs.py at the next job search.
    This is a soft statistical tendency rooted in research on trauma, dissociation,
    and reclaiming agency — not a deterministic path.
    """
    trauma = victim.get("trauma", {})
    # Higher score = stronger nudge
    current_nudge = victim.get("sexwork_consideration_score", 0.0)
    nudge_gain    = trauma["score"] * 0.25
    victim["sexwork_consideration_score"] = round(
        min(1.0, current_nudge + nudge_gain), 3
    )


# ── Daily tick: natural healing ───────────────────────────────────────────

def tick_trauma(world):
    """
    Daily pass: very slow natural decay of trauma score.
    Support network accelerates healing.
    """
    chars = {c["id"]: c for c in world.get("characters", [])
             if not c.get("is_offscreen")}

    for cid, c in chars.items():
        trauma = c.get("trauma")
        if not trauma or trauma.get("score", 0) == 0:
            continue

        # Base decay
        decay = TRAUMA_DECAY_PER_TICK * 24  # called daily

        # Support accelerates healing
        support_count = sum(
            1 for oid, rel in c.get("relationships", {}).items()
            if rel.get("trust", 0) >= 55 and rel.get("state") in ("close_friend", "friend")
            and oid in chars
        )
        decay += support_count * TRAUMA_DECAY_PER_TICK * 8

        trauma["score"] = max(0.0, round(trauma["score"] - decay, 5))

        # Deactivate PTSD if score drops below threshold
        if trauma["ptsd_active"] and trauma["score"] < PTSD_THRESHOLD * 0.6:
            trauma["ptsd_active"] = False

        # Slowly reduce intimacy avoidance with healing
        if trauma.get("intimacy_avoidance", 0) > 0:
            trauma["intimacy_avoidance"] = max(
                0.0,
                round(trauma["intimacy_avoidance"] - decay * 0.5, 5)
            )


# ── LLM context ───────────────────────────────────────────────────────────

def get_trauma_context(c, world):
    """Summarise trauma state for LLM context — no perpetrator names by default."""
    trauma = c.get("trauma", {})
    if not trauma or trauma.get("score", 0) < 0.05:
        return {}

    lines = []
    score = trauma["score"]
    lines.append(f"trauma_score={'severe' if score>0.7 else 'moderate' if score>0.35 else 'mild'} ({score:.2f})")
    if trauma.get("ptsd_active"):
        lines.append("ptsd_active=True — may experience flashbacks, startle response, avoidance")
    if trauma.get("intimacy_avoidance", 0) > 0.1:
        lines.append(f"intimacy_avoidance={trauma['intimacy_avoidance']:.2f} — strongly reluctant to initiate or accept intimacy")
    if trauma.get("trust_floor", 0) > 0.1:
        lines.append(f"trust_floor={trauma['trust_floor']:.2f} — requires high trust before any intimate stage")

    # Revenge urge (only flag if very high, and as an internal state, not naming target)
    for perp_id, urge in trauma.get("revenge_urge", {}).items():
        if urge > 0.5:
            lines.append(f"revenge_urge_high — intense anger toward someone who wronged them (urge={urge:.2f})")
            break

    return {"trauma": lines}
