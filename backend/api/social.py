"""
/admin/social -- the agreements (social contracts) for the viewer's "Social" tab (frontend/src/main.js).

  GET /admin/social/contracts?char_id=...&scope=mine|all   the list: title, state, who, terms, how it's going
  GET /admin/social/contract/{id}                           everything about one, for the details window:
        what was agreed (the terms: who does what, when, how it's going), who's involved, and for each of them --
        responsibilities (what they agreed to do), expectations (what's expected of them now: the real expectation
        entries behind their terms, with the window on their schedule and how it's going), rights (what the others
        agreed to do for them, the rules they can hold the others to, what they can do if it's broken), and the
        breaches on record.

Read-only, from the saved world (db.load_world) like api/conversation_trace.py.
"""

from fastapi import APIRouter, HTTPException

from db import load_world

router = APIRouter(prefix="/admin/social", tags=["social"])

_STATE_TEXT = {"proposed": "proposed", "negotiated": "being negotiated", "accepted": "agreed", "active": "in force",
               "violated": "broken (still in force)", "disputed": "disputed", "renegotiating": "being renegotiated",
               "fulfilled": "fulfilled", "expired": "expired", "terminated": "ended"}
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _contracts(world):
    from social.contracts import normalize
    out = []
    for k in (world.get("social_contracts") or {}).values():
        if isinstance(k, dict) and k.get("id"):
            out.append(normalize(k))
    return out


def _in_force(k):
    from social.contracts import IN_FORCE
    return (k.get("state") or k.get("status")) in IN_FORCE


def _name(world, cid, full=False):
    n = ((world.get("characters") or {}).get(cid) or {}).get("name") or str(cid or "someone")
    return n if full else n.split(" ")[0]


def _when(world, tick):
    """A tick as the sim's clock: "Saturday 14:30" (with "today" / "yesterday" / "tomorrow" when it is)."""
    if tick is None:
        return None
    cal = world.get("calendar") or {}
    now = world.get("tick", 0)
    if "hour" not in cal:
        return f"tick {tick}"
    now_min = cal.get("hour", 0) * 60 + cal.get("minute", 0)
    delta_min = (int(tick) - int(now)) // 60
    total = now_min + delta_min
    day_off, minute = divmod(total, 24 * 60)
    wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(
        (cal.get("weekday") or "monday").lower()) if (cal.get("weekday") or "").lower() in (
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday") else 0
    day = {0: "today", -1: "yesterday", 1: "tomorrow"}.get(day_off) or _DAYS[(wd + day_off) % 7]
    if abs(day_off) > 6:
        day = f"{abs(day_off)} days {'ago' if day_off < 0 else 'from now'}"
    return f"{day} {minute // 60:02d}:{minute % 60:02d}"


def _agreement(world, cid, kid, tid):
    c = (world.get("characters") or {}).get(cid) or {}
    return next((a for a in c.get("agreements") or [] if a.get("contract_id") == kid and a.get("term_id") == tid), None)


def _term_info(world, k, t):
    from systems.agreements import classify, parse_time
    ob = t.get("obligation") or str(t.get("commitment") or "").replace("_", " ")
    who = t.get("responsible_party") or t.get("party")
    kind, cadence, acts = classify(ob)
    when = parse_time(ob, t) if kind != "rule" else None
    a = _agreement(world, who, k["id"], t.get("id")) or {}
    return {"id": t.get("id"), "obligation": ob, "responsible": who, "responsible_name": _name(world, who),
            "kind": a.get("kind") or kind, "cadence": a.get("cadence") or cadence,
            "when": (a.get("time") or when or {}).get("label") or None,
            "frequency": t.get("frequency"), "deadline": t.get("deadline"),
            "conditions": t.get("conditions") or [], "consequences": t.get("consequences") or [],
            "status": a.get("status") or t.get("status") or "pending", "kept": a.get("kept", 0),
            "missed": a.get("missed", 0), "last_kept": _when(world, a.get("last_kept_tick")), "how": a.get("how"),
            "expectation_id": a.get("expectation_id")}


def _expectation(world, cid, eid):
    e = (((world.get("characters") or {}).get(cid) or {}).get("expectations") or {}).get(eid)
    if not e:
        return None
    tw = e.get("time_window") or {}
    return {"id": eid, "label": e.get("label") or eid, "cadence": e.get("cadence"),
            "status": "not due" if e.get("not_applicable") else e.get("status"),
            "window": (f"{_when(world, e.get('window_start_tick'))} – {_when(world, e.get('window_end_tick'))}"
                       if e.get("window_start_tick") is not None and e.get("window_end_tick") is not None else None),
            "agreed_time": (f"{tw.get('start')}–{tw.get('end')}" + (
                " on " + ", ".join(_DAYS[d] for d in tw["weekdays"]) if tw.get("weekdays") else "")) if tw else None,
            "streak": e.get("streak", 0), "missed_count": e.get("missed_count", 0),
            "frustration": round(float(e.get("frustration") or 0), 2)}


def _summary(world, k):
    terms = k.get("terms") or []
    return {"id": k["id"], "title": k.get("title") or "an agreement", "state": k.get("state"),
            "state_text": _STATE_TEXT.get(k.get("state"), k.get("state")), "in_force": _in_force(k),
            "type": k.get("contract_type"), "parties": [_name(world, p) for p in k.get("parties") or []],
            "party_ids": list(k.get("parties") or []), "terms": len(terms),
            "obligations": [f"{_name(world, t.get('responsible_party') or t.get('party'))}: "
                            f"{t.get('obligation') or t.get('commitment')}" for t in terms][:4],
            "breaches": len(k.get("violation_records") or k.get("violations") or []),
            "made": _when(world, k.get("created_tick")), "created_tick": k.get("created_tick") or 0}


@router.get("/contracts")
def contracts(char_id: str = None, scope: str = "mine", sim_id: str = "default"):
    world = load_world(sim_id)
    rows = []
    for k in _contracts(world):
        if scope != "all" and char_id and char_id not in (k.get("parties") or []):
            continue
        rows.append(_summary(world, k))
    rows.sort(key=lambda r: (not r["in_force"], -r["created_tick"]))
    return {"tick": world.get("tick", 0), "contracts": rows}


@router.get("/contract/{kid}")
def contract(kid: str, sim_id: str = "default"):
    world = load_world(sim_id)
    k = next((x for x in _contracts(world) if x["id"] == kid), None)
    if not k:
        raise HTTPException(404, f"no agreement '{kid}'")
    terms = [_term_info(world, k, t) for t in k.get("terms") or []]
    parties = list(k.get("parties") or [])
    authority = k.get("authority_id")
    breaches = []
    for v in k.get("violation_records") or []:
        breaches.append({"who": _name(world, v.get("responsible_party")), "who_id": v.get("responsible_party"),
                         "what": v.get("evidence") or v.get("violation_type"), "when": _when(world, v.get("timestamp")),
                         "seen_by": _name(world, v.get("observed_by")) if v.get("observed_by") else None,
                         "severity": v.get("severity"), "disputed": bool(v.get("disputed"))})
    people = []
    for p in parties:
        others = [o for o in parties if o != p]
        mine = [t for t in terms if t["responsible"] == p]
        theirs = [t for t in terms if t["responsible"] != p and t["kind"] != "rule"]
        rules = [t for t in terms if t["responsible"] != p and t["kind"] == "rule"]
        expectations = [x for x in (_expectation(world, p, t["expectation_id"]) for t in mine if t["expectation_id"]) if x]
        rights = [f"{t['responsible_name']} {t['obligation']}" + (f" ({t['when']})" if t["when"] else "")
                  for t in theirs]
        rights += [f"{t['responsible_name']} keeps to: {t['obligation']}" for t in rules]
        if theirs or rules:
            rights.append(f"If {' or '.join(_name(world, o) for o in others)} breaks it, {_name(world, p)} can call "
                          f"it out -- it goes on record as a breach and counts against them.")
        if authority == p:
            rights.append(f"As the one in charge, {_name(world, p)} sets the consequences and decides on changes "
                          f"{' and '.join(_name(world, o) for o in others)} ask for.")
        rights.append("Ask to renegotiate the agreement.")
        people.append({
            "id": p, "name": _name(world, p, full=True),
            "role": "in charge" if authority == p else ("bound by it" if k.get("subject_id") == p else "party"),
            "responsibilities": [{"obligation": t["obligation"], "when": t["when"], "kind": t["kind"],
                                  "cadence": t["cadence"], "status": t["status"], "kept": t["kept"],
                                  "missed": t["missed"], "consequences": t["consequences"]} for t in mine],
            "expectations": expectations,
            "rights": rights,
            "breaches": [b for b in breaches if b["who_id"] == p],
        })
    out = _summary(world, k)
    out.update({"description": k.get("description") or "", "conditions": k.get("conditions") or [],
                "effective": _when(world, k.get("effective_at")), "expires": _when(world, k.get("expires_at")),
                "authority": _name(world, authority) if authority else None,
                "origin_conversation_id": k.get("origin_conversation_id"),
                "revisions": len(k.get("revision_history") or []),
                "compliance": k.get("compliance_score"), "terms_detail": terms, "people": people,
                "breach_records": breaches})
    return out
