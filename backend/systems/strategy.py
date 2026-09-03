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
    # body_intentions.py::generate_body_intentions() actually creates
    # {"type": "eat_food", ...} -- "satisfy_hunger" was never the real
    # intention type anywhere, so this branch (and hunger's whole
    # automatic strategy dispatch) was silently unreachable.

    if t == "eat_food":

        return resolve_hunger_strategy(

            c,

            world
        )

    # =====================================================
    # THIRST
    # =====================================================
    # Mirrors HUNGER above -- body_intentions.py creates {"type": "drink",
    # ...} intentions once hydration drops, but nothing ever dispatched
    # them (there was no branch here at all), so thirst never triggered
    # automatic drinking behavior regardless of how dehydrated a character
    # got.

    if t == "drink":

        return resolve_thirst_strategy(

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

    # =====================================================
    # MESS (systems/chores.py) -- a zone the character's own
    # cleanliness_threshold judged too dirty. Picks dishes if any are
    # actually piled up (household-wide, not zone-scoped), else a
    # random floor/surface chore for the flagged zone.
    # =====================================================

    if t == "clean_zone":

        from systems.chores import chore_activity_for_zone
        return chore_activity_for_zone(world, c, intention.get("zone_key"))

    return None


# =========================================================
# HUNGER
# =========================================================

def resolve_hunger_strategy(

    c,

    world
):

    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    if not household:
        return "eat_snack"

    from systems.household_storage import (
        find_household_resource
    )

    # =====================================================
    # READY MEALS
    # =====================================================

    meal = find_household_resource(

        household,

        resource_type="MEAL"
    )

    if meal:

        return "eat_meal"

    # =====================================================
    # STORED MEALS
    # =====================================================

    leftovers = find_household_resource(

        household,

        resource_type="STORED_MEAL"
    )

    if leftovers:

        return "heat_meal"

    # =====================================================
    # PROCESSED MEALS
    # =====================================================

    processed = find_household_resource(

        household,

        resource_type=
            "PROCESSED_MEAL"
    )

    if processed:

        return "heat_meal"

    # =====================================================
    # QUICK FOOD
    # =====================================================

    fruit = find_household_resource(

        household,

        resource_type=
            "FOOD_FRUIT"
    )

    if fruit:

        return "eat_snack"

    snacks = find_household_resource(

        household,

        resource_type=
            "FOOD_SNACK"
    )

    if snacks:

        return "eat_snack"

    # =====================================================
    # INGREDIENTS
    # =====================================================

    protein = find_household_resource(

        household,

        resource_type=
            "FOOD_PROTEIN"
    )

    carbs = find_household_resource(

        household,

        resource_type=
            "FOOD_CARB"
    )

    vegetables = find_household_resource(

        household,

        resource_type=
            "FOOD_VEGETABLE"
    )

    if protein and carbs and vegetables:

        return "cook_recipe"

    # =====================================================
    # NO FOOD
    # =====================================================

    money = c.get(
        "money",
        0
    )

    if money > 20:

        return random.choice([

            "buy_food",

            "order_takeout"
        ])

    return "eat_snack"


# =========================================================
# THIRST
# =========================================================

def resolve_thirst_strategy(c, world):
    # Tap water is always available at a sink -- unlike food, there's no
    # household stock to check first. See activities.py's "drink_water"
    # entry (interaction "drink", now a real anchor on kitchen_sink/
    # bathroom_sink) and its completion handler for the
    # glass-required-for-proper-hydration behavior.
    return "drink_water"


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

    from systems.body import body_energy
    energy = body_energy(c)

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
    # "conversation" used to be an option here, but the activity it starts
    # (activities.py's generic start_activity()) never sets
    # activity["conversation_id"], so update_conversation_activity() always
    # dead-ended while still blocking the character from think() for the
    # activity's full duration — a frozen character, not a conversation.
    # None falls through cleanly to the character's normal per-tick
    # decision (agent_loop.py: "if not activity_type: continue"), which now
    # threads real speech into conversations via apply_speech() instead.
    # "hangout" is unrelated to that broken path (execute_activity() only
    # special-cases the literal string "conversation") and stays as a
    # genuine, working leisure activity.

    if (

        c.get("building_id")
        ==
        target.get("building_id")
    ):

        return random.choice([

            "hangout",

            None
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
    from systems.body import body_hygiene_norm
    hygiene = body_hygiene_norm(c)

    if hygiene < 0.3:
        return "take_shower"

    return random.choice(["wash_hands", "brush_teeth"])


# =========================================================
# ENERGY
# =========================================================

def resolve_energy_strategy(c):
    from systems.body import body_energy
    energy = body_energy(c)

    if energy < 0.15:
        return "sleep"

    return "nap"