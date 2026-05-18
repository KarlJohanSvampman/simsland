NEED_ACTIVITY_MAP = {

    "energy": "sleep",

    "hunger": "cook_meal",

    "comfort": "relax"
}

# =========================================================
# PICK PRIMARY NEED
# =========================================================

def choose_need(character):

    needs = character.get(
        "needs",
        {}
    )

    if not needs:
        return None

    return min(

        needs,

        key=lambda k:
            needs[k]
    )


def choose_activity(character):

    need = choose_need(character)

    if not need:
        return None

    return NEED_ACTIVITY_MAP.get(
        need
    )

from systems.affordances import (
    find_props_with_affordance
)


# =========================================================
# FIND ACTIVITY TARGET
# =========================================================

def find_activity_target(

    world,

    activity_template
):

    required = (

        activity_template
        .get(
            "required_affordances",
            []
        )
    )

    if not required:
        return None

    affordance = required[0]

    candidates = (

        find_props_with_affordance(

            world,

            affordance
        )
    )

    if not candidates:
        return None

    return candidates[0]