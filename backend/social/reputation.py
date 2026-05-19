# =========================================================
# ENSURE REPUTATION
# =========================================================

def ensure_reputation(world):

    world.setdefault(
        "reputation",
        {}
    )


# =========================================================
# GET REPUTATION
# =========================================================

def get_reputation(

    world,

    target_id
):

    ensure_reputation(world)

    return world[
        "reputation"
    ].setdefault(

        target_id,

        {
            "trust": 0.5,

            "respect": 0.5,

            "fear": 0.0,

            "controversy": 0.0
        }
    )

# =========================================================
# APPLY SOCIAL EVENT
# =========================================================

def apply_social_event(

    world,

    target_id,

    event_type,

    intensity=0.1
):

    rep = get_reputation(

        world,

        target_id
    )

    # =====================================
    # POSITIVE
    # =====================================

    if event_type in [

        "helped",

        "comforted",

        "heroic"
    ]:

        rep["trust"] += intensity

        rep["respect"] += (
            intensity * 0.7
        )

    # =====================================
    # NEGATIVE
    # =====================================

    elif event_type in [

        "lied",

        "betrayed",

        "insulted"
    ]:

        rep["trust"] -= intensity

        rep["controversy"] += (
            intensity * 0.5
        )

    # =====================================
    # AGGRESSIVE
    # =====================================

    elif event_type in [

        "threatened",

        "violent"
    ]:

        rep["fear"] += intensity

        rep["respect"] += (
            intensity * 0.3
        )

    # clamp
    for k in rep:

        rep[k] = max(
            0,
            min(1, rep[k])
        )