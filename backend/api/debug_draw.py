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


@router.get("/talk-reach/log")
def talk_reach_log(sim_id: str = "default", limit: int = 50):
    """The latest in-person lines said to someone out of sight, out of earshot or in another room, newest first."""
    world = load_world(sim_id)
    log = world.get("conversation_reach_log") or []
    return {"tick": world.get("tick", 0), "incidents": list(reversed(log[-max(1, min(100, limit)):]))}


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
            seen.append({"id": v["id"], "name": o.get("name"), "x": o["x"], "y": o["y"], "distance": v.get("distance"),
                         "visibility": v.get("visibility"),
                         "thinks": v.get("name") if v.get("mistaken_for") else None})
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
                      "thinks": a.get("speaker") if a.get("mistaken_for") else None,
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
    # the sight-line tests the last look really made (brain/perception.py::_record_los)
    lc = c.get("_los_checks") or {}
    los = {"age_s": tick - lc["tick"] if lc.get("tick") is not None else None, "checks": lc.get("checks") or []}
    # how sight fades with distance (systems/vision.py detail tiers) and how far each voice carries
    det = pc.detection_range(c, world)
    bands = {"recognized": vr, "figure": vr + (det - vr) / 2.0 if det > vr else vr, "silhouette": det}
    voices = {v: round(pc.volume_range(c, v), 1) for v in pc.VOLUME_TIERS}

    # in-person conversations they're in: are the others really within sight and earshot? (systems/conversation_reach.py)
    from systems.conversation_reach import check_pair
    talks = []
    for conv in (world.get("conversations") or {}).values():
        if not conv.get("active") or char_id not in (conv.get("participants") or []):
            continue
        if (conv.get("medium") or "in_person") != "in_person":
            continue
        for oid in conv["participants"]:
            o = chars.get(oid)
            if oid == char_id or not o or o.get("x") is None:
                continue
            now_r = check_pair(world, c, o)
            last_r = (conv.get("reach") or {}).get(f"{char_id}>{oid}") or (conv.get("reach") or {}).get(f"{oid}>{char_id}")
            talks.append({"conv_id": conv["id"], "id": oid, "name": o.get("name"), "x": o["x"], "y": o["y"],
                          "now": now_r, "last_line": last_r, "lines": len(conv.get("history") or [])})

    # reputation of everyone around them: the public score and standing, and how they themselves regard that person
    from systems.reputation import _label, _notoriety_label
    rep_near = []
    for oid, o in chars.items():
        if oid == char_id or o.get("alive") is False or o.get("off_grid") or o.get("x") is None:
            continue
        dist = ((o["x"] - c["x"]) ** 2 + (o["y"] - c["y"]) ** 2) ** 0.5
        if dist > det:
            continue
        r = o.get("reputation") or {}
        g, cm, n = float(r.get("global", 0.5)), float(r.get("community", 0.5)), float(r.get("notoriety", 0.0))
        rel = (c.get("relationships") or {}).get(oid) or {}
        rep_near.append({"id": oid, "name": o.get("name"), "x": o["x"], "y": o["y"], "distance": round(dist, 1),
                         "global": round(g, 2), "standing": _label(g), "community": round(cm, 2), "community_standing": _label(cm),
                         "notoriety": round(n, 2), "notoriety_label": _notoriety_label(n), "last_event": r.get("last_event"),
                         "their_view": {k: round(float(rel[k]), 2) for k in ("trust", "respect", "friendship") if isinstance(rel.get(k), (int, float))}})
    rep_near.sort(key=lambda e: e["distance"])

    return {
        "tick": tick, "id": char_id, "name": c.get("name"), "x": c.get("x"), "y": c.get("y"),
        "navigation": {"now": now, "plans": plans[-6:], "speed": speed},
        "perception": {"visual_range": vr, "detection_range": pc.detection_range(c, world), "hearing_range": pc.hearing_range(c),
                       "seen": seen, "heard": heard, "in_range_unseen": hidden, "in_range_unheard": unheard,
                       "last_seen": sorted(aware, key=lambda a: a["ago_s"])[:12],
                       "los": los, "vision_bands": bands, "voice_ranges": voices},
        "conversations": talks,
        "social": {"reputation": rep_near[:16]},
    }
