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

    # Through doors, never through walls (systems/building_grid.py). If the floorplan leaves no way at all (a room
    # authored without a door), fall back to the old wall-blind path, and say so in the path log.
    from systems.building_grid import path as walled_path
    local_path = walled_path(floorplan, local_start, local_target, blocked)
    if not local_path and tuple(local_start) != tuple(local_target):
        local_path = astar(local_start, local_target, blocked)
        if local_path:
            print(f"[path] {building.get('id')}: no way from {tuple(local_start)} to {tuple(local_target)} "
                  f"without going through a wall -- check the floorplan's doors; walked through it")

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


def _inside(floorplan, lx, ly):
    """Enclosed by the building's walls (systems/building_grid.py) -- not merely "has a floor"."""
    from systems.building_grid import is_inside
    return is_inside(floorplan, lx, ly)


def _tile_has_floor(tiles, key):
    """A floorplan tile is indoors if it has a floor. Tiles with "floor": null are
    the yard/doorstep inside a building's plot; a tile with no "floor" key at all
    (older, simpler floorplans) counts as indoors, as before."""
    tile = tiles.get(key)
    if tile is None:
        return False
    return bool(tile.get("floor", True))


def find_building_entrances(building, floorplan):
    """The doors that lead OUT of the building: "inside" is the enclosed tile, "outside" the one beyond the door
    (systems/building_grid.py works out which tiles the walls enclose). A floorplan with no such door keeps the old
    every-door behaviour."""
    from systems.building_grid import analyse
    out = [{"inside": local_to_world(building, *e["inside"]), "outside": local_to_world(building, *e["outside"]),
            "side": e["side"]} for e in analyse(floorplan)["entrances"]]
    if out:
        return out
    every_door = []
    for key, tile in (floorplan.get("tiles") or {}).items():
        tx, ty = (int(v) for v in key.split(","))
        for side, wall in ((tile or {}).get("walls") or {}).items():
            if wall and wall.get("type") == "door":
                dx, dy = _DOOR_SIDE_OFFSETS.get(side, (0, 0))
                every_door.append({"inside": local_to_world(building, tx, ty),
                                   "outside": local_to_world(building, tx + dx, ty + dy), "side": side})
    return every_door


def find_building_at(world, x, y):

    for building in world.get("buildings", []):

        floorplan = resolve_floorplan(world, building)

        if not floorplan:
            continue

        lx, ly = world_to_local(building, x, y)

        # Inside the walls = in the building; the plot's yard/doorstep tiles are outdoors.
        if _inside(floorplan, lx, ly):
            return building, floorplan

    return None, None


def _bridge_to_outdoor_graph(world, point, max_steps=40):
    """Tiles from `point` (exclusive) to the nearest node of the outdoor walking
    graph (inclusive): [] if `point` already is one, None if none is within reach.

    The outdoor graph leaves out every tile of a building's plot, including the
    doorstep just outside a front door, so a route leaving through a door had
    nowhere to join the street. Steps over walkable world tiles only. Reaches far
    enough to get round a house: a back-yard tile is a dozen or more steps from the
    street (6 was enough for a doorstep, not for the back of the house, where
    characters were left looking for "a way in")."""
    graph = world.get("outdoor_navigation", {})
    lookup = world.get("world_tile_lookup", {})
    start = (int(point[0]), int(point[1]))
    if spatial_key(*start) in graph:
        return []
    plots = _plots(world)
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
            if _blocked_outdoors(world, (x, y), nxt, plots):
                continue
            came_from[nxt] = (x, y)
            if spatial_key(*nxt) in graph:
                path = [nxt]
                while came_from[path[-1]] != start:
                    path.append(came_from[path[-1]])
                return list(reversed(path))
            queue.append((nxt, steps + 1))
    return None


_PLOT_CACHE = {}


def _plots(world):
    """world tile -> [(floorplan, local tile, inside?)] for every building plot (and a tile's ring round it). Cached
    per buildings list."""
    from systems.building_grid import analyse
    buildings = world.get("buildings", [])
    key = (id(buildings), len(buildings),
           tuple((b.get("id"), id((resolve_floorplan(world, b) or {}).get("tiles")),
                  len((resolve_floorplan(world, b) or {}).get("tiles") or {})) for b in buildings))
    hit = _PLOT_CACHE.get("key")
    if hit == key:
        return _PLOT_CACHE["map"]
    out = {}
    for building in buildings:
        floorplan = resolve_floorplan(world, building)
        if not floorplan:
            continue
        g = analyse(floorplan)
        for lx in range(-1, g["width"] + 1):
            for ly in range(-1, g["height"] + 1):
                wx, wy = local_to_world(building, lx, ly)
                out.setdefault((int(wx), int(wy)), []).append((floorplan, (lx, ly), (lx, ly) in g["inside"]))
    _PLOT_CACHE.clear()
    _PLOT_CACHE.update(key=key, map=out)
    return out


def _blocked_outdoors(world, a, b, plots=None):
    """A step outside that would go into a building or through one of its walls (a fence, the back wall)."""
    from systems.building_grid import edge
    plots = plots if plots is not None else _plots(world)
    pa = {id(fp): (la, ins) for fp, la, ins in plots.get((int(a[0]), int(a[1])), [])}
    for fp, lb, inside_b in plots.get((int(b[0]), int(b[1])), []):
        la, inside_a = pa.get(id(fp), (None, False))
        if inside_b and not inside_a:
            return True
        if la is not None and edge(fp.get("tiles") or {}, la, lb) in ("wall", "window"):
            return True
    return False


def _walk_tiles(world, a, b, margin=25, limit=30000):
    """Outside, tile by tile over walkable ground, never into a building or through a wall: [a, ..., b] or None."""
    lookup = world.get("world_tile_lookup", {})
    a, b = (int(a[0]), int(a[1])), (int(b[0]), int(b[1]))
    lo_x, hi_x = min(a[0], b[0]) - margin, max(a[0], b[0]) + margin
    lo_y, hi_y = min(a[1], b[1]) - margin, max(a[1], b[1]) + margin
    plots = _plots(world)
    came = {a: None}
    queue = deque([a])
    while queue and len(came) < limit:
        cur = queue.popleft()
        if cur == b:
            out = [cur]
            while came[out[-1]] is not None:
                out.append(came[out[-1]])
            return list(reversed(out))
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in came or not (lo_x <= nxt[0] <= hi_x and lo_y <= nxt[1] <= hi_y):
                continue
            tile = lookup.get(spatial_key(*nxt))
            if not tile or not tile.get("walkable", False) or _blocked_outdoors(world, cur, nxt, plots):
                continue
            came[nxt] = cur
            queue.append(nxt)
    return None


def _outdoor_tiles(world, exit_point, entry_point):
    """The outdoor leg from a building's door (or anywhere outside) to another door
    (or anywhere outside), bridging doorsteps the outdoor graph doesn't contain.
    None if there is no way."""
    leaving = _bridge_to_outdoor_graph(world, exit_point)
    arriving = _bridge_to_outdoor_graph(world, entry_point)
    if leaving is None or arriving is None:
        return _walk_tiles(world, exit_point, entry_point)
    start = leaving[-1] if leaving else tuple(exit_point)
    goal = arriving[-1] if arriving else tuple(entry_point)
    middle = []
    if start != goal:
        middle = find_outdoor_path(world, start, goal)
        if not middle:
            # the nearest graph node can be a little island (a strip of yard behind a house the street graph
            # doesn't join up): walk the ground itself instead
            return _walk_tiles(world, exit_point, entry_point)
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

        # Every way out of the start building and every way into the target one is a candidate (a house has a front
        # and a back door): the shortest combination whose outdoor leg exists wins. Only the nearest door used to be
        # tried, so the back yard was unreachable from a house whose nearest door is the front one.
        starts = [None]
        if start_building:
            starts = find_building_entrances(start_building, start_floorplan)
            if not starts:
                return False, "start_building_has_no_entrance"
        ends = [None]
        if target_building:
            ends = find_building_entrances(target_building, target_floorplan)
            if not ends:
                return False, "target_building_has_no_entrance"

        def _guess(pair):
            e, t = pair
            ex = e["outside"] if e else (sx, sy)
            en = t["outside"] if t else (tx, ty)
            return ((abs(e["inside"][0] - sx) + abs(e["inside"][1] - sy) if e else 0)
                    + abs(ex[0] - en[0]) + abs(ex[1] - en[1])
                    + (abs(t["inside"][0] - tx) + abs(t["inside"][1] - ty) if t else 0))

        best, failed = None, "no_outdoor_path"
        for entrance, target_entrance in sorted(((e, t) for e in starts for t in ends), key=_guess)[:9]:
            segs = []
            exit_point = (sx, sy)
            if entrance:
                indoor_tiles = build_building_path(start_building, start_floorplan, (sx, sy), entrance["inside"])
                if not indoor_tiles and (sx, sy) != tuple(entrance["inside"]):
                    failed = "no_indoor_path"
                    continue
                if indoor_tiles:
                    segs.append({"type": "indoor", "tiles": indoor_tiles, "building_id": start_building["id"]})
                exit_point = entrance["outside"]
            entry_point = target_entrance["outside"] if target_entrance else (tx, ty)
            if exit_point != entry_point:
                outdoor_tiles = _outdoor_tiles(world, exit_point, entry_point)
                if not outdoor_tiles:
                    failed = "no_outdoor_path"
                    continue
                segs.append({"type": "outdoor", "tiles": outdoor_tiles})
            elif entrance and (sx, sy) != tuple(exit_point):
                # Standing on the tile just inside the door, headed for the doorstep beyond it: no indoor leg and no
                # outdoor leg, but they still have to step out. This came back as "no_route" and sent the
                # character into a no-path episode one step from the door (Robert, 2026-11-04).
                segs.append({"type": "outdoor", "tiles": [tuple(exit_point)]})
            if target_entrance:
                indoor_tiles = build_building_path(target_building, target_floorplan, target_entrance["inside"], (tx, ty))
                # The target is the tile just inside the door itself (the walk home goes there): no indoor path to
                # plan, but they still have to step in off the doorstep.
                if not indoor_tiles and tuple(target_entrance["inside"]) == (tx, ty):
                    indoor_tiles = [(tx, ty)]
                if not indoor_tiles:
                    failed = "no_indoor_path"
                    continue
                segs.append({"type": "indoor", "tiles": indoor_tiles, "building_id": target_building["id"]})
            length = sum(len(sg["tiles"]) for sg in segs)
            if best is None or length < best[0]:
                best = (length, segs)
        if best is None:
            return False, failed
        segments = best[1]

    if not segments:
        return False, "already_there" if (sx, sy) == (tx, ty) else "no_route"

    c["route"] = segments
    c["route_segment_index"] = 0
    c["path_index"] = 0

    partial = target_building and not any(seg.get("building_id") == target_building["id"] for seg in segments)
    return True, "partial_stops_outside" if partial else "ok"
