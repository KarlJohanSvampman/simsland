# =========================================================
# ENSURE SELF MODEL
# =========================================================

def ensure_self_model(c):

    c.setdefault(
        "self_model",
        {}
    )


# =========================================================
# SET SELF PERCEPTION
# =========================================================

def set_self_perception(

    c,

    key,

    value,

    confidence=0.5
):

    ensure_self_model(c)

    c["self_model"][key] = {

        "value": value,

        "confidence": confidence
    }

# =========================================================
# CONSOLIDATE IDENTITY
# =========================================================

def consolidate_identity(c):

    narratives = c.get(
        "narratives",
        []
    )

    stress = c.get(
        "stress",
        0
    )

    ensure_self_model(c)

    # =====================================
    # STRESS IDENTITY
    # =====================================

    if stress > 75:

        set_self_perception(

            c,

            "emotional_state",

            "overwhelmed",

            0.8
        )

    # =====================================
    # LONELINESS
    # =====================================

    loneliness_hits = 0

    for n in narratives:

        text = n.get(
            "text",
            ""
        ).lower()

        if any(x in text for x in [

            "lonely",

            "isolated",

            "rejected"
        ]):

            loneliness_hits += 1

    if loneliness_hits >= 3:

        set_self_perception(

            c,

            "social_identity",

            "isolated",

            0.7
        )

    # =====================================
    # CYNICISM
    # =====================================

    negative_relationships = 0

    for n in narratives:

        text = n.get(
            "text",
            ""
        ).lower()

        if any(x in text for x in [

            "strained",

            "betrayed",

            "conflict"
        ]):

            negative_relationships += 1

    if negative_relationships >= 4:

        set_self_perception(

            c,

            "worldview",

            "cynical",

            0.75
        )