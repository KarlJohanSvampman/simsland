import random

from data.recipes import (
    RECIPES
)

from systems.household_storage import (
    find_household_resource,
    remove_household_resource,
    add_household_resource
)

from systems.resource_runtime import (
    create_resource
)


# =========================================================
# START COOKING PROCESS
# =========================================================

def start_cooking_process(

    c,

    household,

    recipe_id,

    world
):

    recipe = RECIPES.get(
        recipe_id
    )

    if not recipe:
        return None

    process = {

        "type": "cooking",

        "recipe_id": recipe_id,

        "started_tick": world["tick"],

        "current_stage": 0,

        "stage_started_tick":
            world["tick"],

        "completed": False,

        "reserved_resources": []
    }

    c["active_process"] = process

    begin_stage(

        c,

        household,

        process,

        world
    )

    return process


# =========================================================
# BEGIN STAGE
# =========================================================

def begin_stage(

    c,

    household,

    process,

    world
):

    recipe = RECIPES[
        process[
            "recipe_id"
        ]
    ]

    idx = process[
        "current_stage"
    ]

    if idx >= len(
        recipe["stages"]
    ):

        finish_recipe(

            c,

            household,

            process,

            world
        )

        return

    stage = recipe[
        "stages"
    ][idx]

    process[
        "stage_started_tick"
    ] = world["tick"]

    process[
        "stage_name"
    ] = stage["name"]

    process[
        "waiting"
    ] = not stage.get(
        "active",
        True
    )

    # =====================================================
    # CONSUME INPUTS
    # =====================================================

    for resource_type, amount in stage.get(

        "inputs",

        {}
    ).items():

        resource = find_household_resource(

            household,

            resource_type=
                resource_type
        )

        if not resource:
            process["failed"] = True
            return

        remove_household_resource(

            household,

            resource,

            amount
        )


# =========================================================
# UPDATE PROCESS
# =========================================================

def update_cooking_process(

    c,

    household,

    world
):

    process = c.get(
        "active_process"
    )

    if not process:
        return False

    if process.get(
        "type"
    ) != "cooking":

        return False

    if process.get(
        "completed"
    ):

        return False

    recipe = RECIPES[
        process[
            "recipe_id"
        ]
    ]

    stage = recipe[
        "stages"
    ][
        process[
            "current_stage"
        ]
    ]

    elapsed = (

        world["tick"]

        -

        process[
            "stage_started_tick"
        ]
    )

    duration = (
        stage["duration"] * 60
    )

    # =====================================================
    # STAGE COMPLETE
    # =====================================================

    if elapsed >= duration:

        process[
            "current_stage"
        ] += 1

        begin_stage(

            c,

            household,

            process,

            world
        )

        return True

    return True


# =========================================================
# FINISH RECIPE
# =========================================================

def finish_recipe(

    c,

    household,

    process,

    world
):

    recipe = RECIPES[
        process[
            "recipe_id"
        ]
    ]

    cooking_skill = c.get(
        "cooking_skill",
        0.3
    )

    difficulty = recipe.get(
        "difficulty",
        0.5
    )

    quality = calculate_quality(

        cooking_skill,

        difficulty
    )

    nutrition = recipe.get(
        "nutrition",
        0.5
    )

    servings = recipe[
        "output"
    ].get(
        "servings",
        1
    )

    meal = create_resource(

        "MEAL",

        quantity=1,

        servings=servings,

        nutrition=nutrition,

        quality=quality,

        taste=calculate_taste(

            quality,

            c
        ),

        recipe=process[
            "recipe_id"
        ],

        cooked_by=c["id"],

        created_tick=world[
            "tick"
        ],

        container="fridge"
    )

    add_household_resource(

        household,

        meal
    )

    process[
        "completed"
    ] = True

    c["active_process"] = None

    # =====================================================
    # EXPERIENCE
    # =====================================================

    c["cooking_skill"] = min(

        1.0,

        cooking_skill + 0.01
    )


# =========================================================
# QUALITY
# =========================================================

def calculate_quality(

    skill,

    difficulty
):

    delta = skill - difficulty

    quality = 0.5 + delta

    quality += random.uniform(
        -0.1,
        0.1
    )

    return max(
        0,
        min(1.0, quality)
    )


# =========================================================
# TASTE
# =========================================================

def calculate_taste(

    quality,

    c
):

    taste = quality

    if "foodie" in c.get(
        "traits",
        []
    ):

        taste += 0.1

    if "lazy" in c.get(
        "traits",
        []
    ):

        taste -= 0.05

    return max(
        0,
        min(1.0, taste)
    )