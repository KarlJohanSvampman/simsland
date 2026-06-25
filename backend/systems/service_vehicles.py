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

    traffic = world.get(
        "traffic",
        {}
    )

    entries = (

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

    if not entries:
        return None

    entry = entries[0]

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
            0,

        "entry_point":
            entry
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

    # =====================================
    # FINISHED ALL TARGETS
    # =====================================

    if idx >= len(targets):

        traffic = world.get(
            "traffic",
            {}
        )

        exits = (

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

        if not exits:

            vehicle["state"] = (
                "despawn"
            )

            return

        exit_point = exits[0]

        current = (

            int(vehicle["x"]),
            int(vehicle["y"])
        )

        vehicle["route"] = (

            find_road_path(

                world,

                current,

                (
                    exit_point["x"],
                    exit_point["y"]
                )
            )
        )

        vehicle["state"] = (
            "leaving"
        )

        return

    # =====================================
    # NEXT HOUSE
    # =====================================

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

    vehicle["route"] = (

        find_road_path(

            world,

            current,

            road_target
        )
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

# =========================================================
# UPDATE VEHICLE
# =========================================================

def update_vehicle(

    vehicle,

    world
):

    state = vehicle.get(
        "state"
    )

    # =====================================================
    # WAITING
    # =====================================================

    if state == "waiting_for_worker":

        # worker runtime will
        # reactivate vehicle later

        return

    # =====================================================
    # NO ROUTE
    # =====================================================

    route = vehicle.get(
        "route",
        []
    )

    if not route:

        if state == "leaving":

            despawn_vehicle(
                vehicle,
                world
            )

            return

        if state == "despawn":

            despawn_vehicle(
                vehicle,
                world
            )

            return

        vehicle["state"] = (
            "parked"
        )

        spawn_service_worker(
            vehicle,
            world
        )

        vehicle["state"] = (
            "waiting_for_worker"
        )

        return

        # ================================================
        # ARRIVED
        # ================================================

        vehicle["state"] = (
            "parked"
        )

        spawn_service_worker(

            vehicle,

            world
        )

        vehicle["state"] = (
            "waiting_for_worker"
        )

        return

    # =====================================================
    # DRIVING
    # =====================================================

    vehicle["state"] = "driving"

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
    vehicle["parked_x"] = (
        vehicle["x"] + 0.3
    )

    vehicle["parked_y"] = (
        vehicle["y"]
    )
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


    # =========================================================
# WORKER FINISHED
# =========================================================

def service_worker_complete(

    vehicle,

    world
):

    vehicle[
        "current_target"
    ] += 1

    assign_next_vehicle_route(

        vehicle,

        world
    )

    vehicle["state"] = (
        "driving"
    )