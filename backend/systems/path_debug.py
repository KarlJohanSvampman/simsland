"""
systems/path_debug.py

What path a character planned, and making a failure to find one impossible to miss.

Every route plan (systems/navigation.py::plan_character_route) is recorded on the character:

    c["path_plans"] = [ {"tick", "from": [x, y], "to": [x, y], "ok", "reason", "tiles", "segments": [...],
                         "target_id"}, ... ]                                   # the last MAX_PLANS

    reason: ok | partial_stops_outside (the walk ends at the door of the target building) | already_there |
            no_indoor_path | no_outdoor_path | start_building_has_no_entrance | target_building_has_no_entrance |
            no_route

The planned route itself is c["route"] (its tiles), which the viewer draws for the selected character; the
Inspector's Movement tab lists the recent plans.

A real failure to find a way (not "already there", and not a plan made only to test a spot -- see probing()) puts the
character into a short psychotic episode, as asked: they lose their bearings out loud ("I can't find the way... where
am I?"), it's in their memory and the container log ("[path] NO PATH ..."), and c["psychosis_state"] is active for
EPISODE_TICKS -- so it shows up. At most once per COOLDOWN_TICKS per character.
"""

from contextlib import contextmanager

from core import scheduler

MAX_PLANS = 10
EPISODE_TICKS = 600             # 10 sim-minutes
COOLDOWN_TICKS = 1800
OWNER = "pathalarm"
NOT_A_FAILURE = {"ok", "partial_stops_outside", "already_there"}

_probing = 0


@contextmanager
def probing():
    """Plans made inside this only test whether a spot can be reached (picking a random room to roam to, say): a
    failure there is an answer, not something going wrong."""
    global _probing
    _probing += 1
    try:
        yield
    finally:
        _probing -= 1


def record(c, world, target, ok, reason):
    if c.get("is_workplace_npc"):
        return
    tick = world.get("tick", 0)
    route = (c.get("route") or []) if ok else []
    entry = {
        "tick": tick,
        "from": [round(c.get("x", 0), 1), round(c.get("y", 0), 1)],
        "to": [round(target[0], 1), round(target[1], 1)],
        "ok": bool(ok), "reason": reason,
        "tiles": sum(len(seg.get("tiles") or []) for seg in route),
        "segments": [seg.get("type") for seg in route],
        "target_id": (c.get("move_target") or {}).get("target_id") or (c.get("activity") or {}).get("target_id"),
        "probe": bool(_probing),
    }
    if _probing and not ok:
        return                                        # a probe that found nothing isn't worth keeping
    plans = c.setdefault("path_plans", [])
    plans.append(entry)
    del plans[:-MAX_PLANS]
    if not ok and reason not in NOT_A_FAILURE and not _probing:
        _lost(c, world, entry)


def _lost(c, world, entry):
    from brain.memory import store_memory
    from systems.incidental_speech import fire_incidental
    tick = world.get("tick", 0)
    print(f"[path] NO PATH tick {tick}: {c.get('name', c.get('id'))} from {entry['from']} to {entry['to']} "
          f"({entry['reason']}, target {entry['target_id']})", flush=True)
    if tick - (c.get("_lost_tick") or -10**9) < COOLDOWN_TICKS:
        return
    c["_lost_tick"] = tick
    state = c.setdefault("psychosis_state", {})
    state.update(active=True, intensity=0.6, trigger="no_path", started_tick=tick, _duration=EPISODE_TICKS,
                 detail=f"couldn't find a way from {entry['from']} to {entry['to']} ({entry['reason']})")
    fire_incidental(c, "announce", "I... I can't find the way. Where am I? Where was I going?", world)
    store_memory(c, f"Everything went strange -- I couldn't find any way to where I was going "
                    f"({entry['reason'].replace('_', ' ')}). I didn't know where I was.",
                 importance=0.6, tags=["psychosis", "lost", "no_path"], tick=tick, source="internal")
    scheduler.schedule_in(world, f"{OWNER}:{c['id']}", "over", EPISODE_TICKS)


def _over(world, entry):
    cid = entry["owner"].split(":", 1)[1]
    c = (world.get("characters") or {}).get(cid)
    if not c:
        return
    state = c.get("psychosis_state") or {}
    if state.get("trigger") == "no_path":
        state.update(active=False, intensity=0.0, trigger=None, _duration=None)


scheduler.register(OWNER, _over)
