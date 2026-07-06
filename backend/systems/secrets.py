"""
systems/secrets.py — secret-keeping and deception engine

A secret is stored on the *keeper* character:

    c["secrets"] = [
        {
            "id":         "sec_abc",
            "content":    "I embezzled $40k from my employer",
            "severity":   0.9,        # 0–1: gossip → life-ruining
            "stakes":     "prison, career, marriage",
            "category":   "crime",    # crime, infidelity, identity, finance,
                                      # health, past, relationship, other
            "subject_ids": [],        # character ids the secret is about
            "known_by":   [],         # char ids who've been told or discovered
            "created_tick": 0,

            "deception_targets": {
                "char_xyz": {
                    "active_lie":      "I've been working overtime",
                    "deceived_level":  0.85,  # 1=fully fooled, 0=knows truth
                    "suspicion_level": 0.15,  # 0=no suspicion, 1=certain something's off
                    "suspicion_of":    None,  # char_id blamed instead, or None
                    "false_belief":    None,  # what they think the truth is
                    "last_probed_tick": 0,
                }
            }
        }
    ]
"""

import random
import uuid

# ---------------------------------------------------------------------------
# Secret categories and default severity ranges
# ---------------------------------------------------------------------------

CATEGORIES = {
    "crime":        (0.6, 1.0),
    "infidelity":   (0.5, 0.9),
    "identity":     (0.4, 0.8),
    "finance":      (0.3, 0.8),
    "health":       (0.2, 0.7),
    "past":         (0.1, 0.6),
    "relationship": (0.2, 0.6),
    "other":        (0.1, 0.5),
}

# How much deceived_level decays per tick naturally (0 = never degrades on its own)
_DECEPTION_DECAY_PER_TICK = 0.00005   # ~0.4% per day

# How much suspicion rises per tick when keeper acts inconsistently
_SUSPICION_RISE_INCONSISTENT = 0.002

# ---------------------------------------------------------------------------
# Create / add a secret
# ---------------------------------------------------------------------------

def add_secret(keeper, content, category="other", severity=None, stakes=None,
               subject_ids=None, world=None):
    """
    Create a new secret on `keeper` and return it.

    severity defaults to the midpoint of the category range if not supplied.
    """
    lo, hi = CATEGORIES.get(category, (0.1, 0.5))
    if severity is None:
        severity = round((lo + hi) / 2, 2)
    severity = max(lo, min(hi, severity))

    secret = {
        "id":              f"sec_{uuid.uuid4().hex[:8]}",
        "content":         content,
        "severity":        severity,
        "stakes":          stakes or "",
        "category":        category,
        "subject_ids":     list(subject_ids or []),
        "known_by":        [],
        "created_tick":    world.get("tick", 0) if world else 0,
        "deception_targets": {},
    }
    keeper.setdefault("secrets", []).append(secret)
    return secret


# ---------------------------------------------------------------------------
# Add a deception target to an existing secret
# ---------------------------------------------------------------------------

def add_deception_target(secret, target_id, active_lie=None,
                         initial_deceived=1.0, false_belief=None):
    """
    Register `target_id` as someone being deceived about this secret.

    initial_deceived = 1.0 means they haven't a clue.
    """
    secret["deception_targets"][target_id] = {
        "active_lie":       active_lie or "",
        "deceived_level":   float(initial_deceived),
        "suspicion_level":  0.0,
        "suspicion_of":     None,
        "false_belief":     false_belief,
        "last_probed_tick": 0,
    }
    return secret["deception_targets"][target_id]


# ---------------------------------------------------------------------------
# Reveal / discover a secret
# ---------------------------------------------------------------------------

def reveal_secret(secret, discoverer_id, world, method="told"):
    """
    Mark `discoverer_id` as knowing the secret.
    Removes them from deception_targets (they know the truth now).
    Updates deceived_level to 0 if they were a target.

    method: "told" | "discovered" | "witnessed" | "rumour"
    """
    if discoverer_id not in secret.get("known_by", []):
        secret.setdefault("known_by", []).append(discoverer_id)

    dt = secret.get("deception_targets", {}).pop(discoverer_id, None)
    return {"secret_id": secret["id"], "method": method, "dt_was": dt}


# ---------------------------------------------------------------------------
# Update suspicion for a target
# ---------------------------------------------------------------------------

def update_suspicion(secret, target_id, delta, suspicion_of=None, false_belief=None):
    """
    Shift suspicion for a specific target.
    +delta = more suspicious, -delta = less suspicious (reassured).
    Optionally redirect suspicion to another char or update false belief.
    """
    dt = secret.get("deception_targets", {}).get(target_id)
    if not dt:
        return
    dt["suspicion_level"] = max(0.0, min(1.0, dt["suspicion_level"] + delta))
    dt["deceived_level"]  = max(0.0, min(1.0, dt["deceived_level"]  - delta * 0.6))
    if suspicion_of is not None:
        dt["suspicion_of"] = suspicion_of
    if false_belief is not None:
        dt["false_belief"] = false_belief


# ---------------------------------------------------------------------------
# Tick — decay deception over time
# ---------------------------------------------------------------------------

def tick_secrets(world):
    """
    Called each tick (or each day). Slowly erodes deceived_level;
    characters become slightly more suspicious over long stretches
    when they haven't been reassured.
    """
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        for secret in c.get("secrets", []):
            for tid, dt in secret.get("deception_targets", {}).items():
                # Natural decay of deception confidence
                dt["deceived_level"] = max(
                    0.0, dt["deceived_level"] - _DECEPTION_DECAY_PER_TICK
                )
                # Creeping suspicion when time passes since last probe
                ticks_since = tick - dt.get("last_probed_tick", tick)
                if ticks_since > 720:   # ~30 days
                    dt["suspicion_level"] = min(
                        1.0, dt["suspicion_level"] + 0.0001
                    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_secrets_about(world, subject_id):
    """Return all secrets that list subject_id in subject_ids."""
    out = []
    for c in world.get("characters", {}).values():
        for s in c.get("secrets", []):
            if subject_id in s.get("subject_ids", []):
                out.append({"keeper_id": c["id"], "secret": s})
    return out


def get_secrets_targeting(world, target_id):
    """Return all deception targets aimed at target_id."""
    out = []
    for c in world.get("characters", {}).values():
        for s in c.get("secrets", []):
            dt = s.get("deception_targets", {}).get(target_id)
            if dt:
                out.append({"keeper_id": c["id"], "secret": s, "dt": dt})
    return out


def get_secret_by_id(c, secret_id):
    return next((s for s in c.get("secrets", []) if s["id"] == secret_id), None)
