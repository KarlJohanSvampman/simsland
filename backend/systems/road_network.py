from collections import deque


# =========================================================
# ENSURE ROAD NETWORK
# =========================================================

def ensure_road_network(world):

    world.setdefault(
        "road_network",
        {}
    )

    world.setdefault(
        "road_entry_points",
        []
    )


# =========================================================
# REGISTER ROAD TILE
# =========================================================

def register_road_tile(

    world,

    x,

    y
):

    ensure_road_network(
        world
    )

    world[
        "road_network"
    ][(x, y)] = []


# =========================================================
# BUILD CONNECTIVITY
# =========================================================

def build_road_connectivity(world):

    roads = world.get(
        "road_network",
        {}
    )

    dirs = [

        (1, 0),
        (-1, 0),
        (0, 1),
        (0, -1)
    ]

    for x, y in roads:

        neighbors = []

        for dx, dy in dirs:

            n = (

                x + dx,

                y + dy
            )

            if n in roads:

                neighbors.append(n)

        roads[(x, y)] = neighbors


# =========================================================
# FIND ROAD PATH
# =========================================================

def find_road_path(

    world,

    start,

    goal
):

    roads = world.get(
        "road_network",
        {}
    )

    queue = deque()
    queue.append(start)

    came_from = {
        start: None
    }

    while queue:

        current = queue.popleft()

        if current == goal:
            break

        for neighbor in roads.get(
            current,
            []
        ):

            if neighbor in came_from:
                continue

            came_from[
                neighbor
            ] = current

            queue.append(
                neighbor
            )

    if goal not in came_from:
        return []

    path = []

    current = goal

    while current:

        path.append(current)

        current = came_from[
            current
        ]

    path.reverse()

    return path


# =========================================================
# NEAREST ROAD TILE
# =========================================================

def nearest_road_tile(

    world,

    x,

    y
):

    roads = world.get(
        "road_network",
        {}
    )

    best = None
    best_dist = 999999

    for rx, ry in roads:

        dx = rx - x
        dy = ry - y

        dist = (
            dx * dx
            +
            dy * dy
        )

        if dist < best_dist:

            best_dist = dist
            best = (rx, ry)

    return best