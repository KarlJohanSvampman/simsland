"""
/admin/debugdraw/{char_id} -- everything VR Debug Draw (frontend/src/vrDebugDraw.js) draws for a character, in one read:

    navigation   where they stand; the route they are walking now (what is left of it), what it is for (the target:
                 a person, prop, room, building or spot -- with coordinates), how long it should take and how long it
                 has taken; their recent plans (systems/path_debug.py) with the places that were in the running and
                 their scores, planned vs actual time, and how each walk ended
    perception   vision, detection and hearing ranges; who they see (where, how far, how well); what they hear (where,
                 how loud, how clearly -- speech placed at the speaker); who is in range but hidden behind a wall
                 (line of sight), who is within hearing range but silent; where others were last seen (and how long ago)

Coordinates are world tiles (x, y); the viewer draws them at (x - 10, y - 7) like everything else.
"""

from fastapi import APIRouter, HTTPException

from db import load_world

router = APIRouter(prefix="/admin/debugdraw", tags=["debugdraw"])


def _remaining_route(c):
    pts = [[round(c.get("x", 0), 2), round(c.get("y", 0), 2)]]
    route = c.get("route") or []
    seg_i = c.get("route_segment_index") or 0
    for s in range(seg_i, len(route)):
        tiles = route[s].get("tiles") or []
        start = (c.get("path_index") or 0) if s == seg_i else 0
        pts.extend([[t[0], t[1]] for t in tiles[start:]])
    return pts


@router.get("/{char_id}")
def debug_draw(char_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    chars = world.get("characters") or {}
    c = chars.get(char_id)
    if not c:
        raise HTTPException(404, f"no character '{char_id}'")
    tick = world.get("tick", 0)
    from systems.path_debug import _target
    from systems.movement import tiles_per_tick
    from brain import perception as pc

    plans = c.get("path_plans") or []
    last = plans[-1] if plans else None
    route = _remaining_route(c) if c.get("is_moving") else []
    speed = max(1e-3, float(tiles_per_tick(c, world) or 1))
    mt = c.get("move_target") or {}
    now = None
    if route and len(route) > 1:
        now = {"path": route, "target": _target(c, world, (mt.get("x", route[-1][0]), mt.get("y", route[-1][1]))),
               "left_s": round((len(route) - 1) / speed), "since_s": tick - last["tick"] if last else None,
               "eta_s": last.get("eta_s") if last else None}

    per = c.get("perception") or {}
    seen = []
    for v in per.get("visible_people") or []:
        o = chars.get(v.get("id"))
        if o and o.get("x") is not None:
            seen.append({"id": v["id"], "name": v.get("name"), "x": o["x"], "y": o["y"], "distance": v.get("distance"),
                         "visibility": v.get("visibility")})
    heard = []
    for a in per.get("audible_events") or []:
        x, y, who = a.get("x"), a.get("y"), a.get("debug_from") or a.get("source_id")
        if who in chars:                                   # speech: where the speaker is now
            x, y = chars[who].get("x"), chars[who].get("y")
        if x is None:
            continue
        what = a.get("sound") or (f"{a.get('speaker') or 'someone'} talking" if a.get("type") == "speech" else "a sound")
        heard.append({"x": x, "y": y, "volume": a.get("volume"), "clarity": a.get("clarity"),
                      "distance": a.get("distance"), "what": what, "id": who if who in chars else None,
                      "knows_who": bool(a.get("source_id") or a.get("speaker"))})
    heard_ids = {h["id"] for h in heard if h["id"]}
    vr, hr = pc.visual_range(c, world), pc.hearing_range(c)
    seen_ids = {s["id"] for s in seen}
    hidden, unheard = [], []
    for oid, o in chars.items():
        if oid == char_id or o.get("alive") is False or o.get("off_grid") or o.get("x") is None:
            continue
        d = abs(o["x"] - c["x"]) + abs(o["y"] - c["y"])
        if d <= vr and oid not in seen_ids:
            hidden.append({"id": oid, "name": o.get("name"), "x": o["x"], "y": o["y"], "distance": round(d, 1),
                           "blocked": bool(pc.walls_between(c, o, world))})
        if d <= hr and oid not in heard_ids:
            unheard.append({"id": oid, "name": o.get("name"), "x": o["x"], "y": o["y"], "distance": round(d, 1)})
    aware = []
    for oid, s in (c.get("last_seen") or {}).items():
        if oid in chars and oid not in seen_ids:
            aware.append({"id": oid, "name": chars[oid].get("name"), "x": s.get("x"), "y": s.get("y"),
                          "ago_s": tick - (s.get("tick") or 0)})
    return {
        "tick": tick, "id": char_id, "name": c.get("name"), "x": c.get("x"), "y": c.get("y"),
        "navigation": {"now": now, "plans": plans[-6:], "speed": speed},
        "perception": {"visual_range": vr, "detection_range": pc.detection_range(c, world), "hearing_range": pc.hearing_range(c),
                       "seen": seen, "heard": heard, "in_range_unseen": hidden, "in_range_unheard": unheard,
                       "last_seen": sorted(aware, key=lambda a: a["ago_s"])[:12]},
    }
