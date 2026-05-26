from collections import deque


# =========================================================
# ROAD KEY
# =========================================================

def road_key(x, y):

    return f"{x},{y}"


# =========================================================
# PARSE ROAD KEY
# =========================================================

def parse_road_key(key):

    x, y = key.split(",")

    return int(x), int(y)


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

    key = road_key(x, y)

    world[
        "road_network"
    ].setdefault(

        key,

        []
    )


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

    for key in roads.keys():

        x, y = parse_road_key(
            key
        )

        neighbors = []

        for dx, dy in dirs:

            nx = x + dx
            ny = y + dy

            neighbor_key = road_key(
                nx,
                ny
            )

            if neighbor_key in roads:

                neighbors.append(
                    neighbor_key
                )

        roads[key] = neighbors


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

    # =====================================================
    # NORMALIZE
    # =====================================================

    if isinstance(start, tuple):

        start = road_key(
            start[0],
            start[1]
        )

    if isinstance(goal, tuple):

        goal = road_key(
            goal[0],
            goal[1]
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

    # =====================================================
    # REBUILD PATH
    # =====================================================

    path = []

    current = goal

    while current:

        path.append(

            parse_road_key(
                current
            )
        )

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

    for key in roads.keys():

        rx, ry = parse_road_key(
            key
        )

        dx = rx - x
        dy = ry - y

        dist = (
            dx * dx
            +
            dy * dy
        )

        if dist < best_dist:

            best_dist = dist

            best = (
                rx,
                ry
            )

    return best