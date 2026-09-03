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

    prop,

    world=None,
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

    # Feeds the refurnishing drive (systems/refurnishing.py) -- a prop
    # placed through the World Editor counts as a real furniture change,
    # same as a sim doing it in-sim via the redecorate_room chore. world
    # is optional (callers outside api/props.py may not have it handy)
    # since this is purely a "nice to track," not load-bearing.
    if world is not None:
        from systems.chores import zone_key_for_prop
        from systems.refurnishing import record_furniture_change
        record_furniture_change(world, zone_key_for_prop(prop))


# =========================================================
# PROP MOVED
# =========================================================

def on_prop_moved(

    sim_id,

    floorplan,

    definitions,

    prop,

    world=None,
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

    if world is not None:
        from systems.chores import zone_key_for_prop
        from systems.refurnishing import record_furniture_change
        record_furniture_change(world, zone_key_for_prop(prop))


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
