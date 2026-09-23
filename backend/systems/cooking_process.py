from data.recipes import RECIPES as _PY_RECIPES

def _get_recipes(world=None):
    """Prefer definitions.json, fall back to Python dict."""
    return (world or {}).get("definitions", {}).get("recipe_templates") or _PY_RECIPES

from systems.household_storage import (
    find_household_resource,
    remove_household_resource,
    add_household_resource
)

from systems.resource_runtime import (
    create_resource
)


# =========================================================
# CHOOSE RECIPE
# =========================================================
# activities.py's "cook_recipe" completion branch called an undefined
# choose_recipe(c, household) -- this would NameError the moment a
# character's activity actually resolved to cook_recipe. Filters to
# recipes the household can actually make right now (every stage's
# required resource_type present in storage), then picks via
# systems/choice.py's generic utility.

def _recipe_is_feasible(household, recipe):
    from systems.household_storage import find_household_resource
    required = set()
    for stage in recipe.get("stages", []):
        required.update(stage.get("inputs", {}).keys())
    return all(find_household_resource(household, resource_type=rt) for rt in required)


def choose_recipe(c, world, household, occasion=None):
    recipes = _get_recipes(world)
    feasible = [
        {"id": rid, "label": r.get("name", rid), "tags": r.get("tags", [])}
        for rid, r in recipes.items()
        if _recipe_is_feasible(household, r)
    ]
    if not feasible:
        return None

    from systems.choice import choose
    picked = choose(c, world, "meal", feasible, occasion=occasion)
    if not picked:
        return None

    from systems.validation import queue_choice_for_validation
    queue_choice_for_validation(c, world, "meal", picked["label"], occasion=occasion)
    return picked["id"]


# =========================================================
# START COOKING PROCESS
# =========================================================

def start_cooking_process(

    c,

    household,

    recipe_id,

    world
):

    recipe = _get_recipes(world).get(
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

    recipe = _get_recipes(world)[
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

    is_active = stage.get(
        "active",
        True
    )

    process[
        "waiting"
    ] = not is_active

    # =====================================================
    # SURFACE REQUIREMENT
    # =====================================================
    # Confirmed live gap: recipe stages had zero awareness of what was
    # physically nearby -- a "chop"/"mix" step resolved identically
    # whether or not the character had any counter space. Checked once
    # per stage (not every tick -- see update_cooking_process(), which
    # used to be the natural-looking call site but would have over-
    # counted a single missing stage many times over its own duration).
    # A miss is a soft penalty (tracked here, applied to dish quality in
    # finish_recipe()), not a hard block or a forced walk-to-counter --
    # a character with no counter space still finishes the recipe, it
    # just doesn't turn out as well.
    primitives = (world.get("definitions") or {}).get("stage_primitives") or {}
    prim = primitives.get(stage.get("primitive"), {})
    if prim.get("requires_surface"):
        from systems.props import find_preferred_surface, PREFERRED_SURFACE_RADIUS
        # A table/counter tagged "cook_prep" (systems/props.py::
        # find_preferred_surface) wins over the generic "prepare_food"
        # anchor search when one's nearby; falls back to the untouched
        # generic behavior (with its own same-room-scale radius --
        # find_nearest_free_anchor() has no distance cutoff of its own)
        # when nothing's tagged.
        found = find_preferred_surface(c, world, "cook_prep", fallback_interaction="prepare_food")
        has_surface = False
        if found:
            prop, _anchor = found
            distance = abs(prop.get("x", 0) - c.get("x", 0)) + abs(prop.get("y", 0) - c.get("y", 0))
            has_surface = distance <= PREFERRED_SURFACE_RADIUS
        if not has_surface:
            process["missing_surface_count"] = process.get("missing_surface_count", 0) + 1

    # =====================================================
    # STAGE ANIMATION
    # =====================================================
    # Previously this function never touched c["animation_state"] at
    # all — every stage transition (boil_water -> cook_carbs ->
    # prepare_sauce) was invisible, the character just idled through
    # the whole multi-stage process. Only set it for active stages
    # (the character needs to be doing something); an unattended stage
    # (active: false — boiling, roasting) leaves animation_state alone,
    # matching the already-intentional "character is free to walk away"
    # behavior once this activities.py hand-off has happened.
    if is_active:
        primitives = (world.get("definitions") or {}).get("stage_primitives") or {}
        prim = primitives.get(stage.get("primitive"), {})
        anim = prim.get("animation_state")
        if anim:
            c["animation_state"] = anim

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

    recipe = _get_recipes(world)[
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

    if stage.get("active", True):
        from systems.accidents import maybe_trigger_cooking_accident
        maybe_trigger_cooking_accident(c, world, stage.get("primitive"))

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

    recipe = _get_recipes(world)[
        process[
            "recipe_id"
        ]
    ]

    # Real d100 skill check (systems/skill_checks.py) against the shared
    # abilities.py "cooking" proficiency -- replaces the old standalone
    # c["cooking_skill"] float + calculate_quality() formula entirely.
    # The recipe's own 0-1 "difficulty" field still matters (a harder
    # recipe should be harder to nail) -- folded in as a situational
    # modifier on the shared "cook_recipe" baseDifficulty rather than a
    # second parallel difficulty concept: 0.5 is neutral (the value the
    # old formula centered on), higher makes it harder, lower easier.
    from systems.skill_checks import resolve_skill_check
    from systems.abilities import record_attempt

    recipe_difficulty = recipe.get("difficulty", 0.5)
    # Missing counter space during a chop/mix stage (begin_stage()'s own
    # surface-requirement check) is a real, additive penalty here -- 10
    # difficulty points per miss, same order of magnitude as the recipe-
    # difficulty term just above it.
    surface_penalty = process.get("missing_surface_count", 0) * 10
    extra_modifier = round((0.5 - recipe_difficulty) * 100) - surface_penalty
    result = resolve_skill_check("cook_recipe", c, world, extra_actor_modifier=extra_modifier)

    if result and not result.get("blocked"):
        record_attempt(c, "cooking", world, result["success"], margin=result["actor_margin"])
        # Quality reflects the FULL signed difference (can go negative on
        # a bad miss, not just floored-at-0 like the progression-facing
        # actor_margin) -- a recipe always produces something, per the
        # user's own ask, its quality just ranges from a real disaster to
        # a real triumph depending on how the roll actually went.
        signed_margin = result["difficulty"] - result["roll"]
        quality = max(0.0, min(1.0, signed_margin / 100))
    else:
        quality = 0.5

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

    # Cooking dirties the kitchen -- scaled by how many stages the recipe
    # actually needed (more steps, more pans/counter space used), same
    # zone-scalar chores.py's own dishwashing/floor chores already credit
    # against. A bad cook (low quality) also means more mess left behind.
    from systems.chores import adjust_room_cleanliness, kitchen_zone_key
    zone_key = kitchen_zone_key(world, household)
    if zone_key:
        stage_count = len(recipe.get("stages", [])) or 1
        mess = 3.0 * stage_count * (1.5 - quality)
        adjust_room_cleanliness(world, zone_key, -mess)

    process[
        "completed"
    ] = True

    c["active_process"] = None


# =========================================================
# TASTE
# =========================================================

def calculate_taste(

    quality,

    c
):

    taste = quality

    if "foodie" in c.get(
        "traits", []
    ):
        taste = min(1.0, taste + 0.1)

    return max(0.0, min(1.0, taste))
