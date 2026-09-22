import random

# Module-level current tick, stamped once per sim tick from sim_loop.py
# (add_intention() has no world param -- 44 call sites across the
# codebase call it as add_intention(c, {...}) with no world reference --
# so a tiny global is far less invasive than threading world through
# every caller just to timestamp when an intention was created).
_CURRENT_TICK = 0


def set_current_tick(t):
    global _CURRENT_TICK
    _CURRENT_TICK = t


# =========================================================
# INTENTION TYPES
# =========================================================

INTENTION_TYPES = {
    "wealth":     {"priority": 50, "decay": 0.01},
    "romance":    {"priority": 40, "decay": 0.005},
    "friendship": {"priority": 35, "decay": 0.005},
    "survival":   {"priority": 90, "decay": 0},
    "career":     {"priority": 45, "decay": 0.002},
    "comfort":    {"priority": 30, "decay": 0.01},
}

# =========================================================
# CATEGORY PRIORITY
# =========================================================

# Yellow -> orange -> red urgency staging (spec: per the user's explicit ask).
# A brand-new intention starts yellow with a real deadline in the future; if
# it's STILL around, unresolved, once that deadline passes, it's re-armed with
# a fresh deadline, a higher priority, and moves up a color stage. Deliberately
# generic (not per-template) -- more urgent categories simply get a shorter
# fuse, so they escalate sooner. Expectation-sourced intentions already carry
# their own real window_end_tick and their own missed/frustration escalation
# (systems/expectations.py) -- this reuses that window as the deadline instead
# of inventing a second, competing one, but leaves stage/color to expectations'
# own status coloring (Mind tab keeps that branch separate, see main.js).
INTENTION_DEADLINE_TICKS_BY_CATEGORY = {
    "survival": 900,     # 15 sim-minutes
    "health":   1800,    # 30 min
    "schedule": 3600,    # 1h
    "social":   3600,
    "chores":   5400,    # 1.5h
    "identity": 7200,    # 2h
    "leisure":  7200,
}
INTENTION_DEFAULT_DEADLINE_TICKS = 3600
INTENTION_STAGE_COLORS = ("yellow", "orange", "red")   # index 0 = brand new
INTENTION_MAX_STAGE = len(INTENTION_STAGE_COLORS) - 1
INTENTION_PRIORITY_ESCALATION = 15   # per missed deadline, capped at 100

_intention_seq = 0


def _next_intention_seq():
    global _intention_seq
    _intention_seq += 1
    return _intention_seq


def _deadline_window(intention):
    return INTENTION_DEADLINE_TICKS_BY_CATEGORY.get(
        intention.get("category"), INTENTION_DEFAULT_DEADLINE_TICKS)


CATEGORY_PRIORITY = {
    "survival": 100,
    "health":   90,
    "schedule": 75,
    "social":   60,
    "identity": 40,
    "chores":   35,
    "leisure":  20,
    "impulse":  10,
}

# How far out (real ticks) urgency starts ramping before a real
# window_end_tick -- e.g. an intention whose window closes in 2 hours
# starts climbing now; one still 5 hours out is unaffected.
URGENCY_WINDOW_TICKS = 2 * 3600

# Per the user's explicit ask: fatigue should shape which intention gets
# picked in general, not just gate a hard "must sleep now" cutoff --
# a tired character can still do things, but naturally gravitates toward
# the easier ones first ("low hanging fruit"). How physically/mentally
# demanding a handful of well-known intention types are (0=trivial,
# 1=strenuous); anything not listed here (the many intention types this
# deliberately doesn't enumerate one-by-one, including every
# "expectation:<id>" instance) falls back to DEFAULT_INTENTION_EFFORT, a
# reasonable moderate middle ground. Body-survival types (sleep, toilet,
# eat, drink) are kept near-zero on purpose -- those aren't really
# optional regardless of how tired someone is, so fatigue shouldn't
# discount them at all.
INTENTION_EFFORT = {
    "exercise": 0.9, "work": 0.8, "chore": 0.6,
    "clean_floors": 0.6, "dust_and_wipe": 0.5, "outdoor_time": 0.4,
    "sleep": 0.0, "take_nap": 0.0, "use_toilet": 0.05,
    "eat_food": 0.1, "drink": 0.05, "wait": 0.0,
    "seek_solitude": 0.1, "seek_caffeine_or_rest": 0.0,
    "socialize": 0.3, "seek_romance": 0.4, "seek_intimacy": 0.5,
    "creative_outlet": 0.25, "learn_something": 0.2,
    "spiritual_practice": 0.15, "play": 0.3, "pursue_purpose": 0.3,
}
DEFAULT_INTENTION_EFFORT = 0.35

# At fatigue=100, a max-effort (1.0) intention's priority is cut by up to
# this fraction -- a trivial (0.0-effort) one is completely untouched at
# any fatigue level. This only ever discounts a demanding option relative
# to an easy one WITHIN the same category tier (category_score*1000
# still dominates below, so fatigue can never make a leisure activity
# outrank a real survival need) -- the actual mechanism behind "pick low
# hanging fruit first."
FATIGUE_EFFORT_PENALTY_MAX = 0.5


def _fatigue_effort_multiplier(i, c):
    if c is None:
        return 1.0
    effort = INTENTION_EFFORT.get(i.get("type", ""), DEFAULT_INTENTION_EFFORT)
    if effort <= 0:
        return 1.0
    fatigue = c.get("body", {}).get("fatigue", 0) / 100.0
    return 1.0 - fatigue * effort * FATIGUE_EFFORT_PENALTY_MAX


def final_priority(i, c=None):
    category_score = CATEGORY_PRIORITY.get(i.get("category", "impulse"), 0)
    base = i.get("priority", 0)

    # Real deadline-driven urgency (systems/expectations.py's schedule-
    # derived window_end_tick) -- compounds with the intention's own
    # base priority rather than a flat additive bump, per the explicit
    # ask: "least time left and highest priority should compel us all
    # the more." A low-priority intention barely spikes even with zero
    # time left; a high-priority one running out of time genuinely
    # dominates. Reuses the same module-level _CURRENT_TICK
    # add_intention() already relies on, rather than threading a world
    # param through every one of final_priority()'s own callers.
    window_end = i.get("window_end_tick")
    if window_end is not None:
        remaining = max(0, window_end - _CURRENT_TICK)
        if remaining < URGENCY_WINDOW_TICKS:
            urgency_factor = 1.0 + (1.0 - remaining / URGENCY_WINDOW_TICKS) * (base / 100.0)
            base = min(100, base * urgency_factor)

    # c is optional (every caller below now passes it; a couple of older,
    # narrower call sites that only ever sort within one already-fixed
    # category can safely omit it and get the fatigue-blind score, same
    # as before this round).
    base *= _fatigue_effort_multiplier(i, c)

    return category_score * 1000 + base
# =========================================================
# ENSURE ACTIVE INTENTIONS
# =========================================================

def ensure_intentions(c):

    c.setdefault(
        "active_intentions",
        []
    )
# =========================================================
# HAS INTENTION
# =========================================================

def has_intention(

    c,

    name
):

    for i in c.get(
        "intentions",
        []
    ):

        if i["type"] == name:
            return True

    return False

# =========================================================
# REMOVE INTENTION
# =========================================================

def remove_intention(c, intention_type):
    """Drop a still-lingering entry of this type. Needed anywhere an
    intention is only ever ADDED while some condition holds (frustration
    above a threshold, an expectation still outstanding, ...): once that
    condition clears, nothing else revisits the old entry, so without an
    explicit removal it sits in active_intentions -- at its last, now
    stale, priority/reason -- forever, and keeps getting offered."""
    ints = c.get("active_intentions")
    if ints:
        c["active_intentions"] = [i for i in ints if i.get("type") != intention_type]


# =========================================================
# ADD INTENTION
# =========================================================

def add_intention(

    c,

    intention
):

    ensure_intentions(c)

    intentions = c[
        "active_intentions"
    ]

    # Confirmed live bug (player-visible: a whole batch of lt_need
    # intentions all showing the same "Created At" on every UI refresh):
    # add_intention() unconditionally re-stamps created_at to "now" every
    # time it's called, even when an intention of this type already
    # exists and is just being refreshed (e.g. generate_lt_need_
    # intentions() re-adding the same still-frustrated need every
    # lt_needs cadence tick). That made an intention that's actually been
    # sitting there for hours look freshly created on every single
    # refresh. Preserve the ORIGINAL creation tick when one already
    # exists, unless the caller explicitly passes its own created_at.
    existing = next(
        (i for i in intentions if i["type"] == intention["type"]),
        None
    )

    if "created_at" not in intention:
        if existing and "created_at" in existing:
            intention["created_at"] = existing["created_at"]

    intention.setdefault(
        "created_at",
        _CURRENT_TICK
    )

    # Yellow/orange/red deadline staging -- expectation-sourced intentions
    # already carry their own real window_end_tick and their own
    # missed/frustration-driven escalation (systems/expectations.py), so this
    # only manages the generic ones (see INTENTION_DEADLINE_TICKS_BY_CATEGORY
    # above). A brand-new intention (no existing entry of this type) starts at
    # stage 0 (yellow) with a fresh deadline; a refresh carries its stage/
    # deadline/seq forward unchanged -- check_intention_deadlines() below is
    # what actually escalates one whose deadline has passed.
    if not str(intention.get("type", "")).startswith("expectation:"):
        if existing is not None:
            for field in ("_seq", "stage", "deadline_tick"):
                if field in existing and field not in intention:
                    intention[field] = existing[field]
        if "_seq" not in intention:
            intention["_seq"] = _next_intention_seq()
        intention.setdefault("stage", 0)
        intention.setdefault("deadline_tick", _CURRENT_TICK + _deadline_window(intention))

    intention.setdefault(
        "source",
        "unknown"
    )

    intention.setdefault(
        "category",
        "impulse"
    )

    intention.setdefault(
        "priority",
        0
    )

    # Per the user's explicit ask: every intention gets a unique priority the
    # first time it's created, so the whole list is strictly ordered from the
    # start rather than several tying and falling back to insertion order.
    # Only on real creation (a refresh keeps whatever priority its own
    # recompute already gave it -- e.g. lt_need frustration rising) and only
    # nudged up by whole points, so it never crosses into a different
    # category's priority band.
    if existing is None:
        used = {i.get("priority") for i in intentions if i is not intention}
        while intention["priority"] in used:
            intention["priority"] += 1

    intention.setdefault(
        "interrupts",
        False
    )

    # ------------------------------------
    # REPLACE SAME TYPE
    # ------------------------------------

    intentions = [

        i for i in intentions

        if i["type"] != intention["type"]
    ]

    intentions.append(
        intention
    )

    c["active_intentions"] = (
        intentions
    )


# =========================================================
# CHECK INTENTION DEADLINES
# =========================================================

def check_intention_deadlines(c, world):
    """Escalate any generic (non-expectation) intention whose deadline has
    passed while it's still sitting there unresolved: priority up, color
    stage up (yellow -> orange -> red), deadline re-armed. Called every tick
    from update_agent(), same cadence as update_desires()/update_expectations().
    """
    tick = world.get("tick", 0)
    for i in c.get("active_intentions", []):
        if str(i.get("type", "")).startswith("expectation:"):
            continue
        deadline = i.get("deadline_tick")
        if deadline is None or tick < deadline:
            continue
        i["stage"] = min(INTENTION_MAX_STAGE, i.get("stage", 0) + 1)
        i["priority"] = min(100, i.get("priority", 0) + INTENTION_PRIORITY_ESCALATION)
        i["deadline_tick"] = tick + _deadline_window(i)

# =========================================================
# DECAY
# =========================================================

def decay_intentions(c):

    for i in c.get(
        "activeintentions",
        []
    ):

        typ = i["type"]

        decay = (

            INTENTION_TYPES
            .get(typ, {})
            .get("decay", 0)
        )

        i["strength"] -= decay

    c["active_intentions"] = [

        i for i in c["active_intentions"]

        if i["strength"] > 0
    ]


# =========================================================
# PRIMARY INTENTION
# =========================================================

def select_primary_intention(c):

    intentions = c.get(
        "intentions",
        []
    )

    if not intentions:
        return None

    return max(

        intentions,

        key=lambda i:
            i["strength"]
    )


# =========================================================
# CLEAN INTENTIONS  (remove expired / zero-strength)
# =========================================================

def clean_intentions(c):
    """Remove intentions with strength <= 0 or that have expired."""
    c["active_intentions"] = [
        i for i in c.get("active_intentions", [])
        if i.get("strength", 1) > 0
    ]


# =========================================================
# SORT INTENTIONS  (highest priority first)
# =========================================================

def sort_intentions(c):
    """Sort active intentions by final_priority, descending, in place."""
    c["active_intentions"] = sorted(
        c.get("active_intentions", []),
        key=lambda i: final_priority(i, c),
        reverse=True
    )
    return c["active_intentions"]


# ===================================================