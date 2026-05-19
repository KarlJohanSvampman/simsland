from heapq import heappush, heappop


# =========================================================
# BUILD OUTDOOR NAVIGATION
# =========================================================

def build_outdoor_navigation(world):

    graph = {}

    lookup = world.get(
        "world_tile_lookup",
        {}
    )

    for (x, y), tile in lookup.items():

        if not tile.get(
            "walkable",
            False
        ):
            continue

        neighbors = []

        for dx, dy in [

            (1, 0),
            (-1, 0),
            (0, 1),
            (0, -1)
        ]:

            nx = x + dx
            ny = y + dy

            neighbor = lookup.get(
                (nx, ny)
            )

            if not neighbor:
                continue

            if not neighbor.get(
                "walkable",
                False
            ):
                continue

            neighbors.append({

                "x": nx,

                "y": ny,

                "cost":
                    neighbor.get(
                        "movement_cost",
                        1.0
                    )
            })

        graph[(x, y)] = neighbors

    world[
        "outdoor_navigation"
    ] = graph


# =========================================================
# HEURISTIC
# =========================================================

def heuristic(a, b):

    return abs(a[0] - b[0]) + abs(a[1] - b[1])

# =========================================================
# OUTDOOR PATHFINDING
# =========================================================

def find_outdoor_path(

    world,

    start,

    goal
):

    graph = world.get(
        "outdoor_navigation",
        {}
    )

    if start not in graph:
        return []

    if goal not in graph:
        return []

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

                current = came_from[
                    current
                ]

            path.reverse()

            return path

        for neighbor in graph[
            current
        ]:

            nxt = (

                neighbor["x"],

                neighbor["y"]
            )

            movement_cost = neighbor[
                "cost"
            ]

            tentative = (

                g_score[current]
                + movement_cost
            )

            if tentative < g_score.get(
                nxt,
                999999
            ):

                came_from[nxt] = current

                g_score[nxt] = tentative

                f = (

                    tentative
                    + heuristic(
                        nxt,
                        goal
                    )
                )

                heappush(

                    open_set,

                    (f, nxt)
                )

    return []