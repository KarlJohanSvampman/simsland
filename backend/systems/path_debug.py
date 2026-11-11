"""
systems/path_debug.py

What path a character planned, and making a failure to find one impossible to miss.

Every route plan (systems/navigation.py::plan_character_route) is recorded on the character:

    c["path_plans"] = [ {"tick", "from": [x, y], "to": [x, y], "ok", "reason", "tiles", "segments": [...],
                         "target_id",
                         "target": {"kind", "id", "label", "x", "y"},          # what the walk is for, resolved
                         "path": [[x, y], ...],                                # the planned route, simplified
                         "eta_s",                                              # tiles / walking speed (sim seconds)
                         "candidates": [{"prop_id", "label", "x", "y", "score", "skipped"}],   # if a place was chosen
                         "ended", "actual_s"}, ... ]                           # arrived | stuck | replanned | stopped
                                                                               # -- the last MAX_PLANS

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


CANDIDATES_KEPT = 8
PATH_POINTS = 80


def note_candidates(c, world, interaction, chosen, mode, household_id=None, exclude_anchor=None):
    """After an anchor search (systems/props.py): every anchor for `interaction`, its score (walking distance, lower
    wins) and why it was passed over, if it was -- kept on the character for the next route plan."""
    from systems.anchors import get_world_anchor
    chosen_prop = chosen[0] if chosen else None
    rows = []
    for prop in world.get("props") or []:
        for anchor in prop.get("anchors") or []:
            if anchor.get("interaction") != interaction:
                continue
            skipped = None
            if mode == "household" and prop.get("household_id") and prop.get("household_id") != household_id:
                skipped = "another household's"
            elif mode in ("free", "household") and anchor.get("occupied_by") and anchor["occupied_by"] != c.get("id"):
                skipped = "in use"
            elif mode == "free" and anchor is exclude_anchor:
                skipped = "the one already tried"
            wa = get_world_anchor(prop, anchor)
            rows.append({"prop_id": prop.get("id"), "label": str(prop.get("template") or "prop").replace("_", " "),
                         "x": round(wa["x"], 1), "y": round(wa["y"], 1),
                         "score": round(abs(wa["x"] - c.get("x", 0)) + abs(wa["y"] - c.get("y", 0)), 1),
                         "skipped": skipped, "chosen": prop is chosen_prop and not skipped})
    rows.sort(key=lambda r: (not r["chosen"], r["skipped"] is not None, r["score"]))
    c["_nav_candidates"] = {"tick": world.get("tick", 0), "interaction": interaction, "rows": rows[:CANDIDATES_KEPT]}


def _target(c, world, target):
    """What the walk is for: a person, a prop, a room, a building -- with a label -- or just a spot."""
    mt = c.get("move_target") or {}
    tid = mt.get("target_id") or (c.get("activity") or {}).get("target_id")
    kind = mt.get("target_type")
    label = None
    chars = world.get("characters") or {}
    if tid in chars:
        kind, label = "person", chars[tid].get("name") or tid
    elif isinstance(tid, str) and tid.startswith("room:"):
        kind, label = "room", tid.split(":")[-1].replace("_", " ")
    elif kind == "building" or (isinstance(tid, str) and tid.startswith(("building:", "home:"))):
        kind, label = "building", tid
    elif tid:
        prop = next((p for p in world.get("props") or [] if p.get("id") == tid), None)
        if prop:
            kind, label = "prop", str(prop.get("template") or tid).replace("_", " ")
    return {"kind": kind or ("spot" if not tid else "thing"), "id": tid, "label": label or (tid or "a spot"),
            "x": round(target[0], 1), "y": round(target[1], 1)}


def _simplified_path(c):
    pts = [[round(c.get("x", 0), 1), round(c.get("y", 0), 1)]]
    for seg in c.get("route") or []:
        pts.extend([[t[0], t[1]] for t in (seg.get("tiles") or [])])
    if len(pts) > PATH_POINTS:                        # keep the shape: every n-th point, and the last
        step = len(pts) / PATH_POINTS
        pts = [pts[int(i * step)] for i in range(PATH_POINTS)] + [pts[-1]]
    return pts


def finish(c, world, how):
    """The walk the last plan was for has ended: arrived | stuck | replanned | stopped (how long it actually took)."""
    plans = c.get("path_plans") or []
    p = plans[-1] if plans else None
    if not p or p.get("ended") or not p.get("ok"):
        return
    p["ended"] = how
    p["actual_s"] = world.get("tick", 0) - p.get("tick", 0)


def record(c, world, target, ok, reason):
    if c.get("is_workplace_npc"):
        return
    tick = world.get("tick", 0)
    finish(c, world, "replanned")                     # a new plan while the last one was still being walked
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
        "target": _target(c, world, target),
    }
    if ok:
        entry["path"] = _simplified_path(c)
        try:
            from systems.movement import tiles_per_tick
            speed = max(1e-3, float(tiles_per_tick(c, world) or 1))      # tiles per tick (a tick is a sim second)
            entry["eta_s"] = max(1, round(entry["tiles"] / speed))
        except Exception:                             # noqa: BLE001
            pass
    nc = c.get("_nav_candidates")
    if nc and tick - nc.get("tick", -10) <= 2:        # chosen just now: what was in the running
        entry["candidates"] = nc["rows"]
        entry["interaction"] = nc.get("interaction")
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
