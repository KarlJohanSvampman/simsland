"""
brain/situations/scoring.py

Deterministic, explainable scoring for candidate situations -- no LLM call
anywhere in this file. Candidates are drawn from the character's own
c["active_intentions"] (already populated every tick by the existing,
scattered trigger/eligibility logic this reuses rather than duplicates:
systems/body_intentions.py, systems/lt_needs.py, systems/social_intentions.py,
systems/expectations.py, brain/intentions.py's deadline escalation, ...).
This module's job starts *after* that: turn each already-real candidate
into an explainable, comparable score.

Honest scoping note: the proposal this implements asks for each factor
(urgency/relevance/persistence/event_significance/relationship_significance)
to be computed from dedicated per-situation-type logic (situations/needs.py,
situations/social.py, ...). Building that whole registry would mean
re-authoring every existing intention generator's trigger logic a second
time in a new shape. Instead, each factor below is derived from real,
existing fields already present on every intention (priority, category,
target_id, created_at, window_end_tick, source, interrupts) -- genuine
signals, not placeholders, just not yet split into a fully separate
per-situation-type registry. See selector.py's module docstring for what
a fuller adoption (situations/*.py registry, per-situation option lists)
would still need.
"""

from . import history as _history

# =========================================================
# INTERRUPT LEVELS
# =========================================================

CRITICAL   = 3
HIGH       = 2
NORMAL     = 1
BACKGROUND = 0

_LEVEL_NAMES = {CRITICAL: "CRITICAL", HIGH: "HIGH", NORMAL: "NORMAL", BACKGROUND: "BACKGROUND"}

# category -> interrupt level, mirroring brain/intentions.py's own
# CATEGORY_PRIORITY tiering (survival=100 down to impulse=10) -- this
# reuses that same hierarchy rather than inventing a second, potentially
# inconsistent one.
_CATEGORY_LEVEL = {
    "survival": HIGH,       # bumped to CRITICAL below once genuinely urgent
    "health":   HIGH,
    "schedule": HIGH,
    "social":   NORMAL,
    "identity": NORMAL,
    "chores":   NORMAL,
    "leisure":  BACKGROUND,
    "impulse":  BACKGROUND,
}

# A survival/health intention only earns CRITICAL once it's genuinely
# urgent -- matches brain/agent_loop.py's own _BODY_INTERRUPT_THRESHOLDS
# order of magnitude (bladder>=88, hunger>=82, fatigue>=90, ...) without
# hard-coding a duplicate per-need table: those generators already bake
# "how urgent" into the intention's own priority (body_intentions.py's
# threshold tiers, e.g. bladder_urgent=97 vs bladder_full=80), so a high
# enough priority within survival/health is itself the signal.
_CRITICAL_PRIORITY_THRESHOLD = 90


def interrupt_level(intention):
    category = intention.get("category", "impulse")
    level = _CATEGORY_LEVEL.get(category, BACKGROUND)

    if category in ("survival", "health") and intention.get("priority", 0) >= _CRITICAL_PRIORITY_THRESHOLD:
        level = CRITICAL

    # An intention explicitly flagged "interrupts" (body_intentions.py's
    # urgent bladder/bowels/exhaustion entries, weather.py's severe
    # exposure) always earns at least HIGH regardless of category.
    if intention.get("interrupts") and level < HIGH:
        level = HIGH

    return level


def level_name(level):
    return _LEVEL_NAMES.get(level, "NORMAL")


# =========================================================
# INTERRUPTIBILITY OF THE CURRENT ACTIVITY
# =========================================================
# How willing a character already mid-activity is to be pulled away, per
# the proposal's step 5 -- prevents a HIGH-scoring but only mildly urgent
# situation from constantly yanking someone out of something like eating
# or sleeping, while still letting a genuinely CRITICAL one through
# regardless (see selector.py: CRITICAL always bypasses this check).

NONE_ = 0
LOW   = 1
MEDIUM = 2
HIGH_INTERRUPTIBILITY = 3

ACTIVITY_INTERRUPTIBILITY = {
    "sleep":        LOW,
    "eat":          NONE_,
    "eat_meal":     NONE_,
    "eat_snack":    LOW,
    "cook":         LOW,
    "cook_meal":    LOW,
    "shower":       NONE_,
    "use_toilet":   NONE_,
    "use_toilet_bowels": NONE_,
    "socialize":    MEDIUM,
    "sing_karaoke": MEDIUM,
    "watch_tv":     HIGH_INTERRUPTIBILITY,
    "walk":         HIGH_INTERRUPTIBILITY,
    "interact":     MEDIUM,
    "wait":         HIGH_INTERRUPTIBILITY,
}
DEFAULT_ACTIVITY_INTERRUPTIBILITY = MEDIUM

# The minimum interrupt level (of the CANDIDATE situation) required to
# override a given interruptibility tier of the current activity.
_REQUIRED_LEVEL_FOR_INTERRUPTIBILITY = {
    NONE_:               CRITICAL,   # only a CRITICAL situation gets through at all
    LOW:                 HIGH,
    MEDIUM:              NORMAL,
    HIGH_INTERRUPTIBILITY: BACKGROUND,
}


def current_activity_interruptibility(c):
    act = c.get("activity")
    if not act:
        return HIGH_INTERRUPTIBILITY
    return ACTIVITY_INTERRUPTIBILITY.get(act.get("type"), DEFAULT_ACTIVITY_INTERRUPTIBILITY)


def can_interrupt(intention_level, c):
    if intention_level == CRITICAL:
        return True
    tier = current_activity_interruptibility(c)
    return intention_level >= _REQUIRED_LEVEL_FOR_INTERRUPTIBILITY.get(tier, NORMAL)


# =========================================================
# TRAIT AFFINITY
# =========================================================
# Small, additive personality bias (proposal step 12: kept in [-30, +30],
# personality biases cognition rather than overriding circumstances).
# Matched against intention TYPE/CATEGORY keywords rather than a full
# per-trait taxonomy -- real trait tags already used elsewhere in this
# codebase (systems/lt_needs.py's distribute_lt_needs, systems/
# character_gen.py), reused here rather than invented fresh.

_TRAIT_AFFINITY_RULES = [
    # (trait, {intention types or categories}, bonus)
    ("ambitious",     {"work", "pay_bills", "go_to_work"}, 20),
    ("disciplined",   {"work"}, 10),
    ("family_oriented", {"family"}, 20),
    ("family_oriented", {"expectation:family_dinner_together", "expectation:get_kids_to_school"}, 15),
    ("anxious",       {"seek_shelter", "call_911"}, 15),
    ("frugal",        {"expectation:file_taxes", "expectation:pay_bill", "pay_bills"}, 15),
    ("extrovert",     {"socialize", "contact_person", "gossip", "visit_person"}, 15),
    ("introvert",     {"seek_solitude"}, 15),
    ("introvert",     {"socialize", "contact_person"}, -10),
    ("spiritual",     {"spiritual_practice"}, 15),
    ("curious",       {"learn_something"}, 15),
    ("intellectual",  {"learn_something"}, 15),
    ("creative",      {"creative_outlet"}, 15),
    ("nature_lover",  {"outdoor_time"}, 15),
    ("romantic",      {"seek_romance", "seek_intimacy", "flirt"}, 15),
]

_AFFINITY_CAP = 30


def trait_affinity(intention, traits):
    if not traits:
        return 0.0
    traits_set = set(traits)
    itype = intention.get("type", "")
    category = intention.get("category", "")
    total = 0.0
    for trait, targets, bonus in _TRAIT_AFFINITY_RULES:
        if trait in traits_set and (itype in targets or category in targets):
            total += bonus
    return max(-_AFFINITY_CAP, min(_AFFINITY_CAP, total))


# =========================================================
# PER-FACTOR SCORING
# =========================================================

def urgency(intention):
    """0-100. The generators that already populate active_intentions
    (body_intentions.py's threshold tiers, lt_needs.py's frustration-based
    curve) already encode "how urgent" as the intention's own priority --
    reused directly rather than re-derived from raw body/need state a
    second time, which would require this module to special-case every
    intention type's own underlying stat."""
    return max(0.0, min(100.0, float(intention.get("priority", 0))))


def relevance(intention, c):
    """0-100. Boosted when the situation is explicitly tied to something
    the character already has real, standing stake in -- a schedule-
    driven expectation (source == "expectation", or an expectation: type)
    is the clearest, cheaply-checkable case of "connects to a real
    commitment" available without deep per-type modeling."""
    base = max(0.0, min(100.0, float(intention.get("priority", 0))))
    source = intention.get("source", "")
    itype = intention.get("type", "")
    if source == "expectation" or itype.startswith("expectation:"):
        base = min(100.0, base + 20.0)
    if intention.get("category") == "schedule":
        base = min(100.0, base + 10.0)
    return base


def persistence(intention, tick):
    """0-100. How long this has gone unresolved -- rewards a lower-
    urgency-but-repeatedly-ignored matter the way the proposal's step 9
    describes, using the intention's own created_at (every intention
    already carries this, see brain/intentions.py::add_intention)."""
    created_at = intention.get("created_at")
    if created_at is None:
        return 0.0
    age_ticks = max(0, tick - created_at)
    # Scales to 100 over ~2 real hours of the same intention staying
    # active -- deliberately slower than urgency/novelty so it only ever
    # matters for something that's been hanging around a while.
    return max(0.0, min(100.0, age_ticks / (2 * _history.TICKS_PER_HOUR) * 100.0))


def event_significance(intention, tick):
    """0-100. A situation that was JUST created (this tick or very
    recently) reads as event-driven -- something just happened -- versus
    one that's been sitting in active_intentions for a while, which is
    ambient rather than a fresh stimulus."""
    created_at = intention.get("created_at")
    if created_at is None:
        return 0.0
    age_ticks = max(0, tick - created_at)
    if age_ticks <= 5:
        return 100.0
    if age_ticks >= 5 * _history.TICKS_PER_MINUTE:
        return 0.0
    # Linear falloff between "just now" and "5 minutes ago".
    return max(0.0, 100.0 * (1 - age_ticks / (5 * _history.TICKS_PER_MINUTE)))


def relationship_significance(intention, c, world):
    """0-30 (proposal step 13's own range). Uses the real relationship
    model (social/relationship_score.py) rather than a hard-coded
    stranger/friend/family table -- a hostile spouse still scores high
    here, same as the proposal's own example."""
    target_id = intention.get("target_id")
    if not target_id:
        return 0.0
    other = world.get("characters", {}).get(target_id)
    if not other:
        return 0.0
    try:
        from social.relationship_score import relationship_score
        score = relationship_score(c, other)  # already roughly 0-100-ish
    except Exception:
        return 0.0
    return max(0.0, min(30.0, abs(score) * 0.3))


# =========================================================
# COMBINE
# =========================================================

WEIGHTS = {
    "urgency":                  0.35,
    "relevance":                0.25,
    "persistence":              0.15,
    "novelty":                  0.10,
    "event_significance":       0.10,
    "relationship_significance": 0.05,
}


def score_situation(intention, situation_id, c, world, tick):
    """Returns (score, breakdown_dict) -- the breakdown is kept around so
    a debug/inspector view can show *why* a situation won, per the
    proposal's own explainability goal."""
    category_base = float(intention.get("priority", 0)) * 0  # base_priority folded into urgency above already
    u  = urgency(intention)
    rl = relevance(intention, c)
    p  = persistence(intention, tick)
    n  = _history.novelty(c, situation_id, tick)
    ev = event_significance(intention, tick)
    rs = relationship_significance(intention, c, world)
    ta = trait_affinity(intention, c.get("traits", []))
    cd = _history.cooldown_penalty(c, situation_id, intention.get("type", ""), tick)

    score = (
        category_base
        + u  * WEIGHTS["urgency"]
        + rl * WEIGHTS["relevance"]
        + p  * WEIGHTS["persistence"]
        + n  * WEIGHTS["novelty"]
        + ev * WEIGHTS["event_significance"]
        + rs * WEIGHTS["relationship_significance"]
        + ta
        - cd
    )

    breakdown = {
        "urgency": u, "relevance": rl, "persistence": p, "novelty": n,
        "event_significance": ev, "relationship_significance": rs,
        "trait_affinity": ta, "cooldown_penalty": cd, "score": score,
    }
    return score, breakdown
