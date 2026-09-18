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


def final_priority(i):
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
    if "created_at" not in intention:
        existing = next(
            (i for i in intentions if i["type"] == intention["type"]),
            None
        )
        if existing and "created_at" in existing:
            intention["created_at"] = existing["created_at"]

    intention.setdefault(
        "created_at",
        _CURRENT_TICK
    )

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
        key=final_priority,
        reverse=True
    )
    return c["active_intentions"]


# ===================================================