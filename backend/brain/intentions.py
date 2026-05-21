import random

from brain.intention_types import (
    INTENTION_TYPES
)

from brain.intention_priority import (
    final_priority
)
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
# CLEAN INTENTIONS
# =========================================================

def clean_intentions(c):

    intentions = c.get(
        "active_intentions",
        []
    )

    seen = set()

    cleaned = []

    for i in reversed(intentions):

        key = i.get("type")

        if key in seen:
            continue

        seen.add(key)

        cleaned.append(i)

    cleaned.reverse()

    c["active_intentions"] = (
        cleaned[-10:]
    )


# =========================================================
# SORT INTENTIONS
# =========================================================

def sort_intentions(c):

    intentions = c.get(
        "active_intentions",
        []
    )

    intentions.sort(

        key=final_priority,

        reverse=True
    )

    