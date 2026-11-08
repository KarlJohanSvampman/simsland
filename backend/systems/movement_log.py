"""
systems/movement_log.py

How far each character actually moves while they're supposed to be moving -- the record that shows how often, and
where, they get stuck.

Every SAMPLE_TICKS (15 sim-seconds), for each character that is on the move -- walking a route, in the walking phase
of an activity, or on a walking leg of a trip -- or was at the last sample: how far they got since the last sample.
A sample taken while moving that covered less than STUCK_DISTANCE counts as stuck. Alongside, the activity events on
the same time axis: start, end (with how it ended) and timeout.

    c["move_log"] = {
        "samples": [[tick, distance, moving], ...],        # the last MAX_SAMPLES (two hours)
        "events":  [[tick, kind, label], ...],             # kind: start | end | timeout; the last MAX_EVENTS
        "stuck_samples": n, "moving_samples": n,           # totals since the log began
        "last": [x, y, tick, moving, activity key],
    }

The Inspector's "Movement" tab draws it as a line graph (frontend/src/movementLog.js). A recurring timer drives the
sampling (core/scheduler.py, owner "movelog"); the events come from systems/activity_trace.py and
systems/step_timeouts.py.
"""

import math

from core import scheduler

SAMPLE_TICKS = 15
STUCK_DISTANCE = 0.5
MAX_SAMPLES = 480                # two hours of samples
MAX_EVENTS = 200


def _log(c):
    return c.setdefault("move_log", {"samples": [], "events": [], "stuck_samples": 0, "moving_samples": 0,
                                     "last": None})


def _on_the_move(c):
    from systems.travel import TRAVEL_WALKING_STATES
    act = c.get("activity") or {}
    return bool(c.get("is_moving") or act.get("phase") == "walking"
                or c.get("travel_state") in TRAVEL_WALKING_STATES)


def _activity_key(c):
    act = c.get("activity") or {}
    if not act.get("type"):
        return None
    return f"{act.get('type')}:{act.get('started_tick', act.get('phase_started_tick'))}"


def note_event(c, world, kind, label):
    if c.get("is_workplace_npc"):
        return
    log = _log(c)
    tick = world.get("tick", 0)
    events = log["events"]
    if events and events[-1][1] == kind and events[-1][2] == label and tick - events[-1][0] < SAMPLE_TICKS:
        return                                       # the same event, reported twice
    events.append([tick, kind, str(label)[:60]])
    del events[:-MAX_EVENTS]


def sample(c, world):
    if c.get("is_workplace_npc") or c.get("off_grid") or c.get("x") is None:
        return
    log = _log(c)
    tick = world.get("tick", 0)
    moving = _on_the_move(c)
    key = _activity_key(c)
    last = log.get("last")
    if last:
        if last[4] != key:                            # an activity started or ended between samples, unreported
            if last[4] and not any(e[0] >= last[2] and e[1] in ("end", "timeout") for e in log["events"]):
                note_event(c, world, "end", last[4].split(":", 1)[0])
            if key and not any(e[0] >= last[2] and e[1] == "start" for e in log["events"]):
                note_event(c, world, "start", key.split(":", 1)[0])
        if moving or last[3]:
            dist = math.hypot(c["x"] - last[0], c["y"] - last[1])
            log["samples"].append([tick, round(dist, 2), bool(moving)])
            del log["samples"][:-MAX_SAMPLES]
            if moving and last[3]:
                log["moving_samples"] += 1
                if dist < STUCK_DISTANCE:
                    log["stuck_samples"] += 1
    log["last"] = [c["x"], c["y"], tick, bool(moving), key]


def _job(world, entry):
    for c in (world.get("characters") or {}).values():
        try:
            sample(c, world)
        except Exception as exc:                     # noqa: BLE001 -- logging must never break the tick
            print(f"[movelog] {c.get('id')}: {exc!r}")


# (scheduled from core/flow.py)
