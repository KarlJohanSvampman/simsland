import random

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
    "leisure":  20,
    "impulse":  10,
}

def final_priority(i):
    category_score = CATEGORY_PRIORITY.get(i.get("category", "impulse"), 0)
    return category_score * 1000 + i.get("priority", 0)
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

    intention.setdefault(
        "created_at",
        0
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