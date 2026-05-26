from systems.props import (
    find_nearest_anchor
)


from systems.occupancy import (
    reserve_anchor
)


# =========================================================
# BEGIN INTERACTION
# =========================================================

def begin_interaction(

    c,

    world,

    interaction_name
):

    result = find_nearest_anchor(

        c,

        world,

        interaction_name
    )

    if not result:
        return None

    prop, anchor = result

    ok = reserve_anchor(

        c,

        world,

        prop,

        anchor
    )

    if not ok:
        return None

    request_route_to_anchor(

        c,

        world,

        prop,

        anchor
    )

    return {

        "prop": prop,

        "anchor": anchor
    }