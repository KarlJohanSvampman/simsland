"""
systems/worries.py — behavior-based suspicion

A worry is a standing, decaying belief that something's off about a
specific person, stored on the *observer*:

    c["worries"] = {
        "char_xyz": {
            "suspicion_level": 0.3,      # 0-1
            "false_belief":    None,     # LLM-authored guess (form_theory)
            "suspicion_of":    None,     # redirected blame -- another char id
            "triggers":        [{"tick": 1200, "kind": "routine_deviation",
                                  "note": "..."}],   # capped, last 5
            "created_tick": 900, "last_updated_tick": 1200,
        }
    }

Deliberately mirrors systems/secrets.py's deception_targets shape
(same suspicion_level/false_belief/suspicion_of vocabulary) but is its
own structure, decoupled from requiring a specific secret to exist --
secrets.py stays dormant. Populated by: perception.py's habit-deviation
check, excuses.py's caught-lying/evasive-answer detection, and
action_router.py's check_device "getting caught" roll.
"""

MAX_TRIGGERS = 5
ACTIVE_THRESHOLD = 0.1

# Passive decay per cleanup call (systems/social_rules.py-style cadence
# via sim_loop.py's contract_checks block) -- small enough that an
# unconfirmed worry fades over real time if nothing reinforces it,
# same reasoning as secrets.py's tick_secrets decay.
_DECAY_PER_SWEEP = 0.01


def ensure_worries(c):
    c.setdefault("worries", {})
    return c["worries"]


def bump_suspicion(observer, subject_id, delta, kind, note, world):
    """Raise (or, with a negative delta, ease) observer's suspicion of
    subject_id. Creates the worry entry on first use, clamps to 0-1,
    records a capped trigger history."""
    worries = ensure_worries(observer)
    worry = worries.setdefault(subject_id, {
        "suspicion_level": 0.0,
        "false_belief":    None,
        "suspicion_of":    None,
        "triggers":        [],
        "created_tick":    world.get("tick", 0),
        "last_updated_tick": world.get("tick", 0),
    })
    worry["suspicion_level"] = max(0.0, min(1.0, worry["suspicion_level"] + delta))
    worry["triggers"].append({"tick": world.get("tick", 0), "kind": kind, "note": note})
    worry["triggers"] = worry["triggers"][-MAX_TRIGGERS:]
    worry["last_updated_tick"] = world.get("tick", 0)
    return worry


def decay_worries(world):
    """Periodic passive decay -- called on the same slow cadence as
    check_contract_violations/cleanup_expired_rule_exceptions. Deletes
    entries that have decayed to near-zero with no recent trigger, so
    c["worries"] stays bounded over a long-lived character's life."""
    for c in world.get("characters", {}).values():
        worries = c.get("worries")
        if not worries:
            continue
        for subject_id in list(worries.keys()):
            worry = worries[subject_id]
            worry["suspicion_level"] = max(0.0, worry["suspicion_level"] - _DECAY_PER_SWEEP)
            if worry["suspicion_level"] <= 0.0 and not worry.get("false_belief"):
                del worries[subject_id]


def get_active_worries(c):
    """Worries above the narrative-relevance floor, for context_builder.py."""
    return {
        sid: w for sid, w in c.get("worries", {}).items()
        if w.get("suspicion_level", 0) > ACTIVE_THRESHOLD
    }
