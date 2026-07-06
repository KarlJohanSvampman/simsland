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
    "betrayal_intimate":          0.20,
    "physical_assault":           0.20,
    "witnessed_violence":         0.10,
    "public_humiliation":         0.08,
    "stalking":                   0.15,
    "harassment":                 0.10,
    # Religious repression types
    "identity_shame":             0.12,
    "porn_shame":                 0.06,
    "sexual_curiosity_shame":     0.05,
    "residual_identity_shame":    0.08,
    "identity_crisis_onset":      0.15,
    # Pregnancy drama
    "unplanned_pregnancy_discovery": 0.14,
    "abortion_grief":             0.10,
    "adoption_grief":             0.12,
    "family_pregnancy_discovery": 0.08,
    "family_pregnancy_showing":   0.05,
    "family_pregnancy_birth":     0.04,
    "family_pregnancy_abortion_decision": 0.10,
    "family_pregnancy_adoption_decision": 0.07,
    "family_pregnancy_keep_decision":     0.05,
    "pregnancy_discovery":        0.06,
    "pregnancy_abortion_decision":0.08,
    "pregnancy_keep_decision":    0.04,
}

# Psychological thresholds
PTSD_THRESHOLD            = 0.50   # trauma.score above this activates PTSD
TRAUMA_DECAY_PER_TICK     = 0.00003  # very slow natural healing


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
