import random
import uuid


# =========================================================
# UPDATE AMBIENT TRAFFIC
# =========================================================

def update_ambient_traffic(world):

    vehicles = world.setdefault(
        "vehicles",
        []
    )

    ambient = [

        v

        for v in vehicles

        if v.get("type")
        == "ambient_traffic"
    ]

    max_traffic = 3

    if len(ambient) < max_traffic:

        if random.random() < 0.0015:

            spawn_traffic_vehicle(
                world
            )

    update_traffic_vehicles(
        world
    )


# =========================================================
# SPAWN TRAFFIC VEHICLE
# =========================================================

def spawn_traffic_vehicle(world):

    traffic = world.get(
        "traffic",
        {}
    )

    entry_points = (

        traffic.get(
            "entry_points",
            []
        )

        or

        world.get(
            "road_entry_points",
            []
        )
    )

    exit_points = (

        traffic.get(
            "exit_points",
            []
        )

        or

        world.get(
            "road_exit_points",
            []
        )
    )

    if not entry_points:
        return None

    if not exit_points:
        return None

    start = random.choice(
        entry_points
    )

    end = random.choice(
        exit_points
    )

    vehicle = {

        "id":
            f"traffic_{uuid.uuid4().hex[:6]}",

        "type":
            "ambient_traffic",

        "x":
            start["x"],

        "y":
            start["y"],

        "entry":
            start,

        "exit":
            end,

        "speed":
            0.25,

        "path":
            [],

        "path_index":
            0,

        "despawn":
            False
    }

    build_vehicle_path(
        vehicle,
        world
    )

    world.setdefault(
        "vehicles",
        []
    ).append(vehicle)

    return vehicle


# =========================================================
# BUILD VEHICLE PATH
# =========================================================

def build_vehicle_path(

    vehicle,

    world
):

    graph = world.get(
        "road_graph",
        {}
    )

    start = (

        vehicle["x"],
        vehicle["y"]
    )

    end = (

        vehicle["exit"]["x"],
        vehicle["exit"]["y"]
    )

    path = simple_road_path(
        graph,
        start,
        end
    )

    vehicle["path"] = path
    vehicle["path_index"] = 0


# =========================================================
# SIMPLE ROAD PATH
# =========================================================

def simple_road_path(

    graph,

    start,

    goal
):

    if start == goal:
        return [start]

    frontier = [start]

    visited = {
        start: None
    }

    while frontier:

        current = frontier.pop(0)

        if current == goal:
            break

        for n in graph.get(
            current,
            []
        ):

            if n in visited:
                continue

            visited[n] = current
            frontier.append(n)

    if goal not in visited:
        return []

    path = []

    cur = goal

    while cur:

        path.append(cur)

        cur = visited[cur]

    path.reverse()

    return path


# =========================================================
# UPDATE VEHICLES
# =========================================================

def update_traffic_vehicles(world):

    vehicles = world.get(
        "vehicles",
        []
    )

    remove = []

    for vehicle in vehicles:

        path = vehicle.get(
            "path",
            []
        )

        if not path:

            remove.append(
                vehicle
            )

            continue

        idx = vehicle.get(
            "path_index",
            0
        )

        if idx >= len(path):

            remove.append(
                vehicle
            )

            continue

        x, y = path[idx]

        vehicle["x"] = x
        vehicle["y"] = y

        vehicle["path_index"] += 1

    for vehicle in remove:

        if vehicle in vehicles:

            vehicles.remove(
                vehicle
            )