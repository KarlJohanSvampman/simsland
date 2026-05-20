from heapq import heappush, heappop
from collections import deque

from systems.navigation_cache import NAV_CACHE

from systems.transforms import (

    world_to_local,

    local_to_world
)


# =========================================================
# HEURISTIC
# =========================================================

def heuristic(a, b):

    return (

        abs(a[0] - b[0])

        + abs(a[1] - b[1])
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
                    + heuristic(n, goal)
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

            f"{building_id}:"

            f"{door['id']}"
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

def build_room_lookup(building_id,floorplan):

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
                (tile_x, tile_y)
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
            (
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

            f"{building['id']}:"

            f"{door['id']}"
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

            == c["id"]
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
                (a, b)
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
    ].get(local)


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

    # =====================================
    # LOCAL -> WORLD
    # =====================================

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

    # =====================================
    # SAME ROOM
    # =====================================

    if start_room == target_room:

        return build_building_path(
            building,

            floorplan,

            start_tile,

            target_tile
        )

    # =====================================
    # ROOM ROUTE
    # =====================================

    room_route = build_room_route(

        floorplan,

        start_room,

        target_room
    )

    if not room_route:
        return []

    final_path = []

    current_tile = start_tile

    # =====================================
    # ROOM-TO-ROOM
    # =====================================

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

    # =====================================
    # FINAL SEGMENT
    # =====================================

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

