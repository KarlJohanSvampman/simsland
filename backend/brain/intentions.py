import random

from brain.intention_types import (
    INTENTION_TYPES
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

    name,

    strength=None
):

    if has_intention(c, name):
        return

    data = INTENTION_TYPES.get(
        name,
        {}
    )

    c.setdefault(
        "intentions",
        []
    ).append({

        "type": name,

        "strength":
            strength
            if strength is not None
            else data.get(
                "priority",
                50
            ),

        "progress": 0,

        "active": True
    })


# =========================================================
# DECAY
# =========================================================

def decay_intentions(c):

    for i in c.get(
        "intentions",
        []
    ):

        typ = i["type"]

        decay = (

            INTENTION_TYPES
            .get(typ, {})
            .get("decay", 0)
        )

        i["strength"] -= decay

    c["intentions"] = [

        i for i in c["intentions"]

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