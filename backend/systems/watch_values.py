"""
systems/watch_values.py -- what VR "Watch values" (frontend/src/vrWatch.js) can show above a character.

    QUICK          ready-made states: mood, top intention, activity, stress, the next thing due (a calendar event or an
                   expectation's window), reputation
    fields(c, w)   every scalar on the character (bools, numbers, short strings) by dotted path, grouped by top-level
                   key; a string whose path takes only a few values across everyone is an enum (with its options)
    value(c, w, p) the current value of a quick state or a path

Only the client keeps history (the previous value, when it changed); nothing here is stored.
"""

MAX_DEPTH = 4
MAX_STR = 80
ENUM_MAX_OPTIONS = 10
KNOWN_ENUMS = {"posture", "animation_state", "emotion", "mood.name", "mood.polarity", "activity.type", "development_stage",
               "family_role", "status"}


def _fmt_in(seconds):
    s = max(0, int(seconds))
    if s < 90:
        return f"{s} s"
    if s < 90 * 60:
        return f"{round(s / 60)} min"
    if s < 36 * 3600:
        return f"{s / 3600:.1f} h"
    return f"{round(s / 86400)} days"


def _mood(c, w):
    m = c.get("mood") or {}
    return m.get("name") or c.get("emotion") or "neutral"


def _intention(c, w):
    try:
        from systems.todo import todo_list
        t = todo_list(c)
        top = (t["pressing"] or t["when_free"] or [None])[0]
    except Exception:
        top = None
    if not top:
        return "none"
    name = str(top.get("type") or "?").replace("expectation:", "").replace("_", " ")
    tgt = (w.get("characters") or {}).get(top.get("target_id") or "")
    return name + (f" ({tgt.get('name')})" if tgt else "")


def _activity(c, w):
    a = c.get("activity") or {}
    if a.get("type"):
        return str(a["type"]).replace("_", " ")
    return "walking" if c.get("is_moving") else "idle"


def _stress(c, w):
    return round(float(c.get("stress") or 0), 1)


def _next_due(c, w):
    """The soonest of: an expectation window that opens or closes next, a calendar event."""
    tick = w.get("tick", 0)
    best = None                                   # (seconds, text)
    for nd in (c.get("expectations") or {}).values():
        if not isinstance(nd, dict) or nd.get("status") in ("satisfied",) or nd.get("satisfied_this_period"):
            continue
        start, end = nd.get("window_start_tick"), nd.get("window_end_tick")
        name = str(nd.get("label") or nd.get("template_id") or "?").replace("_", " ")
        if start is not None and start > tick:
            cand = (start - tick, f"{name} in {_fmt_in(start - tick)}")
        elif end is not None and end > tick:
            cand = (end - tick, f"{name} — due within {_fmt_in(end - tick)}")
        else:
            continue
        if best is None or cand[0] < best[0]:
            best = cand
    try:
        from systems.calendar_events import get_upcoming_events
        ev = get_upcoming_events(c, w, horizon_days=60)
        if ev:
            e = ev[0]
            secs = (e.get("days_until") or 0) * 86400
            if best is None or secs < best[0]:
                best = (secs, f"{e.get('name')} " + ("today" if not e.get("days_until") else f"in {e['days_until']} days"))
    except Exception:
        pass
    return best[1] if best else "nothing due"


def _rep_label(v):
    from systems.reputation import _label
    return _label(v)


def _reputation(c, w):
    r = c.get("reputation") or {}
    g = float(r.get("global", 0.5))
    return f"{g:.2f} {_rep_label(g)}"


QUICK = {
    "@mood": ("Mood", "enum", _mood),
    "@intention": ("Intention", "string", _intention),
    "@activity": ("Activity", "enum", _activity),
    "@stress": ("Stress", "number", _stress),
    "@next": ("Next due", "string", _next_due),
    "@reputation": ("Reputation", "string", _reputation),
}


def _walk(obj, prefix, depth, out):
    if isinstance(obj, dict):
        if depth >= MAX_DEPTH:
            return
        for k, v in obj.items():
            if not isinstance(k, str) or k.startswith("_"):
                continue
            _walk(v, f"{prefix}.{k}" if prefix else k, depth + 1, out)
    elif isinstance(obj, bool):
        out[prefix] = ("bool", obj)
    elif isinstance(obj, (int, float)):
        out[prefix] = ("number", obj)
    elif isinstance(obj, str) and len(obj) <= MAX_STR:
        out[prefix] = ("string", obj)
    elif obj is None and prefix in KNOWN_ENUMS:
        out[prefix] = ("string", None)


def fields(c, w, group=None):
    """{"groups": [{group, count}], "fields": [{path, type, value, options?}] (for `group`; "@" = the quick states)}."""
    flat = {}
    _walk(c, "", 0, flat)
    groups = {}
    for p in flat:
        groups[p.split(".", 1)[0]] = groups.get(p.split(".", 1)[0], 0) + 1
    singles = {g for g, n in groups.items() if n == 1}            # one-value keys share a group ("~")
    out = {"groups": [{"group": "@", "label": "★ Quick picks", "count": len(QUICK)}] +
                     ([{"group": "~", "label": "Single values", "count": len(singles)}] if singles else []) +
                     [{"group": g, "label": g.replace("_", " "), "count": n} for g, n in sorted(groups.items()) if g not in singles]}
    if group is None:
        return out
    if group == "@":
        out["fields"] = [{"path": k, "label": lab, "type": typ, "value": fn(c, w)} for k, (lab, typ, fn) in QUICK.items()]
        return out
    rows = []
    others = [o for o in (w.get("characters") or {}).values() if o is not c]
    for p, (typ, v) in sorted(flat.items()):
        top = p.split(".", 1)[0]
        if (top in singles) != (group == "~") or (group != "~" and top != group):
            continue
        row = {"path": p, "label": p.replace("_", " "), "type": typ, "value": v}
        if typ == "string":
            seen = {v} if v is not None else set()
            for o in others:
                ov = value(o, w, p)
                if isinstance(ov, str):
                    seen.add(ov)
                if len(seen) > ENUM_MAX_OPTIONS:
                    break
            if p in KNOWN_ENUMS or (len(seen) <= ENUM_MAX_OPTIONS and len(others) >= 2 and len(seen) < len(others) + 1):
                row["type"] = "enum"
                row["options"] = sorted(seen)
        rows.append(row)
    rows.sort(key=lambda r: ({"enum": 0, "bool": 1, "number": 2, "string": 3}[r["type"]], r["path"]))   # enums and bools first
    out["fields"] = rows
    return out


def value(c, w, path):
    if path in QUICK:
        try:
            return QUICK[path][2](c, w)
        except Exception as e:
            return f"? ({e})"
    cur = c
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, (bool, int, float, str)) or cur is None else str(cur)[:MAX_STR]
