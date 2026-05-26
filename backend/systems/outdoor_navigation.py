from heapq import heappush, heappop

from core.spatial import (
    spatial_key,
    parse_spatial_key
)


# =========================================================
# BUILD OUTDOOR NAVIGATION
# =========================================================

def build_outdoor_navigation(world):

    graph = {}

    lookup = world.get(
        "world_tile_lookup",
        {}
    )

    for key, tile in lookup.items():

        x, y = parse_spatial_key(
            key
        )

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

                spatial_key(
                    nx,
                    ny
                )
            )

            if not neighbor:
                continue

            if not neighbor.get(
                "walkable",
                False
            ):
                continue

            neighbors.append({

                "key":
                    spatial_key(
                        nx,
                        ny
                    ),

                "cost":
                    neighbor.get(
                        "movement_cost",
                        1.0
                    )
            })

        graph[
            spatial_key(x, y)
        ] = neighbors

    world[
        "outdoor_navigation"
    ] = graph


# =========================================================
# HEURISTIC
# =========================================================

def heuristic(a, b):

    ax, ay = parse_spatial_key(a)
    bx, by = parse_spatial_key(b)

    return (
        abs(ax - bx)
        +
        abs(ay - by)
    )


# =========================================================
# OUTDOOR PATHFINDING
# =========================================================

def find_outdoor_path(

    world,

    start,

    goal
):

    if isinstance(start, tuple):

        start = spatial_key(
            start[0],
            start[1]
        )

    if isinstance(goal, tuple):

        goal = spatial_key(
            goal[0],
            goal[1]
        )

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

                path.append(

                    parse_spatial_key(
                        current
                    )
                )

                current = came_from[
                    current
                ]

            path.reverse()

            return path

        for neighbor in graph[
            current
        ]:

            nxt = neighbor["key"]

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
                    +
                    heuristic(
                        nxt,
                        goal
                    )
                )

                heappush(
                    open_set,
                    (f, nxt)
                )

    return []