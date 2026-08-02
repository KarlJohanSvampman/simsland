"""
systems/travel.py

Physical off-grid travel (see the "off-grid physical travel" plan): the car
departure/return state machine. Garage/car/bus-stop spawning lives in
vehicles.py; the bus schedule + bus state machine (Round 3) lives in
transit.py.

c["travel_state"] walks one of two paths:
    to_garage -> driving_out -> (off_grid, real errand clock running)
                 -> driving_back -> walking_home -> None
    to_bus_stop -> waiting_for_bus -> ... (picked up by transit.py)
"""

import random
from collections import deque

from systems.navigation import plan_character_route
from systems.vehicles import (
    household_car,
    household_garage,
    bus_stop,
    household_home_entrance,
)

# travel_state values where the character isn't walking a route and isn't
# yet off-grid -- agent_loop.py skips LLM/movement decisions entirely for
# these (movement never even runs), same as it does for off_grid itself.
TRAVEL_FROZEN_STATES = (
    "driving_out", "driving_back",
    "waiting_for_bus", "on_bus_departing", "awaiting_bus_arrival",
)

# travel_state values where the character IS walking a normal route (to the
# garage/bus stop/home) -- movement must still run for these, but the
# LLM/needs decision tail must not, even on the tick the route completes.
# Without this, the one tick where the route has just emptied (arrival) but
# update_travel() hasn't yet processed the handoff to the next travel_state
# is wide open for ordinary decision-making to reissue a brand new route,
# hijacking the trip before update_travel() ever sees the arrival.
TRAVEL_WALKING_STATES = ("to_garage", "to_bus_stop", "walking_home")

_CAR_PROBABILITY = 0.8


# =========================================================
# TRAVEL MODE
# =========================================================

def choose_travel_mode(c, world):
    car = household_car(world, c.get("household_id"))
    car_available = car is not None and not car.get("state", {}).get("in_use")
    if car_available and random.random() < _CAR_PROBABILITY:
        return "car"
    return "bus"


def _at_position(c, target, tolerance=0.6):
    return (
        abs(c.get("x", 0) - target["x"]) < tolerance
        and abs(c.get("y", 0) - target["y"]) < tolerance
    )


def _route_or_already_there(c, world, target):
    """plan_character_route() returns False when start == target -- zero
    tiles means zero segments, not a routing failure -- which would
    otherwise send an already-arrived character straight to the instant
    off-grid fallback below instead of starting their trip. True if c is
    already at target or a route was planned."""
    if _at_position(c, target):
        c["route"] = []
        return True
    return plan_character_route(world, c, target["x"], target["y"])


def begin_travel(c, world, reason, duration):
    from systems.offgrid import _send_offgrid_immediate

    # update_agent()'s "if c.get('activity'): execute_activity(...); return"
    # branch runs before movement -- a leftover activity (examining a prop,
    # a hobby step, ...) would otherwise block update_character_movement()
    # from ever processing the to_garage/to_bus_stop route at all. The trip
    # itself was already a prioritized decision (maybe_go_offgrid() et al.),
    # so it preempts whatever the character was idly doing.
    c["activity"] = None

    c["_pending_offgrid"] = {"reason": reason, "duration": duration}
    mode = choose_travel_mode(c, world)

    if mode == "car":
        garage = household_garage(world, c.get("household_id"))
        car = household_car(world, c.get("household_id"))
        if garage and car and _route_or_already_there(c, world, garage):
            # Claim the car now, at the decision, not later when the
            # character physically reaches the garage -- otherwise a
            # second household member deciding in the gap while the first
            # is still walking over would see car_available=True too, and
            # both would end up racing for the same car.
            car["state"]["in_use"] = True
            c["travel_mode"] = "car"
            c["travel_state"] = "to_garage"
            return True
    else:
        stop = bus_stop(world)
        if stop and _route_or_already_there(c, world, stop):
            c["travel_mode"] = "bus"
            c["travel_state"] = "to_bus_stop"
            return True

    # No usable garage/bus-stop route -- e.g. a household with no garage
    # (Round 5's fallback case). Skip the physical trip entirely.
    c.pop("_pending_offgrid", None)
    return _send_offgrid_immediate(c, world, reason, duration)


# =========================================================
# ROAD PATHING
# =========================================================

def plan_road_route(world, start_xy, target_xy):
    """BFS over world["road_graph"] (the live graph built by
    world_tiles.py::build_road_graph()) between two points that are each
    already road tiles. Returns a list of (x, y) tuples including both
    endpoints, or None if no path exists."""
    graph = world.get("road_graph") or {}

    start_node = f"{int(start_xy[0])},{int(start_xy[1])}"
    target_node = f"{int(target_xy[0])},{int(target_xy[1])}"

    if start_node not in graph or target_node not in graph:
        return None
    if start_node == target_node:
        return [(int(start_xy[0]), int(start_xy[1]))]

    came_from = {start_node: None}
    queue = deque([start_node])
    while queue:
        node = queue.popleft()
        if node == target_node:
            break
        for neighbor in graph.get(node, []):
            if neighbor in came_from:
                continue
            came_from[neighbor] = node
            queue.append(neighbor)

    if target_node not in came_from:
        return None

    path = []
    node = target_node
    while node is not None:
        x_str, y_str = node.split(",")
        path.append((int(x_str), int(y_str)))
        node = came_from[node]
    path.reverse()
    return path


def _nearest_road_node(world, xy):
    graph = world.get("road_graph") or {}
    if not graph:
        return None
    x, y = xy
    best_node, best_dist = None, None
    for node in graph:
        nx_str, ny_str = node.split(",")
        d = (int(nx_str) - x) ** 2 + (int(ny_str) - y) ** 2
        if best_dist is None or d < best_dist:
            best_dist, best_node = d, node
    return best_node


def _straight_line(from_xy, to_xy):
    """Orthogonal (horizontal-then-vertical) walk between two points --
    used only for the short garage/bus-stop <-> road on-ramp leg, not the
    long haul (plan_road_route's BFS handles that)."""
    fx, fy = int(from_xy[0]), int(from_xy[1])
    tx, ty = int(to_xy[0]), int(to_xy[1])
    path = [(fx, fy)]
    if tx != fx:
        step_x = 1 if tx > fx else -1
        for xx in range(fx + step_x, tx + step_x, step_x):
            path.append((xx, fy))
    if ty != fy:
        step_y = 1 if ty > fy else -1
        for yy in range(fy + step_y, ty + step_y, step_y):
            path.append((tx, yy))
    return path


def build_road_trip_path(world, from_xy, to_xy):
    """Full tile-by-tile path from an arbitrary point (a garage/bus-stop,
    not necessarily itself a road tile) to a target point that IS a road
    tile (a road exit point) -- a short local on-ramp walk to the nearest
    road_graph node, then a BFS road route the rest of the way."""
    on_ramp = _nearest_road_node(world, from_xy)
    if not on_ramp:
        return _straight_line(from_xy, to_xy)

    rx_str, ry_str = on_ramp.split(",")
    ramp_xy = (int(rx_str), int(ry_str))

    path = _straight_line(from_xy, ramp_xy)

    road_path = plan_road_route(world, ramp_xy, to_xy)
    if road_path:
        path.extend(road_path[1:])
    elif ramp_xy != (int(to_xy[0]), int(to_xy[1])):
        path.append((int(to_xy[0]), int(to_xy[1])))

    return path


def _mark_dirty_prop(world, prop_id):
    # Props are never swept by sim_loop.py's per-tick dirty collection (only
    # characters are, via _run_agent()'s return value) -- a moving vehicle
    # needs this called explicitly wherever its x/y/hidden/state changes.
    from sim_loop import _mark_dirty
    _mark_dirty(world, prop_ids={prop_id})


def _nearest_point(points, xy):
    if not points:
        return None
    x, y = xy
    return min(points, key=lambda p: (p["x"] - x) ** 2 + (p["y"] - y) ** 2)


def step_vehicle_along_road(prop, world):
    """Advances prop one tile along its precomputed prop["_path"]
    (prop["_path_index"] tracks progress). Returns True while still en
    route, False once the path is exhausted."""
    path = prop.get("_path")
    if not path:
        return False
    idx = prop.get("_path_index", 0)
    if idx >= len(path):
        prop["_path"] = None
        prop["_path_index"] = 0
        return False
    prop["x"], prop["y"] = path[idx]
    prop["_path_index"] = idx + 1
    if idx + 1 >= len(path):
        prop["_path"] = None
        prop["_path_index"] = 0
        return False
    return True


# =========================================================
# CAR STATE MACHINE
# =========================================================

def _start_driving_out(c, world):
    car = household_car(world, c.get("household_id"))
    garage = household_garage(world, c.get("household_id"))
    if not car or not garage:
        _abort_travel_to_immediate(c, world)
        return

    exit_point = _nearest_point(world.get("road_exit_points"), (garage["x"], garage["y"]))
    if not exit_point:
        _abort_travel_to_immediate(c, world)
        return

    car["state"]["in_use"] = True
    car["_path"] = build_road_trip_path(
        world, (garage["x"], garage["y"]), (exit_point["x"], exit_point["y"])
    )
    car["_path_index"] = 0

    c["travel_hidden"] = True
    c["travel_state"] = "driving_out"
    _mark_dirty_prop(world, car["id"])


def _finish_driving_out(c, world, car):
    if car:
        car["hidden"] = True
        _mark_dirty_prop(world, car["id"])
    c["travel_state"] = None
    pending = c.pop("_pending_offgrid", None)
    if pending:
        from systems.offgrid import _send_offgrid_immediate
        _send_offgrid_immediate(c, world, pending["reason"], pending["duration"])


def _start_driving_back(c, world):
    car = household_car(world, c.get("household_id"))
    garage = household_garage(world, c.get("household_id"))
    if not car or not garage:
        _finish_travel(c, world)
        return

    car["hidden"] = False
    forward_path = build_road_trip_path(
        world, (garage["x"], garage["y"]), (car["x"], car["y"])
    )
    car["_path"] = list(reversed(forward_path))
    car["_path_index"] = 0
    c["travel_state"] = "driving_back"
    _mark_dirty_prop(world, car["id"])


def _finish_driving_back(c, world, car):
    if car:
        car["hidden"] = True
        car["state"]["in_use"] = False
        car["_path"] = None
        car["_path_index"] = 0
        c["x"], c["y"] = car["x"], car["y"]
        _mark_dirty_prop(world, car["id"])
    c["travel_hidden"] = False
    _begin_walking_home(c, world)


def _abort_travel_to_immediate(c, world):
    # Release the car claimed at begin_travel()'s decision point -- this
    # only fires from _start_driving_out()'s defensive guard (garage/car/
    # exit-point vanished between decision and arrival), so the car really
    # was reserved for this trip and would otherwise stay locked with no
    # one ever driving it.
    if c.get("travel_mode") == "car":
        car = household_car(world, c.get("household_id"))
        if car:
            car["state"]["in_use"] = False

    c["travel_state"] = None
    c["travel_mode"] = None
    c["travel_hidden"] = False
    pending = c.pop("_pending_offgrid", None)
    if pending:
        from systems.offgrid import _send_offgrid_immediate
        _send_offgrid_immediate(c, world, pending["reason"], pending["duration"])


# =========================================================
# WALKING HOME (shared tail for car + bus, Round 3)
# =========================================================

def _begin_walking_home(c, world):
    """Routes c home from wherever c["x"]/c["y"] currently is -- the caller
    is responsible for having already placed the character there (at the
    garage, or at the bus stop -- see transit.py)."""
    entrance = household_home_entrance(world, c.get("household_id"))
    if entrance and plan_character_route(world, c, entrance[0], entrance[1]):
        c["travel_state"] = "walking_home"
    else:
        _finish_travel(c, world)


def _finish_travel(c, world):
    c["travel_state"] = None
    c["travel_mode"] = None
    c["travel_hidden"] = False


# =========================================================
# MAIN UPDATE
# =========================================================

def update_travel(c, world):
    state = c.get("travel_state")

    if state == "to_garage":
        if not c.get("route"):
            _start_driving_out(c, world)

    elif state == "to_bus_stop":
        if not c.get("route"):
            c["travel_state"] = "waiting_for_bus"

    elif state == "driving_out":
        car = household_car(world, c.get("household_id"))
        if not car or not step_vehicle_along_road(car, world):
            _finish_driving_out(c, world, car)
        else:
            _mark_dirty_prop(world, car["id"])

    elif state == "driving_back":
        car = household_car(world, c.get("household_id"))
        if not car or not step_vehicle_along_road(car, world):
            _finish_driving_back(c, world, car)
        else:
            _mark_dirty_prop(world, car["id"])

    elif state == "walking_home":
        if not c.get("route"):
            _finish_travel(c, world)
