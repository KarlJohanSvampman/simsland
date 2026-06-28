"""
lt_needs.py — long-term need tracking and frustration system.

Each character has c["lt_needs"]:
  {
    "socialize":   {"points": 25, "last_satisfied_tick": 0, "week_count": 0, "frustration": 0.0},
    "exercise":    {"points": 15, ...},
    ...
  }

- "points" comes from a 100-point budget distributed at character creation.
  A need with 0 points is ignored.
- "last_satisfied_tick" is updated when a satisfying activity completes.
- "week_count" resets each game week; tracks how many times satisfied this week.
- "frustration" (0-1) accumulates as the need goes unmet. At high frustration it
  raises emotional_temperature baseline and stress.

Called from sim_loop on a slow cadence (e.g., every 30 sim-minutes).
"""

import math
import random

# Game ticks per week (1 tick = 1 sec, 1 game-min = 60 ticks, week = 10080 game-min)
TICKS_PER_GAME_MINUTE = 60
TICKS_PER_GAME_WEEK   = TICKS_PER_GAME_MINUTE * 60 * 24 * 7   # 3,628,800

# How many satisfying events per week are "enough" (scaled by points)
# A 100-pt need wants 3 satisfactions/week; a 20-pt need wants 1.
def weekly_target(points):
    return max(1, round(points / 33))

# Frustration accrues per tick when unmet. Decays when met.
FRUSTRATION_ACCRUAL_PER_TICK = 1 / (TICKS_PER_GAME_WEEK * 2)  # full frustration = 2 weeks unmet
FRUSTRATION_DECAY_ON_SATISFY = 0.4


# ── DEFAULT NEED BUDGET DISTRIBUTION ─────────────────────────────────────────
# Used when character is created without a personalised budget.
# Traits can shift weights later.
DEFAULT_BUDGET_WEIGHTS = {
    "socialize":   20,
    "exercise":    15,
    "creative":    10,
    "nature":      10,
    "learning":     8,
    "romance":      8,
    "intimacy":     7,
    "solitude":     7,
    "spirituality": 5,
    "purpose":      5,
    "adventure":    3,
    "play":         2,
}

def distribute_lt_needs(c, budget=100, world=None):
    """
    Assign c["lt_needs"] based on a personalised 100-point budget.
    If the character already has lt_needs with non-zero points, skip.
    """
    existing = c.get("lt_needs", {})
    if any(v.get("points", 0) > 0 for v in existing.values()):
        return

    # Start from default weights
    weights = dict(DEFAULT_BUDGET_WEIGHTS)

    # Trait modifiers
    traits = c.get("traits", [])
    if "introvert" in traits:
        weights["solitude"] = weights.get("solitude", 7) + 15
        weights["socialize"] = max(0, weights.get("socialize", 20) - 10)
    if "extrovert" in traits:
        weights["socialize"] = weights.get("socialize", 20) + 15
        weights["solitude"]  = max(0, weights.get("solitude", 7) - 5)
    if "athletic" in traits or "disciplined" in traits:
        weights["exercise"] = weights.get("exercise", 15) + 12
    if "lazy" in traits or "apathetic" in traits:
        weights["exercise"] = max(0, weights.get("exercise", 15) - 8)
    if "creative" in traits:
        weights["creative"] = weights.get("creative", 10) + 12
    if "curious" in traits or "intellectual" in traits:
        weights["learning"] = weights.get("learning", 8) + 10
    if "spiritual" in traits:
        weights["spirituality"] = weights.get("spirituality", 5) + 15
    if "romantic" in traits:
        weights["romance"] = weights.get("romance", 8) + 10
        weights["intimacy"] = weights.get("intimacy", 7) + 8
    if "adventurous" in traits or "thrill_seeking" in traits:
        weights["adventure"] = weights.get("adventure", 3) + 12
    if "nature_lover" in traits:
        weights["nature"] = weights.get("nature", 10) + 12
    if "playful" in traits:
        weights["play"] = weights.get("play", 2) + 10

    # Normalise to budget
    total = sum(weights.values())
    lt = {}
    remaining = budget
    keys = list(weights.keys())
    for i, k in enumerate(keys):
        if i == len(keys) - 1:
            pts = remaining
        else:
            pts = round(weights[k] / total * budget)
        remaining -= pts
        if pts > 0:
            lt[k] = {
                "points":               pts,
                "last_satisfied_tick":  0,
                "week_count":           0,
                "frustration":          0.0,
            }

    c["lt_needs"] = lt


# ── TICK UPDATE ───────────────────────────────────────────────────────────────

def update_lt_needs(c, world):
    """
    Update frustration for each long-term need. Call on slow cadence (~30 game-min).
    """
    lt   = c.get("lt_needs", {})
    tick = world.get("tick", 0)

    total_frustration = 0.0

    for need_id, nd in lt.items():
        pts = nd.get("points", 0)
        if pts == 0:
            continue

        # Frustration grows proportional to need weight and time since last satisfied
        ticks_since = tick - nd.get("last_satisfied_tick", 0)
        # If never satisfied and tick=0, don't penalise immediately
        if nd.get("last_satisfied_tick", 0) == 0 and tick < TICKS_PER_GAME_WEEK:
            ticks_since = 0

        max_comfortable = TICKS_PER_GAME_WEEK   # frustration starts after 1 week
        if ticks_since > max_comfortable:
            overdue_fraction = (ticks_since - max_comfortable) / TICKS_PER_GAME_WEEK
            target_frustration = min(1.0, overdue_fraction * (pts / 50))
        else:
            target_frustration = 0.0

        # Lerp toward target
        current = nd.get("frustration", 0.0)
        nd["frustration"] = current + (target_frustration - current) * 0.05

        total_frustration += nd["frustration"] * (pts / 100)

    # Push frustration into stress and emotional temperature
    _apply_lt_frustration(c, total_frustration)


def _apply_lt_frustration(c, total_frustration):
    """total_frustration is 0-1 weighted average. Raise stress + emotional temp."""
    if total_frustration < 0.1:
        return
    stress_bump = total_frustration * 20          # up to +20 stress
    c["stress"] = min(100, c.get("stress", 0) + stress_bump * 0.005)  # gentle drift

    # Raise emotional temperature toward "irritable" baseline
    from brain.emotion import apply_emotion_inertia
    if total_frustration > 0.5:
        apply_emotion_inertia(c, llm_emotion="annoyed")


# ── SATISFY A NEED ────────────────────────────────────────────────────────────

def satisfy_lt_need(c, need_id, world):
    """
    Call when a character completes an activity that satisfies a long-term need.
    """
    lt = c.get("lt_needs", {})
    if need_id not in lt:
        return

    nd = lt[need_id]
    nd["last_satisfied_tick"] = world.get("tick", 0)
    nd["week_count"] = nd.get("week_count", 0) + 1
    nd["frustration"] = max(0.0, nd["frustration"] - FRUSTRATION_DECAY_ON_SATISFY)

    # Reduce stress slightly
    c["stress"] = max(0, c.get("stress", 0) - 5)


def reset_weekly_counts(c):
    """Call at start of each game week."""
    for nd in c.get("lt_needs", {}).values():
        nd["week_count"] = 0


# ── LT NEED CONTEXT FOR LLM ──────────────────────────────────────────────────

def build_lt_need_context(c):
    """Return text lines describing unfulfilled long-term needs for LLM prompt."""
    lt     = c.get("lt_needs", {})
    issues = []
    for need_id, nd in lt.items():
        pts = nd.get("points", 0)
        if pts == 0:
            continue
        frustration = nd.get("frustration", 0.0)
        if frustration > 0.6:
            issues.append(
                f"You've been neglecting your need for {need_id.replace('_', ' ')} "
                f"for too long — you feel a deep restlessness and frustration about it."
            )
        elif frustration > 0.3:
            issues.append(
                f"You haven't had enough {need_id.replace('_', ' ')} lately "
                f"and it's starting to weigh on you."
            )
    return issues
