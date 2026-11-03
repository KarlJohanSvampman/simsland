"""
systems/step_timeouts.py

Every step a character is in -- an activity phase, a walk, a leg of a trip -- has a timeout event. Nothing polls for
"stuck": the timeout is scheduled when the step starts (core/scheduler.py, owner "stuck:<id>"), and when it fires it
looks at whether the step moved on. If it did, the timeout is simply re-armed from the progress; if it didn't, the
character is reported stuck and taken out of the step.

How long a step gets:

  - a step that should be short (a walk, a non-"using" activity phase, a "using" phase with no length):
    STALL_TICKS (3 sim-minutes) after the last sign of progress -- for a walk, getting half a tile further;
  - a step with a known length (an activity's "using" phase, waiting for the 15-minute bus, a drive):
    that length, then STALL_TICKS more;
  - a walk that keeps moving but never arrives (going round in circles): WALK_MAX_TICKS in total.

Being stuck is reported (container log and the character's memory log) and undone the way that step needs:

  - an activity: interrupted (prop anchor and posture released), movement cleared, the character woken with
    `activity_aborted` to choose again;
  - a trip's walk (to the garage, to the bus stop, home): first one fresh route; still stuck after that, the walk is
    given up (an outbound trip happens without it, a walk home just ends);
  - waiting for / riding the bus, a drive: the leg is finished as it would have finished (off-grid for an outbound
    trip, walking home from the stop or the garage for a return).

Sleep is left to fatigue and alarms. A leftover of the retired at-home "work" action times out at once.

note_step(c, world) is the hook that arms it: agent_loop.update_agent calls it each tick, and it only reschedules
when the step itself changes (progress inside a step is just noted on the character for the timeout to read).
"""

import math

from core import scheduler

STALL_TICKS = 180            # 3 sim-minutes without anything happening
WALK_MAX_TICKS = 900         # no walk takes more than 15 sim-minutes, moving or not
PROGRESS_DISTANCE = 0.5      # tiles: a walk that got this much further made progress
EXEMPT_TYPES = {"sleep"}

OWNER = "stuck"

# How long each leg of a trip is expected to take (before the STALL_TICKS on top).
_BUS_WAIT = 15 * 60 + 300    # the bus comes every 15 minutes and takes up to its stall timeout to arrive
_LEG_TICKS = {
    "waiting_for_bus": _BUS_WAIT,
    "awaiting_bus_arrival": _BUS_WAIT,
    "on_bus_departing": 300,
    "on_bus_returning": 300,
    "driving_out": 300,
    "driving_back": 300,
}


def _owner(c):
    return f"{OWNER}:{c['id']}"


def current_step(c, world):
    """(signature, kind, length) of what c is doing now, or None if nothing that can get stuck.

    kind: "timed"  -- done by start + length (+ STALL_TICKS)
          "walk"   -- STALL_TICKS from the last progress, and never past start + WALK_MAX_TICKS
          "stall"  -- STALL_TICKS from the last progress
    """
    if c.get("off_grid") or c.get("alive") is False:
        return None
    from systems.travel import TRAVEL_WALKING_STATES

    state = c.get("travel_state")
    if state in TRAVEL_WALKING_STATES:
        return ["travel", state], "walk", None
    if state in _LEG_TICKS:
        return ["travel", state], "timed", _LEG_TICKS[state]

    act = c.get("activity")
    if act and act.get("type"):
        act_type = act["type"]
        if act_type in EXEMPT_TYPES:
            return None
        phase = act.get("phase", "using")
        sig = ["activity", act_type, act.get("target_id"), phase, act.get("phase_started_tick")]
        if act_type == "work":                       # the retired at-home "work" action
            return sig, "timed", -STALL_TICKS
        if phase == "walking" or c.get("is_moving"):
            return sig, "walk", None
        duration = act.get("duration")
        if phase == "using" and isinstance(duration, (int, float)) and duration > 0:
            return sig, "timed", int(duration)
        return sig, "stall", None

    if c.get("is_moving"):
        target = c.get("move_target")
        return ["move", list(target) if isinstance(target, (list, tuple)) else target], "walk", None
    return None


def deadline(st):
    if st["kind"] == "timed":
        return st["start"] + st["length"] + STALL_TICKS
    due = st["progress"] + STALL_TICKS
    if st["kind"] == "walk":
        due = min(due, st["start"] + WALK_MAX_TICKS)
    return due


def _arm(c, world, st):
    scheduler.schedule(world, _owner(c), "step", max(deadline(st), world.get("tick", 0)), {"sig": st["sig"]})


def progress(c, world):
    """Something happened in c's current step (a line of a conversation, a turn in a queue): push its timeout back."""
    st = c.get("_step")
    if st:
        st["progress"] = world.get("tick", 0)


def note_step(c, world):
    """Arm (or re-arm, or drop) c's step timeout. Cheap: reschedules only when the step itself changes."""
    tick = world.get("tick", 0)
    step = current_step(c, world)
    st = c.get("_step")
    if step is None:
        if st:
            scheduler.cancel(world, _owner(c), "step")
            c.pop("_step", None)
        return
    sig, kind, length = step
    pos = [c.get("x", 0), c.get("y", 0)]
    if not st or st.get("sig") != sig:
        start = tick
        if sig[0] == "activity" and isinstance(sig[4], (int, float)):
            start = min(tick, int(sig[4]))
        c["_step"] = st = {"sig": sig, "kind": kind, "length": length, "start": start,
                           "progress": tick, "pos": pos, "tries": 0}
        _arm(c, world, st)
        return
    if math.hypot(pos[0] - st["pos"][0], pos[1] - st["pos"][1]) >= PROGRESS_DISTANCE:
        st["pos"] = pos
        st["progress"] = tick


def _find(world, owner):
    cid = owner.split(":", 1)[1]
    chars = world.get("characters") or {}
    c = chars.get(cid)
    if c is None and cid.lstrip("-").isdigit():
        c = chars.get(int(cid))
    return c


def on_timeout(world, entry):
    c = _find(world, entry["owner"])
    if c is None:
        return
    st = c.get("_step")
    if not st or st.get("sig") != (entry.get("payload") or {}).get("sig"):
        return                                       # a timeout for a step that is already over
    note_step(c, world)                              # catch the latest progress (or a step that just changed)
    st = c.get("_step")
    if not st or st.get("sig") != entry["payload"]["sig"]:
        return
    if deadline(st) > world.get("tick", 0):
        _arm(c, world, st)                           # something happened since: wait from there
        return
    unstick(c, world, st)


# =========================================================
# GETTING UNSTUCK
# =========================================================

def _report(c, world, st, what, outcome):
    from brain.memory import store_memory
    tick = world.get("tick", 0)
    idle = tick - max(st["start"], st["progress"]) if st["kind"] != "timed" else tick - st["start"]
    print(f"[stuck] tick {tick}: {c.get('name', c.get('id'))} stuck in {what} "
          f"({' / '.join(str(s) for s in st['sig'][1:] if s is not None)}, {idle} ticks without progress) -- {outcome}")
    store_memory(c, f"I got stuck {what} and {outcome}.", importance=0.3, tags=["stuck", "gave_up"], tick=tick,
                 source="internal")


def unstick(c, world, st):
    kind = st["sig"][0]
    c.pop("_step", None)
    scheduler.cancel(world, _owner(c), "step")
    if kind == "travel":
        _unstick_trip(c, world, st)
    elif kind == "activity":
        _unstick_activity(c, world, st)
    else:
        _report(c, world, st, "walking somewhere", "stopped trying to get there")
        _stop_moving(c)
        from brain.cognition_scheduler import wake_character
        wake_character(c, world, "activity_aborted", {"activity": "move", "target_id": None, "phase": "walking"})
    note_step(c, world)


def _stop_moving(c):
    c["is_moving"] = False
    c["move_target"] = None
    c["route"] = []
    c["animation_state"] = "idle"


def _unstick_activity(c, world, st):
    from systems.occupancy import interrupt_activity
    from brain.cognition_scheduler import wake_character
    act = c.get("activity") or {}
    act_type, target, phase = act.get("type"), act.get("target_id"), act.get("phase", "using")
    label = str(act_type).replace("_", " ")
    if act_type == "work" and not c.get("off_grid"):
        print(f"[stuck] {c.get('name', c.get('id'))}: the at-home \"work\" action no longer exists -- ending it")
        interrupt_activity(c, world, reason="the at-home \"work\" action no longer exists")
    else:
        _report(c, world, st, f"{'getting to ' if phase == 'walking' else ''}{label}", "gave up on it for now")
        interrupt_activity(c, world, reason=f"stuck in the {phase} phase", outcome="timed_out")
    _stop_moving(c)
    wake_character(c, world, "activity_aborted", {"activity": act_type, "target_id": target, "phase": phase})


def _unstick_trip(c, world, st):
    from systems import travel
    from systems.vehicles import bus_stop
    state = st["sig"][1]
    if c.get("travel_state") != state:
        return
    where = {"to_garage": "walking to the car", "to_bus_stop": "walking to the bus stop",
             "walking_home": "walking home", "waiting_for_bus": "waiting for the bus",
             "awaiting_bus_arrival": "waiting for the bus home", "on_bus_departing": "on the bus",
             "on_bus_returning": "on the bus home", "driving_out": "driving off", "driving_back": "driving home"}[state]

    if state in travel.TRAVEL_WALKING_STATES:
        target = travel._walk_target(c, world, state)
        if st["tries"] == 0 and target and travel.plan_character_route(world, c, target[0], target[1]):
            travel._set_off(c)
            _report(c, world, st, where, "set off again on a fresh route")
            tick = world.get("tick", 0)
            c["_step"] = new = dict(st, progress=tick, start=tick, tries=1, pos=[c.get("x", 0), c.get("y", 0)])
            _arm(c, world, new)
            return
        _report(c, world, st, where, "gave up on the walk" if state != "walking_home" else "stopped where I was")
        travel._give_up_walk(c, world, state)
        return

    _report(c, world, st, where, "got there another way")
    car = travel.household_car(world, c.get("household_id"))
    if state == "driving_out":
        travel._finish_driving_out(c, world, car)
    elif state == "driving_back":
        travel._finish_driving_back(c, world, car)
    elif state in ("waiting_for_bus", "on_bus_departing"):
        c["riding_bus_id"] = None
        travel._abort_travel_to_immediate(c, world)
    else:                                            # awaiting_bus_arrival, on_bus_returning
        c["riding_bus_id"] = None
        c["travel_hidden"] = False
        stop = bus_stop(world)
        if stop and state == "on_bus_returning":
            c["x"], c["y"] = stop["x"], stop["y"]
        travel._begin_walking_home(c, world)


scheduler.register(OWNER, on_timeout)
