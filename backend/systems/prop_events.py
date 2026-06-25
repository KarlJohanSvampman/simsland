from systems.room_assignment import (
    assign_prop_room
)

from systems.prop_index import (
    index_prop,
    remove_prop_from_index
)


# =========================================================
# PROP PLACED
# =========================================================

def on_prop_created(

    sim_id,

    floorplan,

    definitions,

    prop
):

    assign_prop_room(
        floorplan,
        prop
    )

    index_prop(

        sim_id,

        prop,

        definitions
    )


# =========================================================
# PROP MOVED
# =========================================================

def on_prop_moved(

    sim_id,

    floorplan,

    definitions,

    prop
):

    assign_prop_room(
        floorplan,
        prop
    )

    index_prop(

        sim_id,

        prop,

        definitions
    )


# =========================================================
# PROP DELETED
# =========================================================

def on_prop_deleted(

    sim_id,

    prop_id
):

    remove_prop_from_index(

        sim_id,

        prop_id
    )