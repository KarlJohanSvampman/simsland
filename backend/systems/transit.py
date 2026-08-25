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

# Defensive: a normal round trip takes nowhere near this many ticks (garage
# tests in the car system completed similar-length trips in well under 50
# ticks). If a trip somehow stalls -- e.g. a corrupted/interrupted path
# from an external world edit -- force it to resolve rather than leaving
# the bus permanently stuck wherever it happens to be, mirroring
# movement.py's _stuck_ticks pattern for character route-walking.
BUS_STALL_TIMEOUT_TICKS = 300


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
    world["_bus"] = {"phase": "arriving", "started_tick": world.get("tick", 0)}
    _mark_dirty(world, prop_ids={bus["id"]})


def _handle_bus_arrival(world, bus):
    from sim_loop import _mark_dirty

    # Characters here are already visible and standing at the stop (see
    # offgrid.py's process_return -- reveals them there the moment their
    # errand ends, rather than staying hidden through the whole wait).
    # Boarding hides them again, mirroring the outbound "waiting_for_bus"
    # -> "on_bus_departing" transition below; _handle_bus_departure()
    # reveals them again once the bus completes this stop and they're
    # walked the rest of the way home.
    for c in _characters_in_state(world, "awaiting_bus_arrival"):
        c["riding_bus_id"] = bus["id"]
        c["travel_hidden"] = True
        c["travel_state"] = "on_bus_returning"
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

    if not exit_point:
        # No exit point to route to at all -- genuinely can't build a
        # departure path (missing road data). Park invisible at the stop
        # until the next scheduled dispatch. Unlike "nobody boarded", this
        # is a real defensive bail, not a normal empty-bus run.
        bus["hidden"] = True
        bus["_path"] = None
        bus["_path_index"] = 0
        world["_bus"] = {"phase": None}
        return

    # The bus runs its full round trip on schedule regardless of
    # passengers -- an ambient service, not something that only exists
    # when someone happens to be waiting.
    bus["_path"] = build_road_trip_path(world, (bus["x"], bus["y"]), (exit_point["x"], exit_point["y"]))
    bus["_path_index"] = 0
    world["_bus"] = {"phase": "departing", "started_tick": world.get("tick", 0)}
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
        returning = c.get("travel_state") == "on_bus_returning"
        c["riding_bus_id"] = None
        c["travel_state"] = None
        pending = c.pop("_pending_offgrid", None)
        if pending:
            _send_offgrid_immediate(c, world, pending["reason"], pending["duration"])
        elif returning:
            # Bus has done its stop; last stretch home is visible, same
            # as the outbound leg's initial walk to the stop was.
            c["travel_hidden"] = False
            _begin_walking_home(c, world)
        _mark_dirty(world, char_ids={c["id"]})

    world["_bus"] = {"phase": None}


def _force_resolve_stalled_bus(world, bus):
    """A trip that's been running far longer than any real one should --
    force it to a clean, hidden, idle state instead of leaving the bus
    permanently parked wherever it stalled. Doesn't try to gracefully
    finish out passenger handling (a stall this long means something's
    already wrong); riders just get released from the bus like a normal
    departure completion would, so they aren't left in limbo either."""
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
        c["travel_hidden"] = False
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

    started = bus_info.get("started_tick")
    if started is not None and world.get("tick", 0) - started > BUS_STALL_TIMEOUT_TICKS:
        _force_resolve_stalled_bus(world, bus)
        return

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

    # No passenger gate -- the bus runs on its own 15-minute schedule
    # unconditionally, same as a real public transit line.
    _dispatch_bus(world)
