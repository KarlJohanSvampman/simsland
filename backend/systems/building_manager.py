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

from systems.transforms import (
    local_to_world
)


# =========================================================
# SPAWN BUILDING PROPS FROM FLOORPLAN
# =========================================================
# floorplan_templates[...]["prop_spawns"] (authored via the World Editor's
# floorplan tool -- frontend/src/floorplan.js) is real, per-floorplan
# furniture-placement data (id/template/x/y/rotation, local to the
# floorplan) that nothing in the runtime pipeline ever consumed --
# confirmed via a full-backend grep turning up zero readers before this.
# instantiate_floorplan() above only ever projected tiles/rooms/doors/
# windows, never props. This is the missing consumer: real world["props"]
# entries, in the same shape api/props.py::_create_prop_dict() already
# produces for a manually-placed prop, projected through the same
# local_to_world() every other floorplan element already uses.

def spawn_building_props(world, building, floorplan):
    """Idempotent per building -- stamps building["_props_spawned"] once
    real props exist for it, so calling this again on every
    build_world_geometry() pass (every world load) never duplicates
    furniture. A building created before this fix (or one whose
    floorplan has no prop_spawns at all) is a safe no-op."""
    if building.get("_props_spawned"):
        return

    prop_spawns = floorplan.get("prop_spawns")
    if not prop_spawns:
        return

    import copy
    import uuid

    prop_templates = world.get("definitions", {}).get("prop_templates", {})
    props = world.setdefault("props", [])

    for spawn in prop_spawns:
        template_id = spawn.get("template")
        template = prop_templates.get(template_id)
        if not template:
            continue
        wx, wy = local_to_world(building, spawn.get("x", 0), spawn.get("y", 0))
        props.append({
            "id":           f"prop_{uuid.uuid4().hex[:8]}",
            "template":     template_id,
            "x":            wx,
            "y":            wy,
            "rotation":     spawn.get("rotation", 0),
            "building_id":  building["id"],
            "household_id": building.get("owner_household_id"),
            "anchors":      copy.deepcopy(template.get("anchors", [])),
            "footprint":    template.get("footprint"),
            "category":     template.get("category"),
            "storage":      copy.deepcopy(template.get("storage")),
            "catalog":      template.get("catalog"),
            "extra_tags":   [],
        })

    building["_props_spawned"] = True


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

        # Real furniture from the floorplan's authored prop_spawns --
        # see spawn_building_props()'s own docstring for why this wasn't
        # happening at all before. Idempotent, so this is safe to call
        # unconditionally on every geometry rebuild.
        spawn_building_props(world, building, floorplan)

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