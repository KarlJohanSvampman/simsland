# =========================================================
# BODY INTENTIONS
# =========================================================

def generate_body_intentions(c):

    b = c.get(
        "body",
        {}
    )

    intentions = []

    # =====================================
    # TOILET
    # =====================================

    if b.get(
        "bladder",
        0
    ) > 80:

        intentions.append({

            "type":
                "use_toilet",

            "priority":
                0.95
        })

    # =====================================
    # SHOWER
    # =====================================

    if b.get(
        "hygiene",
        100
    ) < 35:

        intentions.append({

            "type":
                "take_shower",

            "priority":
                0.6
        })

    # =====================================
    # SLEEP
    # =====================================

    if b.get(
        "fatigue",
        0
    ) > 85:

        intentions.append({

            "type":
                "sleep",

            "priority":
                0.98
        })

    # =====================================
    # FOOD
    # =====================================

    if b.get(
        "hunger",
        0
    ) > 75:

        intentions.append({

            "type":
                "eat_food",

            "priority":
                0.8
        })

    return intentions