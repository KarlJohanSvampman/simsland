"""
systems/trait_budget.py — annual trait/belief-learning budget.

Every character can learn (peer-imitation or value-driven trait
promotion, or belief adoption -- systems/peer_influence.py) only up to a
per-year budget, refreshed on their own birthday
(calendar_events.py::assign_birthday), scaled by how much (and how
closely) they've socialized since the last refresh. One shared pool for
traits+beliefs combined -- the "traits learned per year" request didn't
distinguish the two, and splitting into separate trait/belief pools would
double the tunable surface for no clear benefit.
"""

import random

_BASE_BUDGET = {"adult": 2, "teen": 4, "child": 1, "elderly": -1}

# Calendar "hour" spans many ticks at TICK_RATE_SECONDS=1 (see
# sim_loop.py::_is_monday_midnight's own caution about this), so the
# birthday check in sim_loop.py can fire repeatedly within the same
# in-game hour. Guard the once-a-year recompute (and especially the
# elderly trait-drop, which is NOT idempotent) against re-firing on
# those repeats.
_MIN_TICKS_BETWEEN_RECOMPUTE = 100


def ensure_budget(c):
    return c.setdefault("trait_learning_budget", {
        "year_anchor_tick":  0,
        "learned_this_year": 0,
        # None = not yet computed; try_consume_learn_slot() treats that as
        # unlimited until this character's first birthday recompute.
        "budget_this_year":  None,
    })


def record_social_engagement(c, hours, designation_level):
    """Called from peer_influence.py::resolve_cognitive_adoption for every
    relationship processed -- rolling accumulator consumed (and reset) at
    the next birthday recompute below."""
    acc = c.setdefault("_social_engagement", {"hours": 0.0, "level_sum": 0.0, "samples": 0})
    acc["hours"]     += hours
    acc["level_sum"] += designation_level
    acc["samples"]   += 1


def recompute_budget_on_birthday(c, world):
    """Once a year (on `c`'s own birthday, called from sim_loop.py), sets
    a fresh budget_this_year from the base per-age-group rate scaled by
    social engagement since the last recompute, resets the learned
    counter, and -- for elderly characters (negative base budget) --
    drops one learned trait as a mild decline effect."""
    budget = ensure_budget(c)
    tick = world.get("tick", 0)
    if tick - budget.get("year_anchor_tick", -_MIN_TICKS_BETWEEN_RECOMPUTE * 2) < _MIN_TICKS_BETWEEN_RECOMPUTE:
        return

    base = _BASE_BUDGET.get(c.get("age_group"), 2)
    acc = c.get("_social_engagement", {"hours": 0.0, "level_sum": 0.0, "samples": 0})
    samples = max(1, acc.get("samples", 0))
    avg_hours = acc.get("hours", 0.0) / samples
    avg_level = acc.get("level_sum", 0.0) / samples

    if base < 0:
        budget["budget_this_year"] = base  # elderly: fixed decline rate, not engagement-scaled
    else:
        multiplier = 1.0 + min(1.5, (avg_hours / 20.0) * 0.5 + (avg_level / 4.0) * 0.5)
        budget["budget_this_year"] = max(0, round(base * multiplier))

    budget["learned_this_year"] = 0
    budget["year_anchor_tick"]  = tick
    c["_social_engagement"] = {"hours": 0.0, "level_sum": 0.0, "samples": 0}

    if budget["budget_this_year"] < 0:
        _decline_one_trait(c, world)


def _decline_one_trait(c, world):
    learned = c.get("personality_traits", [])
    if not learned:
        return
    trait = random.choice(learned)
    learned.remove(trait)
    c.setdefault("absorbed_traits", []).append({
        "trait": trait, "source": "cognitive_decline",
        "acquired_tick": world.get("tick", 0), "removed": True,
    })


def try_consume_learn_slot(c):
    """True (and decrements the counter) if `c` still has budget to learn
    a new trait/belief this year."""
    budget = ensure_budget(c)
    remaining = budget.get("budget_this_year")
    if remaining is None:
        return True
    if budget.get("learned_this_year", 0) >= remaining:
        return False
    budget["learned_this_year"] += 1
    return True
