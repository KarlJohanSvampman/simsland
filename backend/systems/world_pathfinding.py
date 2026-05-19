from systems.outdoor_navigation import (
    find_outdoor_path
)

from systems.building_entrances import (
    get_primary_entrance
)


# =========================================================
# BUILD WORLD PATH
# =========================================================

def build_world_path(

    world,

    start_building,

    target_building
):

    start_entrance = (
        get_primary_entrance(
            start_building
        )
    )

    target_entrance = (
        get_primary_entrance(
            target_building
        )
    )

    if not start_entrance:
        return []

    if not target_entrance:
        return []

    return find_outdoor_path(

        world,

        tuple(
            start_entrance[
                "outside_tile"
            ]
        ),

        tuple(
            target_entrance[
                "outside_tile"
            ]
        )
    )