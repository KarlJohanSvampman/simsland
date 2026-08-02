"""
systems/transit.py

The public bus: a fixed 15-sim-minute schedule (see the "off-grid physical
travel" plan). One shared bus_a prop runs a single round trip per scheduled
slot -- it drives in from the nearest road entry point to the stop
(revealing any character whose errand already finished and who's been
waiting at the stop as "awaiting_bus_arrival"), then immediately turns
around and drives back out to the nearest exit point carrying anyone who
was "waiting_for_bus" (their off-grid errand clock only starts once the bus
has actually left the map -- same convention as the car in travel.py).

update_bus(world) must be called every tick (not on an every()-gated
cadence) -- the 15-minute boundary needs single-tick precision.
"""

from systems.vehicles import bus_stop
from systems.travel import (
    build_road_trip_path,
    step_vehicle_along_road,
    _nearest_point,
    _begin_walking_home,
)

BUS_INTERVAL_MINUTES = 15


def _get_or_create_bus(world):
    for p in world.get("props", []):
        if p.get("template") == "bus_a":
            return p
    stop = bus_stop(world)
    bus = {
        "id": "bus_1",
        "template": "bus_a",
        "x": stop["x"] if stop else 0,
        "y": stop["y"] if stop else 0,
        "rotation": 0,
        "household_id": None,
        "hidden": True,
        "state": {},
    }
    world["props"].append(bus)
    return bus


def _characters_in_state(world, state):
    return [c for c in world.get("characters", {}).values() if c.get("travel_state") == state]


def _dispatch_bus(world):
    from sim_loop import _mark_dirty

    bus = _get_or_create_bus(world)
    stop = bus_stop(world)
    if not stop:
        return

    entry_point = _nearest_point(world.get("road_entry_points"), (stop["x"], stop["y"]))
    if not entry_point:
        return

    # build_road_trip_path() expects (off-graph point) -> (on-graph point) --
    # the stop is off-graph (it's a sidewalk tile), the entry point is on
    # the road graph -- so build stop->entry and reverse it for the
    # entry->stop arrival leg (same trick travel.py uses for the car's
    # driving-back leg).
    arriving_path = list(reversed(
        build_road_trip_path(world, (stop["x"], stop["y"]), (entry_point["x"], entry_point["y"]))
    ))

    bus["hidden"] = False
    bus["x"], bus["y"] = arriving_path[0]
    bus["_path"] = arriving_path
    bus["_path_index"] = 0
    world["_bus"] = {"phase": "arriving"}
    _mark_dirty(world, prop_ids={bus["id"]})


def _handle_bus_arrival(world, bus):
    from sim_loop import _mark_dirty

    for c in _characters_in_state(world, "awaiting_bus_arrival"):
        c["travel_hidden"] = False
        c["x"], c["y"] = bus["x"], bus["y"]
        _begin_walking_home(c, world)
        _mark_dirty(world, char_ids={c["id"]})

    boarders = _characters_in_state(world, "waiting_for_bus")
    for c in boarders:
        c["riding_bus_id"] = bus["id"]
        c["travel_hidden"] = True
        c["travel_state"] = "on_bus_departing"
        _mark_dirty(world, char_ids={c["id"]})

    stop = bus_stop(world)
    exit_point = (
        _nearest_point(world.get("road_exit_points"), (stop["x"], stop["y"]))
        if stop else None
    )

    if not boarders or not exit_point:
        # Nobody boarding -- no need to keep driving. Park invisible at the
        # stop until the next scheduled dispatch.
        bus["hidden"] = True
        bus["_path"] = None
        bus["_path_index"] = 0
        world["_bus"] = {"phase": None}
        return

    bus["_path"] = build_road_trip_path(world, (bus["x"], bus["y"]), (exit_point["x"], exit_point["y"]))
    bus["_path_index"] = 0
    world["_bus"] = {"phase": "departing"}
    _mark_dirty(world, prop_ids={bus["id"]})


def _handle_bus_departure(world, bus):
    from sim_loop import _mark_dirty
    from systems.offgrid import _send_offgrid_immediate

    bus["hidden"] = True
    bus["_path"] = None
    bus["_path_index"] = 0
    _mark_dirty(world, prop_ids={bus["id"]})

    for c in world.get("characters", {}).values():
        if c.get("riding_bus_id") != bus["id"]:
            continue
        c["riding_bus_id"] = None
        c["travel_state"] = None
        pending = c.pop("_pending_offgrid", None)
        if pending:
            _send_offgrid_immediate(c, world, pending["reason"], pending["duration"])
        _mark_dirty(world, char_ids={c["id"]})

    world["_bus"] = {"phase": None}


def _step_active_bus_trip(world):
    from sim_loop import _mark_dirty

    bus_info = world.get("_bus")
    if not bus_info or not bus_info.get("phase"):
        return

    bus = _get_or_create_bus(world)
    if step_vehicle_along_road(bus, world):
        _mark_dirty(world, prop_ids={bus["id"]})
        return

    phase = bus_info["phase"]
    if phase == "arriving":
        _handle_bus_arrival(world, bus)
    elif phase == "departing":
        _handle_bus_departure(world, bus)


def update_bus(world):
    calendar = world.get("calendar", {})
    minute_of_day = calendar.get("minute_of_day")
    if minute_of_day is None:
        return

    _step_active_bus_trip(world)

    if minute_of_day % BUS_INTERVAL_MINUTES != 0:
        return
    if world.get("_last_bus_departure_minute") == minute_of_day:
        return
    world["_last_bus_departure_minute"] = minute_of_day

    if world.get("_bus", {}).get("phase"):
        return  # a trip from a previous slot is still in progress

    if not _characters_in_state(world, "waiting_for_bus") and \
       not _characters_in_state(world, "awaiting_bus_arrival"):
        return

    _dispatch_bus(world)
