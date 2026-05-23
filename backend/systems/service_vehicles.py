import uuid

from systems.road_network import (
    find_road_path,
    nearest_road_tile
)


# =========================================================
# SPAWN SERVICE VEHICLE
# =========================================================

def spawn_service_vehicle(

    world,

    service_type,

    vehicle_model,

    worker_model,

    target_households
):

    entry = world[
        "road_entry_points"
    ][0]

    vehicle = {

        "id":
            str(uuid.uuid4()),

        "type":
            "vehicle",

        "service_type":
            service_type,

        "vehicle_model":
            vehicle_model,

        "worker_model":
            worker_model,

        "x":
            entry["x"],

        "y":
            entry["y"],

        "route": [],

        "state":
            "driving",

        "speed":
            0.05,

        "targets":
            target_households,

        "current_target":
            0
    }

    world.setdefault(
        "service_vehicles",
        []
    )

    world[
        "service_vehicles"
    ].append(vehicle)

    assign_next_vehicle_route(

        vehicle,

        world
    )

    return vehicle


# =========================================================
# ASSIGN NEXT ROUTE
# =========================================================

def assign_next_vehicle_route(

    vehicle,

    world
):

    targets = vehicle[
        "targets"
    ]

    idx = vehicle[
        "current_target"
    ]

    if idx >= len(targets):

        vehicle["state"] = (
            "leaving"
        )

        return

    household = targets[idx]

    road_target = nearest_road_tile(

        world,

        household[
            "mailbox"
        ]["x"],

        household[
            "mailbox"
        ]["y"]
    )

    current = (

        int(vehicle["x"]),

        int(vehicle["y"])
    )

    vehicle["route"] = find_road_path(

        world,

        current,

        road_target
    )


# =========================================================
# UPDATE SERVICE VEHICLES
# =========================================================

def update_service_vehicles(world):

    vehicles = world.get(
        "service_vehicles",
        []
    )

    for vehicle in vehicles:

        update_vehicle(
            vehicle,
            world
        )


# =========================================================
# UPDATE VEHICLE
# =========================================================

def update_vehicle(

    vehicle,

    world
):

    route = vehicle.get(
        "route",
        []
    )

    if not route:

        if vehicle[
            "state"
        ] == "leaving":

            despawn_vehicle(

                vehicle,

                world
            )

            return

        spawn_service_worker(

            vehicle,

            world
        )

        return

    next_node = route[0]

    tx, ty = next_node

    dx = tx - vehicle["x"]
    dy = ty - vehicle["y"]

    dist = (
        dx * dx
        +
        dy * dy
    ) ** 0.5

    speed = vehicle.get(
        "speed",
        0.05
    )

    if dist <= speed:

        vehicle["x"] = tx
        vehicle["y"] = ty

        route.pop(0)

        return

    vehicle["x"] += (
        dx / dist
    ) * speed

    vehicle["y"] += (
        dy / dist
    ) * speed


# =========================================================
# SPAWN WORKER
# =========================================================

def spawn_service_worker(

    vehicle,

    world
):

    targets = vehicle[
        "targets"
    ]

    idx = vehicle[
        "current_target"
    ]

    if idx >= len(targets):
        return

    household = targets[idx]

    worker = {

        "id":
            str(uuid.uuid4()),

        "type":
            "service_worker",

        "service_type":
            vehicle[
                "service_type"
            ],

        "model":
            vehicle[
                "worker_model"
            ],

        "x":
            vehicle["x"],

        "y":
            vehicle["y"],

        "target_x":
            household[
                "mailbox"
            ]["x"],

        "target_y":
            household[
                "mailbox"
            ]["y"],

        "vehicle_id":
            vehicle["id"],

        "household_id":
            household["id"],

        "state":
            "walking_to_mailbox",

        "animation_state":
            "carry_box"
    }

    world.setdefault(
        "service_workers",
        []
    )

    world[
        "service_workers"
    ].append(worker)


# =========================================================
# DESPAWN
# =========================================================

def despawn_vehicle(

    vehicle,

    world
):

    world[
        "service_vehicles"
    ].remove(vehicle)