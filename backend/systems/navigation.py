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

ASTAR_MARGIN = 40          # cells of slack around the start/goal box
ASTAR_MAX_EXPANSIONS = 60000


def astar(start, goal, blocked):
    """A* on an unbounded grid. It MUST be bounded: with an unreachable or
    blocked goal the open set never empties, and one such call eats memory at
    tens of MB/s until the container dies."""
    min_x = min(start[0], goal[0]) - ASTAR_MARGIN
    max_x = max(start[0], goal[0]) + ASTAR_MARGIN
    min_y = min(start[1], goal[1]) - ASTAR_MARGIN
    max_y = max(start[1], goal[1]) + ASTAR_MARGIN
    expansions = 0

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

        expansions += 1
        if expansions > ASTAR_MAX_EXPANSIONS:
            return []

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

            if not (min_x <= n[0] <= max_x and min_y <= n[1] <= max_y):
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


def _tile_has_floor(tiles, key):
    """A floorplan tile is indoors if it has a floor. Tiles with "floor": null are
    the yard/doorstep inside a building's plot; a tile with no "floor" key at all
    (older, simpler floorplans) counts as indoors, as before."""
    tile = tiles.get(key)
    if tile is None:
        return False
    return bool(tile.get("floor", True))


def find_building_entrances(building, floorplan):
    """The doors that lead OUT of the building: "inside" is the floor tile, "outside"
    the tile beyond the door.

    Only doors between an indoor (floor) tile and an outdoor one count -- a door
    between two rooms is not a way out. Before multi-room floorplans this returned
    every door, so the nearest "entrance" could be a bedroom door whose "outside"
    tile was still indoors, and a door authored from its outdoor side came out
    inside-out; every route between two starter_houses failed (2026-11-01). A
    floorplan with no such door at all keeps the old every-door behaviour."""

    tiles = floorplan.get("tiles", {})
    exterior, every_door, seen = [], [], set()

    for key, tile in tiles.items():

        walls = tile.get("walls") or {}

        tx, ty = (int(v) for v in key.split(","))

        for side, wall in walls.items():

            if not wall or wall.get("type") != "door":
                continue

            dx, dy = _DOOR_SIDE_OFFSETS.get(side, (0, 0))
            other = f"{tx + dx},{ty + dy}"

            every_door.append({
                "inside":  local_to_world(building, tx, ty),
                "outside": local_to_world(building, tx + dx, ty + dy),
                "side":    side,
            })

            here_in, other_in = _tile_has_floor(tiles, key), _tile_has_floor(tiles, other)
            if here_in == other_in:
                continue                                    # between two rooms (or two yard tiles)
            inside, outside = ((tx, ty), (tx + dx, ty + dy)) if here_in else ((tx + dx, ty + dy), (tx, ty))
            if (inside, outside) in seen:
                continue                                    # the same door, authored on both of its tiles
            seen.add((inside, outside))
            exterior.append({
                "inside":  local_to_world(building, *inside),
                "outside": local_to_world(building, *outside),
                "side":    side,
            })

    return exterior or every_door


def find_building_at(world, x, y):

    for building in world.get("buildings", []):

        floorplan = resolve_floorplan(world, building)

        if not floorplan:
            continue

        lx, ly = world_to_local(building, x, y)

        # On a floor tile = in the building; the plot's yard/doorstep tiles are outdoors.
        if _tile_has_floor(floorplan.get("tiles", {}), f"{lx},{ly}"):
            return building, floorplan

    return None, None


def _bridge_to_outdoor_graph(world, point, max_steps=6):
    """Tiles from `point` (exclusive) to the nearest node of the outdoor walking
    graph (inclusive): [] if `point` already is one, None if none is within reach.

    The outdoor graph leaves out every tile of a building's plot, including the
    doorstep just outside a front door, so a route leaving through a door had
    nowhere to join the street. Steps over walkable world tiles only."""
    graph = world.get("outdoor_navigation", {})
    lookup = world.get("world_tile_lookup", {})
    start = (int(point[0]), int(point[1]))
    if spatial_key(*start) in graph:
        return []
    came_from = {start: None}
    queue = deque([(start, 0)])
    while queue:
        (x, y), steps = queue.popleft()
        if steps >= max_steps:
            continue
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nxt = (x + dx, y + dy)
            if nxt in came_from:
                continue
            tile = lookup.get(spatial_key(*nxt))
            if not tile or not tile.get("walkable", False):
                continue
            came_from[nxt] = (x, y)
            if spatial_key(*nxt) in graph:
                path = [nxt]
                while came_from[path[-1]] != start:
                    path.append(came_from[path[-1]])
                return list(reversed(path))
            queue.append((nxt, steps + 1))
    return None


def _outdoor_tiles(world, exit_point, entry_point):
    """The outdoor leg from a building's door (or anywhere outside) to another door
    (or anywhere outside), bridging doorsteps the outdoor graph doesn't contain.
    None if there is no way."""
    leaving = _bridge_to_outdoor_graph(world, exit_point)
    arriving = _bridge_to_outdoor_graph(world, entry_point)
    if leaving is None or arriving is None:
        return None
    start = leaving[-1] if leaving else tuple(exit_point)
    goal = arriving[-1] if arriving else tuple(entry_point)
    middle = []
    if start != goal:
        middle = find_outdoor_path(world, start, goal)
        if not middle:
            return None
    # arriving runs entry_point -> graph node; walk it the other way, ending ON entry_point
    back_in = (list(reversed(arriving[:-1])) + [tuple(entry_point)]) if arriving else []
    # step onto the doorstep itself first, rather than cutting across it
    out_the_door = [tuple(exit_point)] if leaving else []
    return out_the_door + leaving + list(middle) + back_in


def _nearest_entrance(entrances, key, x, y):

    return min(
        entrances,
        key=lambda e: abs(e[key][0] - x) + abs(e[key][1] - y)
    )


def plan_character_route(world, c, target_x, target_y):
    """Plan c's route to (target_x, target_y) into c["route"]. True if there is one. Every plan is recorded for
    debugging (systems/path_debug.py: c["path_plans"], drawn in the Inspector), and a real failure to find a way is
    made impossible to miss."""
    ok, reason = _plan_route(world, c, target_x, target_y)
    try:
        from systems.path_debug import record
        record(c, world, (target_x, target_y), ok, reason)
    except Exception as exc:                       # noqa: BLE001 -- debugging must never break movement
        print(f"[path_debug] {c.get('id')}: {exc!r}")
    return ok


def _plan_route(world, c, target_x, target_y):
    """plan_character_route()'s planning: (ok, reason)."""

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
            return False, ("already_there" if (sx, sy) == (tx, ty) else "no_indoor_path")

        segments.append({
            "type": "indoor", "tiles": tiles, "building_id": start_building["id"]
        })

    else:

        exit_point = (sx, sy)

        if start_building:

            entrances = find_building_entrances(start_building, start_floorplan)

            if not entrances:
                return False, "start_building_has_no_entrance"

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
                return False, "target_building_has_no_entrance"

            target_entrance = _nearest_entrance(target_entrances, "outside", *exit_point)

            entry_point = target_entrance["outside"]

        if exit_point != entry_point:

            outdoor_tiles = _outdoor_tiles(world, exit_point, entry_point)

            if not outdoor_tiles:
                return False, "no_outdoor_path"

            segments.append({"type": "outdoor", "tiles": outdoor_tiles})

        if target_building:

            indoor_tiles = build_building_path(
                target_building, target_floorplan, target_entrance["inside"], (tx, ty)
            )

            # The target is the tile just inside the door itself (the walk home goes there): there is no indoor
            # path to plan, but they still have to step in off the doorstep.
            if not indoor_tiles and tuple(target_entrance["inside"]) == (tx, ty):
                indoor_tiles = [(tx, ty)]

            if indoor_tiles:
                segments.append({
                    "type": "indoor",
                    "tiles": indoor_tiles,
                    "building_id": target_building["id"],
                })

    if not segments:
        return False, "already_there" if (sx, sy) == (tx, ty) else "no_route"

    c["route"] = segments
    c["route_segment_index"] = 0
    c["path_index"] = 0

    partial = target_building and not any(seg.get("building_id") == target_building["id"] for seg in segments)
    return True, "partial_stops_outside" if partial else "ok"
