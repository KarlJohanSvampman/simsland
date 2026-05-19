from systems.outdoor_navigation import find_outdoor_path
from systems.building_entrances import (
    get_building_by_id,
    get_primary_entrance
)
from systems.navigation import build_multi_room_path


def same_building_route(
    world,
    character,
    target
):
    building = get_building_by_id(
        world,
        character.get("building_id")
    )

    if not building:
        return []

    floorplan = (
        world["definitions"]
        ["floorplan_templates"]
        .get(building["template"])
    )

    if not floorplan:
        return []

    path = build_multi_room_path(
        building,
        floorplan,
        (character["x"], character["y"]),
        (target["x"], target["y"])
    )

    return [
        {
            "type": "indoor",
            "building_id": building["id"],
            "tiles": path
        }
    ]


def building_to_building_route(
    world,
    character,
    target
):
    start_building = get_building_by_id(
        world,
        character.get("building_id")
    )

    target_building = get_building_by_id(
        world,
        target.get("building_id")
    )

    if not start_building or not target_building:
        return []

    start_exit = get_primary_entrance(start_building)
    target_entry = get_primary_entrance(target_building)

    if not start_exit or not target_entry:
        return []

    start_floorplan = (
        world["definitions"]
        ["floorplan_templates"]
        .get(start_building["template"])
    )

    target_floorplan = (
        world["definitions"]
        ["floorplan_templates"]
        .get(target_building["template"])
    )

    indoor_exit = build_multi_room_path(
        start_building,
        start_floorplan,
        (character["x"], character["y"]),
        tuple(start_exit["inside_tile"])
    )

    outdoor = find_outdoor_path(
        world,
        tuple(start_exit["outside_tile"]),
        tuple(target_entry["outside_tile"])
    )

    indoor_entry = build_multi_room_path(
        target_building,
        target_floorplan,
        tuple(target_entry["inside_tile"]),
        (target["x"], target["y"])
    )

    return [
        {
            "type": "indoor",
            "building_id": start_building["id"],
            "tiles": indoor_exit
        },
        {
            "type": "outdoor",
            "tiles": outdoor
        },
        {
            "type": "indoor",
            "building_id": target_building["id"],
            "tiles": indoor_entry
        }
    ]


def build_character_route(
    world,
    character,
    target
):
    current_building_id = character.get("building_id")
    target_building_id = target.get("building_id")

    if current_building_id and current_building_id == target_building_id:
        return same_building_route(
            world,
            character,
            target
        )

    if current_building_id and target_building_id:
        return building_to_building_route(
            world,
            character,
            target
        )

    return []