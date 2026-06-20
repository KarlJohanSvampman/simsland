from brain.intentions import (
    add_intention
)



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

        add_intention(c,{

            "type":
                "use_toilet",

            "category":
                "survival",

            "priority":
                95,

            "interrupts":
                True
        })


    if b.get(
        "bowels",
        0
        ) > 80:

        add_intention(c,{

            "type":
                "use_toilet_bowels",

            "category":
                "survival",

            "priority":
                95,

            "interrupts":
                True
        })


    # =====================================
    # SHOWER
    # =====================================

    if b.get(
        "hygiene",
        100
    ) < 35:
        add_intention(c, {

        "type":
            "take_shower",

        "category":
            "health",

        "priority":
            60
    })

    # =====================================
    # SLEEP
    # =====================================

    if b.get(
        "fatigue",
        0
    ) > 85:

        add_intention(c, {

            "type":
                "sleep",

            "category":
                "survival",

            "priority":
                98,

            "interrupts":
                True
        })

    # =====================================
    # DRINK
    # =====================================

    hydration = b.get(
        "hydration",
        100
    )

    if hydration < 35:

        add_intention(c, {

            "type":
                "drink",

            "category":
                "survival",

            "priority":
                85
        })
    # =====================================
    # FOOD
    # =====================================

    if b.get(
        "hunger",
        0
    ) > 75:

        add_intention(c, {

            "type":
                "eat_food",

            "category":
                "survival",

            "priority":
                80
        })

    return intentions