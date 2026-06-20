import random


# =========================================================
# ENSURE DESIRES
# =========================================================

def ensure_desires(c):

    c.setdefault(
        "persistent_desires",
        []
    )


# =========================================================
# ADD DESIRE
# =========================================================

def add_desire(

    c,

    desire_type,

    target=None,

    importance=0.5
):

    ensure_desires(c)

    # =====================================================
    # DUPLICATE CHECK
    # =====================================================

    for d in c[
        "persistent_desires"
    ]:

        if (

            d["type"]
            ==
            desire_type

            and

            d.get("target")
            ==
            target
        ):

            d["importance"] = max(

                d["importance"],

                importance
            )

            return d

    desire = {

        "type":
            desire_type,

        "target":
            target,

        "importance":
            importance,

        "frustration":
            0.0,

        "progress":
            0.0,

        "resolved":
            False,

        "active":
            True
    }

    c[
        "persistent_desires"
    ].append(desire)

    return desire


# =========================================================
# UPDATE DESIRES
# =========================================================

def update_desires(

    c,

    world
):

    ensure_desires(c)

    for desire in c[
        "persistent_desires"
    ]:

        if desire.get(
            "resolved"
        ):
            continue

        update_desire(

            c,

            desire,

            world
        )


# =========================================================
# UPDATE SINGLE
# =========================================================

def update_desire(

    c,

    desire,

    world
):

    # =====================================================
    # FRUSTRATION
    # =====================================================

    desire[
        "frustration"
    ] += random.uniform(

        0.00001,

        0.00008
    )

    desire[
        "frustration"
    ] = min(

        1.0,

        desire[
            "frustration"
        ]
    )

    # =====================================================
    # IMPORTANCE DRIFT
    # =====================================================

    if desire[
        "frustration"
    ] > 0.5:

        desire[
            "importance"
        ] += 0.00002

    desire[
        "importance"
    ] = min(

        1.0,

        desire[
            "importance"
        ]
    )


# =========================================================
# RESOLVE DESIRE
# =========================================================

def resolve_desire(

    c,

    desire_type,

    target=None
):

    for d in c.get(
        "persistent_desires",
        []
    ):

        if d["type"] != desire_type:
            continue

        if d.get(
            "target"
        ) != target:

            continue

        d["resolved"] = True
        d["active"] = False

        return d

    return None


# =========================================================
# ACTIVE DESIRES
# =========================================================

def active_desires(c):

    return [

        d

        for d in c.get(
            "persistent_desires",
            []
        )

        if not d.get(
            "resolved"
        )
    ]