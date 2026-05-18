from systems.templates import (
    resolve_prop
)


# =========================================================
# GET PROP AFFORDANCES
# =========================================================

def get_prop_affordances(

    world,

    prop
):

    resolved = resolve_prop(
        world,
        prop
    )

    return resolved.get(
        "affordances",
        []
    )


# =========================================================
# FIND PROPS WITH AFFORDANCE
# =========================================================

def find_props_with_affordance(

    world,

    affordance
):

    results = []

    for prop in world.get(
        "props",
        []
    ):

        affs = get_prop_affordances(
            world,
            prop
        )

        if affordance in affs:

            if not is_reserved(prop):

                results.append(prop)

    return results