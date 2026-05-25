import random
import uuid

from systems.service_vehicles import (
    spawn_service_vehicle
)


# =========================================================
# UPDATE AMBIENT TRAFFIC
# =========================================================

def update_ambient_traffic(world):

    traffic = world.get(
        "ambient_traffic",
        []
    )

    max_traffic = 3

    if len(traffic) >= max_traffic:
        return

    # =====================================================
    # RANDOM SPAWN
    # =====================================================

    if random.random() > 0.0015:
        return

    spawn_traffic_vehicle(world)


# =========================================================
# SPAWN TRAFFIC VEHICLE
# =========================================================

def spawn_traffic_vehicle(world):

    entry = random.choice(

        world[
            "road_entry_points"
        ]
    )

    vehicle = {

        "id":
            str(uuid.uuid4()),

        "type":
            "vehicle",

        "service_type":
            "civilian",

        "vehicle_model":
            random.choice([

                "sedan",

                "pickup",

                "compact",

                "suv"
            ]),

        "x":
            entry["x"],

        "y":
            entry["y"],

        "speed":
            random.uniform(
                0.03,
                0.06
            ),

        "route":
            generate_random_drive(
                world
            ),

        "state":
            "driving"
    }

    world.setdefault(
        "service_vehicles",
        []
    )

    world[
        "service_vehicles"
    ].append(vehicle)

    world.setdefault(
        "ambient_traffic",
        []
    )

    world[
        "ambient_traffic"
    ].append(vehicle)


# =========================================================
# RANDOM DRIVE
# =========================================================

def generate_random_drive(world):

    roads = list(

        world.get(
            "road_network",
            {}
        ).keys()
    )

    if len(roads) < 2:
        return []

    return random.sample(

        roads,

        min(
            20,
            len(roads)
        )
    )