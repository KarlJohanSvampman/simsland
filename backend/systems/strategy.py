import random


# =========================================================
# RESOLVE STRATEGY
# =========================================================

def resolve_strategy(

    c,

    world,

    intention
):

    t = intention.get(
        "type"
    )

    # =====================================================
    # HUNGER
    # =====================================================

    if t == "satisfy_hunger":

        return resolve_hunger_strategy(

            c,

            world
        )

    # =====================================================
    # SOCIAL
    # =====================================================

    if t == "contact_person":

        return resolve_social_strategy(

            c,

            world,

            intention
        )

    # =====================================================
    # HYGIENE
    # =====================================================

    if t == "restore_hygiene":

        return resolve_hygiene_strategy(
            c
        )

    # =====================================================
    # FATIGUE
    # =====================================================

    if t == "restore_energy":

        return resolve_energy_strategy(
            c
        )

    return None


# =========================================================
# HUNGER
# =========================================================

def resolve_hunger_strategy(

    c,

    world
):

    money = c.get(
        "money",
        0
    )

    energy = c.get(
        "needs",
        {}
    ).get(
        "energy",
        1
    )

    stress = c.get(
        "stress",
        0
    )

    traits = c.get(
        "traits",
        []
    )

    inventory = c.get(
        "inventory",
        []
    )

    has_food = any(

        item.get("category")
        ==
        "food"

        for item in inventory
    )

    # =====================================================
    # LOW ENERGY
    # =====================================================

    if energy < 0.2:

        if has_food:
            return "eat_snack"

        return "order_takeout"

    # =====================================================
    # LAZY
    # =====================================================

    if "lazy" in traits:

        if money > 40:

            return random.choice([

                "order_takeout",

                "eat_snack"
            ])

    # =====================================================
    # STRESSED
    # =====================================================

    if stress > 70:

        if money > 25:

            return "order_takeout"

    # =====================================================
    # NORMAL
    # =====================================================

    if has_food:

        if random.random() < 0.5:
            return "cook_meal"

        return "eat_meal"

    if money > 20:

        return "buy_food"

    return "eat_snack"


# =========================================================
# SOCIAL
# =========================================================

def resolve_social_strategy(

    c,

    world,

    intention
):

    target_id = intention.get(
        "target_id"
    )

    target = world[
        "characters"
    ].get(
        target_id
    )

    if not target:
        return None

    energy = c.get(
        "needs",
        {}
    ).get(
        "energy",
        1
    )

    insecurity = c.get(
        "insecurity",
        0
    )

    # =====================================================
    # TIRED
    # =====================================================

    if energy < 0.25:

        return "text_person"

    # =====================================================
    # INSECURE
    # =====================================================

    if insecurity > 70:

        return random.choice([

            "text_person",

            "browse_phone"
        ])

    # =====================================================
    # SAME BUILDING
    # =====================================================

    if (

        c.get("building_id")
        ==
        target.get("building_id")
    ):

        return random.choice([

            "conversation",

            "hangout"
        ])

    # =====================================================
    # DISTANT
    # =====================================================

    return random.choice([

        "call_person",

        "visit_person"
    ])


# =========================================================
# HYGIENE
# =========================================================

def resolve_hygiene_strategy(c):

    hygiene = c.get(
        "needs",
        {}
    ).get(
        "hygiene",
        1
    )

    if hygiene < 0.2:

        return "take_shower"

    return random.choice([

        "wash_hands",

        "brush_teeth"
    ])


# =========================================================
# ENERGY
# =========================================================

def resolve_energy_strategy(c):

    energy = c.get(
        "needs",
        {}
    ).get(
        "energy",
        1
    )

    if energy < 0.15:

        return "sleep"

    return "nap"