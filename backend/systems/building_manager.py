from core.definitions import (
    load_definitions
)

from systems.buildings import (
    instantiate_floorplan
)

from systems.templates import (

    get_floorplan_template,

    resolve_floorplan
)

from systems.navigation import (

    cache_floorplan
)


# =========================================================
# BUILD WORLD GEOMETRY
# =========================================================

def build_world_geometry(

    sim_id,

    world
):

    # =====================================
    # DEFINITIONS
    # =====================================

    definitions = load_definitions(
        sim_id
    )

    # inject into world
    world["definitions"] = definitions

    # =====================================
    # RUNTIME COLLECTIONS
    # =====================================

    world_tiles = []

    world_rooms = []

    world_doors = []

    world_windows = []

    world_buildings = []

    # =====================================
    # BUILDINGS
    # =====================================

    for building in world.get(
        "buildings",
        []
    ):

        # =====================================
        # RESOLVE BUILDING TEMPLATE
        # =====================================

        floorplan = get_floorplan_template(

            world,

            building
        )

        if not floorplan:

            print(
                "Missing floorplan template:",
                building.get("template")
            )

            continue

        # =====================================
        # RESOLVED BUILDING
        # =====================================

        resolved_building = resolve_floorplan(

            world,

            building
        )

        # =====================================
        # INSTANTIATE FLOORPLAN
        # =====================================

        runtime = instantiate_floorplan(

            resolved_building,

            floorplan
        )

        # navigation.py's NAV_CACHE is keyed by whatever id gets passed to
        # cache_floorplan() -- core/definitions.py and api/editor.py both
        # only ever cache it under the floorplan TEMPLATE id (e.g.
        # "small_house"), but systems/room_assignment.py::assign_prop_room()
        # looks it up via get_room_at_position() using the BUILDING
        # INSTANCE id (e.g. "house_1"). Those never matched, so every
        # prop/character in every real building got room_id=None
        # regardless of whether the floorplan actually had rooms defined.
        # Caching it again here, once per real building instance, fixes
        # room resolution without touching the template-id cache the
        # editor/definitions-preview paths still rely on.
        cache_floorplan(
            building["id"],
            floorplan
        )

        # =====================================
        # BUILDING METADATA
        # =====================================

        runtime["building"] = {

            "id": building["id"],

            "template": building.get(
                "template"
            ),

            "x": building["x"],

            "y": building["y"],

            "rotation": building.get(
                "rotation",
                0
            ),

            "zone": building.get(
                "zone"
            ),

            "address": building.get(
                "address"
            ),

            "owner_household_id":
                building.get(
                    "owner_household_id"
                )
        }

        world_buildings.append(
            runtime["building"]
        )

        # =====================================
        # RUNTIME GEOMETRY
        # =====================================

        world_tiles.extend(
            runtime.get(
                "tiles",
                []
            )
        )

        world_rooms.extend(
            runtime.get(
                "rooms",
                []
            )
        )

        world_doors.extend(
            runtime.get(
                "doors",
                []
            )
        )

        world_windows.extend(
            runtime.get(
                "windows",
                []
            )
        )

    # =====================================
    # STORE RUNTIME DATA
    # =====================================

    world["runtime_tiles"] = (
        world_tiles
    )

    world["runtime_rooms"] = (
        world_rooms
    )

    world["runtime_doors"] = (
        world_doors
    )

    world["runtime_windows"] = (
        world_windows
    )

    world["runtime_buildings"] = (
        world_buildings
    )