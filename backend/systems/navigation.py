from heapq import heappush, heappop
from collections import deque

NAV_CACHE = {}

from systems.transforms import (
    world_to_local,
    local_to_world
)

from core.spatial import (
    spatial_key,
    parse_spatial_key
)

from systems.templates import resolve_floorplan
from systems.outdoor_navigation import find_outdoor_path


# =========================================================
# ROOM ROUTE KEY
# =========================================================

def room_route_key(a, b):

    return f"{a}->{b}"


# =========================================================
# HEURISTIC
# =========================================================

def heuristic(a, b):

    return (
        abs(a[0] - b[0])
        +
        abs(a[1] - b[1])
    )


# =========================================================
# ASTAR
# =========================================================

def astar(start, goal, blocked):

    open_set = []

    heappush(
        open_set,
        (0, start)
    )

    came_from = {}

    g_score = {
        start: 0
    }

    while open_set:

        _, current = heappop(
            open_set
        )

        if current == goal:

            path = []

            while current in came_from:

                path.append(current)

                current = came_from[current]

            path.reverse()

            return path

        x, y = current

        neighbors = [

            (x + 1, y),
            (x - 1, y),
            (x, y + 1),
            (x, y - 1)
        ]

        for n in neighbors:

            if n in blocked:
                continue

            tentative = (
                g_score[current] + 1
            )

            if tentative < g_score.get(
                n,
                999999
            ):

                came_from[n] = current

                g_score[n] = tentative

                f = (
                    tentative
                    +
                    heuristic(n, goal)
                )

                heappush(
                    open_set,
                    (f, n)
                )

    return []


# =========================================================
# BUILD PORTALS
# =========================================================

def build_portals(

    building_id,

    floorplan
):

    portals = {}

    for door in floorplan.get(
        "doors",
        []
    ):

        portal_id = (
            f"{building_id}:{door['id']}"
        )

        portals[portal_id] = {

            "id": portal_id,

            "building_id":
                building_id,

            "x": door["x"],

            "y": door["y"],

            "connects":
                door.get(
                    "connects",
                    []
                ),

            "locked": False,

            "open": True
        }

    return portals


# =========================================================
# ROOM LOOKUP
# =========================================================

def build_room_lookup(

    building_id,

    floorplan
):

    lookup = {}

    for room in floorplan.get(
        "rooms",
        []
    ):

        for tile in room.get(
            "tiles",
            []
        ):

            tile_x = tile["x"]
            tile_y = tile["y"]

            lookup[
                spatial_key(
                    tile_x,
                    tile_y
                )
            ] = runtime_room_id(

                building_id,

                room["id"]
            )

    return lookup


# =========================================================
# DOOR LOOKUP
# =========================================================

def build_door_lookup(floorplan):

    lookup = {}

    for door in floorplan.get(
        "doors",
        []
    ):

        lookup[
            spatial_key(
                door["x"],
                door["y"]
            )
        ] = door

    return lookup


# =========================================================
# ROOM PATH BFS
# =========================================================

def find_room_path(

    graph,

    start,

    goal
):

    queue = deque([
        [start]
    ])

    visited = set()

    while queue:

        path = queue.popleft()

        room = path[-1]

        if room == goal:
            return path

        if room in visited:
            continue

        visited.add(room)

        for n in graph.get(
            room,
            {}
        ).get(
            "neighbors",
            []
        ):

            queue.append(
                path + [n]
            )

    return []


# =========================================================
# CONNECTING DOOR
# =========================================================

def find_connecting_door(

    building,

    floorplan,

    room_a,

    room_b
):

    for door in floorplan.get(
        "doors",
        []
    ):

        connects = door.get(
            "connects",
            []
        )

        if set(connects) != {
            room_a,
            room_b
        }:
            continue

        portal_id = (
            f"{building['id']}:{door['id']}"
        )

        portal = get_portal(
            building["id"],
            portal_id
        )

        if not portal:
            continue

        if not portal["open"]:
            continue

        if portal["locked"]:
            continue

        return door

    return None


# =========================================================
# ROOM ACCESS
# =========================================================

def can_access_room(
    c,
    room
):

    privacy = room.get(
        "privacy",
        "shared"
    )

    if privacy == "shared":
        return True

    if privacy == "private":

        return (

            room.get(
                "owner_character_id"
            )
            ==
            c["id"]
        )

    return True


# =========================================================
# CACHE FLOORPLAN
# =========================================================

def cache_floorplan(

    building_id,

    floorplan
):

    NAV_CACHE[building_id] = {

        "room_lookup":
            build_room_lookup(
                building_id,
                floorplan
            ),

        "door_lookup":
            build_door_lookup(
                floorplan
            ),

        "room_graph":
            floorplan.get(
                "roomGraph",
                {}
            ),

        "navigation":
            floorplan.get(
                "navigation",
                {}
            ),

        "room_routes": {},

        "portals":
            build_portals(
                building_id,
                floorplan
            ),
    }

    rooms = list(

        floorplan.get(
            "roomGraph",
            {}
        ).keys()
    )

    for a in rooms:

        for b in rooms:

            if a == b:
                continue

            route = find_room_path(

                floorplan.get(
                    "roomGraph",
                    {}
                ),

                a,

                b
            )

            NAV_CACHE[
                building_id
            ][
                "room_routes"
            ][
                room_route_key(a, b)
            ] = route


# =========================================================
# GET PORTAL
# =========================================================

def get_portal(

    building_id,

    portal_id
):

    nav = NAV_CACHE.get(
        building_id
    )

    if not nav:
        return None

    return nav[
        "portals"
    ].get(portal_id)


# =========================================================
# SET PORTAL OPEN
# =========================================================

def set_portal_open(

    building_id,

    portal_id,

    is_open
):

    portal = get_portal(
        building_id,
        portal_id
    )

    if not portal:
        return

    portal["open"] = is_open


# =========================================================
# SET PORTAL LOCKED
# =========================================================

def set_portal_locked(

    building_id,

    portal_id,

    locked
):

    portal = get_portal(
        building_id,
        portal_id
    )

    if not portal:
        return

    portal["locked"] = locked


# =========================================================
# GET ROOM FROM TILE
# =========================================================

def get_room_at_position(

    building,

    x,

    y
):

    building_id = building["id"]

    local = world_to_local(
        building,
        x,
        y
    )

    nav = NAV_CACHE.get(
        building_id
    )

    if not nav:
        return None

    return nav[
        "room_lookup"
    ].get(

        spatial_key(
            local[0],
            local[1]
        )
    )


# =========================================================
# ROOM ROUTE
# =========================================================

def build_room_route(

    floorplan,

    start_room,

    target_room
):

    graph = floorplan.get(
        "roomGraph",
        {}
    )

    return find_room_path(
        graph,
        start_room,
        target_room
    )


# =========================================================
# BUILDING ASTAR
# =========================================================

def build_building_path(

    building,

    floorplan,

    start_tile,

    target_tile
):

    local_start = world_to_local(
        building,
        start_tile[0],
        start_tile[1]
    )

    local_target = world_to_local(
        building,
        target_tile[0],
        target_tile[1]
    )

    blocked_raw = (

        floorplan
        .get(
            "navigation",
            {}
        )
        .get(
            "blocked",
            []
        )
    )

    blocked = set()

    for b in blocked_raw:

        if isinstance(b, str):

            x, y = b.split(",")

            blocked.add((
                int(x),
                int(y)
            ))

        else:

            blocked.add(tuple(b))

    local_path = astar(
        local_start,
        local_target,
        blocked
    )

    world_path = []

    for p in local_path:

        world_path.append(

            local_to_world(
                building,
                p[0],
                p[1]
            )
        )

    return world_path


# =========================================================
# MULTI ROOM PATH
# =========================================================

def build_multi_room_path(

    building,

    floorplan,

    start_tile,

    target_tile
):

    start_room = get_room_at_position(
        building,
        start_tile[0],
        start_tile[1]
    )

    target_room = get_room_at_position(
        building,
        target_tile[0],
        target_tile[1]
    )

    if not start_room:
        return []

    if not target_room:
        return []

    if start_room == target_room:

        return build_building_path(
            building,
            floorplan,
            start_tile,
            target_tile
        )

    room_route = build_room_route(
        floorplan,
        start_room,
        target_room
    )

    if not room_route:
        return []

    final_path = []

    current_tile = start_tile

    for i in range(

        len(room_route) - 1
    ):

        room_a = room_route[i]
        room_b = room_route[i + 1]

        door = find_connecting_door(
            building,
            floorplan,
            room_a,
            room_b
        )

        if not door:
            continue

        door_tile = local_to_world(
            building,
            door["x"],
            door["y"]
        )

        segment = build_building_path(
            building,
            floorplan,
            current_tile,
            door_tile
        )

        final_path.extend(segment)

        current_tile = door_tile

    final_segment = build_building_path(
        building,
        floorplan,
        current_tile,
        target_tile
    )

    final_path.extend(
        final_segment
    )

    return final_path


# =========================================================
# RUNTIME ROOM ID
# =========================================================

def runtime_room_id(

    building_id,

    room_id
):

    return f"{building_id}:{room_id}"


# =========================================================
# ROUTE ORCHESTRATOR
# =========================================================
# Builds the segmented {"type": "indoor"|"outdoor", "tiles": [...],
# "building_id": ...} route shape systems/movement.py's
# update_character_movement() consumes. Works directly off tile.walls
# (the shape the Floorplan Designer/World Editor actually produce) rather
# than the legacy top-level floorplan.doors/rooms/roomGraph schema the
# build_multi_room_path/build_portals machinery above expects — that
# machinery is left as-is for future multi-room buildings once that data
# is authored; this only needs single-room-or-open-plan buildings to work
# indoor <-> outdoor through a door.

_DOOR_SIDE_OFFSETS = {
    "north": (0, -1),
    "south": (0, 1),
    "east":  (1, 0),
    "west":  (-1, 0),
}


def find_building_entrances(building, floorplan):

    entrances = []

    for key, tile in floorplan.get("tiles", {}).items():

        walls = tile.get("walls") or {}

        tx, ty = (int(v) for v in key.split(","))

        for side, wall in walls.items():

            if not wall or wall.get("type") != "door":
                continue

            dx, dy = _DOOR_SIDE_OFFSETS.get(side, (0, 0))

            entrances.append({
                "inside":  local_to_world(building, tx, ty),
                "outside": local_to_world(building, tx + dx, ty + dy),
                "side":    side,
            })

    return entrances


def find_building_at(world, x, y):

    for building in world.get("buildings", []):

        floorplan = resolve_floorplan(world, building)

        if not floorplan:
            continue

        lx, ly = world_to_local(building, x, y)

        if f"{lx},{ly}" in floorplan.get("tiles", {}):
            return building, floorplan

    return None, None


def _nearest_entrance(entrances, key, x, y):

    return min(
        entrances,
        key=lambda e: abs(e[key][0] - x) + abs(e[key][1] - y)
    )


def plan_character_route(world, c, target_x, target_y):

    sx = int(round(c.get("x", 0)))
    sy = int(round(c.get("y", 0)))
    tx = int(round(target_x))
    ty = int(round(target_y))

    start_building = None
    start_floorplan = None

    start_building_id = c.get("building_id")

    if start_building_id:

        start_building = next(
            (b for b in world.get("buildings", []) if b["id"] == start_building_id),
            None
        )

        if start_building:
            start_floorplan = resolve_floorplan(world, start_building)

    # Fall back to position-based lookup — building_id is only ever set by
    # update_character_movement() completing an indoor route segment, so a
    # character that spawned or was placed directly inside a building's
    # footprint won't have it tagged yet.
    if not start_building:
        start_building, start_floorplan = find_building_at(world, sx, sy)

    target_building, target_floorplan = find_building_at(world, tx, ty)

    segments = []

    same_building = (
        start_building
        and target_building
        and start_building["id"] == target_building["id"]
    )

    if same_building:

        tiles = build_building_path(
            start_building, start_floorplan, (sx, sy), (tx, ty)
        )

        if not tiles:
            return False

        segments.append({
            "type": "indoor", "tiles": tiles, "building_id": start_building["id"]
        })

    else:

        exit_point = (sx, sy)

        if start_building:

            entrances = find_building_entrances(start_building, start_floorplan)

            if not entrances:
                return False

            entrance = _nearest_entrance(entrances, "inside", sx, sy)

            indoor_tiles = build_building_path(
                start_building, start_floorplan, (sx, sy), entrance["inside"]
            )

            if indoor_tiles:
                segments.append({
                    "type": "indoor",
                    "tiles": indoor_tiles,
                    "building_id": start_building["id"],
                })

            exit_point = entrance["outside"]

        entry_point = (tx, ty)

        if target_building:

            target_entrances = find_building_entrances(target_building, target_floorplan)

            if not target_entrances:
                return False

            target_entrance = _nearest_entrance(target_entrances, "outside", *exit_point)

            entry_point = target_entrance["outside"]

        if exit_point != entry_point:

            outdoor_tiles = find_outdoor_path(world, exit_point, entry_point)

            if not outdoor_tiles:
                return False

            segments.append({"type": "outdoor", "tiles": outdoor_tiles})

        if target_building:

            indoor_tiles = build_building_path(
                target_building, target_floorplan, target_entrance["inside"], (tx, ty)
            )

            if indoor_tiles:
                segments.append({
                    "type": "indoor",
                    "tiles": indoor_tiles,
                    "building_id": target_building["id"],
                })

    if not segments:
        return False

    c["route"] = segments
    c["route_segment_index"] = 0
    c["path_index"] = 0

    return True