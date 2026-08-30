"""
systems/rideshare.py

General "get me a ride" primitive. Two ways in:
  - REQUESTED: the character in need calls a taxi (request_pickup(...,
    method="taxi"), driven by the new order_taxi_by_phone_call/
    order_taxi_by_phone_app actions + the order_taxi activity in
    action_router.py/activities.py) or asks a specific contact
    (method="friend", routed through systems/proposals.py's real
    request/favor engine -- accept/decline/counter like any other ask,
    Phase 4.7's ledger applies).
  - PROPOSED: someone else offers first ("why don't you let me give you
    a ride?") -- suggest_ride() below, a thin wrapper around the same
    proposals.py engine from the other direction. Nothing new to
    register as an action for this: it's just propose_social_ask() with
    ride-specific framing, exactly like every other social ask the LLM
    already has access to via the existing propose_social action.

Built as its own small vehicle+worker dispatch rather than reusing
systems/service_vehicles.py::spawn_service_vehicle() directly -- that
factory (mail/paperboy) is tightly coupled to routing toward a
HOUSEHOLD's fixed mailbox position (spawn_service_worker() hardcodes
household["mailbox"]["x"/"y"] as the only possible destination), not an
arbitrary waiting character's current location. This reuses its
LOW-LEVEL road-pathing primitives (road_network.py) instead.

c["pickup_request"] = {
    "method":          "taxi" | "friend",
    "location":        {"x","y"},
    "destination":     {"x","y"} | None,
    "status":          "waiting_vehicle" | "in_transit" | "arrived",
    "vehicle_id":      str | None,
    "requested_tick":  int,
}
"""

import uuid

from systems.road_network import find_road_path, nearest_road_tile

TAXI_SPEED = 0.05


def request_pickup(c, world, location, method="taxi", contact_id=None, destination=None):
    """Character waits at `location` for a ride."""
    c["pickup_request"] = {
        "method":         method,
        "location":       dict(location),
        "destination":    dict(destination) if destination else None,
        "status":         "waiting_vehicle",
        "vehicle_id":     None,
        "requested_tick": world.get("tick", 0),
    }

    if method == "taxi":
        return _dispatch_taxi(c, world)

    if method == "friend" and contact_id:
        contact = world.get("characters", {}).get(contact_id)
        if not contact:
            return {"ok": False, "reason": "no_such_contact"}
        from systems.proposals import propose_request
        return propose_request(c, contact, world, "give_me_a_ride",
                                situation="needs a ride", urgency=40)

    return {"ok": False, "reason": "invalid_method"}


def suggest_ride(offerer, world, target_id):
    """The other direction -- offerer proactively offers a ride. Reuses
    the same social_ask engine every other unprompted offer in this
    codebase goes through."""
    target = world.get("characters", {}).get(target_id)
    if not target:
        return {"ok": False, "reason": "no_such_target"}
    from systems.proposals import propose_social_ask
    return propose_social_ask(offerer, target, world, "offer_a_ride",
                               params={"text": "Why don't you let me give you a ride?"})


# ── Taxi vehicle dispatch ─────────────────────────────────────────────────

def _dispatch_taxi(c, world):
    traffic = world.get("traffic", {})
    entries = traffic.get("entry_points", []) or world.get("road_entry_points", [])
    if not entries:
        return {"ok": False, "reason": "no_road_network"}
    entry = entries[0]
    pickup = c["pickup_request"]["location"]

    vehicle = {
        "id":            str(uuid.uuid4()),
        "type":          "vehicle",
        "service_type":  "taxi",
        "vehicle_model": "taxi",
        "worker_model":  "taxi_driver",
        "x":             entry["x"],
        "y":             entry["y"],
        "route":         [],
        "state":         "driving_to_pickup",
        "speed":         TAXI_SPEED,
        "passenger_id":  c["id"],
        "pickup":        dict(pickup),
        "dropoff":       dict(c["pickup_request"]["destination"]) if c["pickup_request"]["destination"] else None,
    }
    road_target = nearest_road_tile(world, pickup["x"], pickup["y"])
    vehicle["route"] = find_road_path(world, (int(vehicle["x"]), int(vehicle["y"])), road_target) or []

    world.setdefault("rideshare_vehicles", []).append(vehicle)
    c["pickup_request"]["vehicle_id"] = vehicle["id"]
    return {"ok": True, "vehicle_id": vehicle["id"]}


def update_rideshare_vehicles(world):
    """Call on a fast-ish cadence (see sim_loop.py)."""
    for vehicle in list(world.get("rideshare_vehicles", [])):
        _update_vehicle(vehicle, world)


def _update_vehicle(vehicle, world):
    route = vehicle.get("route", [])
    if route:
        tx, ty = route[0]
        dx, dy = tx - vehicle["x"], ty - vehicle["y"]
        dist = (dx * dx + dy * dy) ** 0.5
        speed = vehicle.get("speed", TAXI_SPEED)
        if dist <= speed:
            vehicle["x"], vehicle["y"] = tx, ty
            route.pop(0)
        else:
            vehicle["x"] += dx / dist * speed
            vehicle["y"] += dy / dist * speed
        return

    state = vehicle["state"]
    passenger = world.get("characters", {}).get(vehicle.get("passenger_id"))

    if state == "driving_to_pickup":
        if passenger:
            passenger["x"] = vehicle["x"]
            passenger["y"] = vehicle["y"]
            req = passenger.setdefault("pickup_request", {})
            req["status"] = "in_transit"
            passenger["_in_vehicle"] = vehicle["id"]
        dropoff = vehicle.get("dropoff")
        if dropoff:
            road_target = nearest_road_tile(world, dropoff["x"], dropoff["y"])
            vehicle["route"] = find_road_path(world, (int(vehicle["x"]), int(vehicle["y"])), road_target) or []
            vehicle["state"] = "driving_to_dropoff"
        else:
            vehicle["state"] = "leaving"
            _route_to_exit(vehicle, world)
        return

    if state == "driving_to_dropoff":
        if passenger:
            dropoff = vehicle["dropoff"]
            passenger["x"] = dropoff["x"]
            passenger["y"] = dropoff["y"]
            passenger.setdefault("pickup_request", {})["status"] = "arrived"
            passenger.pop("_in_vehicle", None)
        vehicle["state"] = "leaving"
        _route_to_exit(vehicle, world)
        return

    if state == "leaving":
        vehicles = world.get("rideshare_vehicles", [])
        if vehicle in vehicles:
            vehicles.remove(vehicle)


def _route_to_exit(vehicle, world):
    traffic = world.get("traffic", {})
    exits = traffic.get("exit_points", []) or world.get("road_exit_points", [])
    if not exits:
        vehicle["route"] = []
        return
    exit_point = exits[0]
    vehicle["route"] = find_road_path(
        world, (int(vehicle["x"]), int(vehicle["y"])), (exit_point["x"], exit_point["y"])
    ) or []
