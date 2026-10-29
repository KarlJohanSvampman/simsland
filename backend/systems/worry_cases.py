"""
systems/worry_cases.py -- worries as case files that take up focus.

(docs/worry_system_plan.md. This is build step 1: the case file, registration/refresh/expiry, the
hourly poll, the focus budget and the line the character sees. Required focus on activities, mitigation
intentions and breakdowns come later.)

A worry is a temporary case about something a character is anxious about. Each case has a severity,
which sets how long it lasts and how much of the character's focus it takes while it lasts:

    c["worry_cases"][case_id] = {
        id, status,                          # active | resolved | lapsed
        subject: {kind, ref, label},         # self | person | event | expectation | choice | conflict | area
        severity,                            # 1-10
        focus_cost,                          # percentage points taken off max focus while active
        created, expires, last_refreshed, refreshes,
        tags,                                # what counts as evidence for this case
        evidence: [{tick, source, ref, note}],
        summary,                             # one line for the prompt
        mitigated_by: [],                    # filled by the relief step (later)
    }
    c["focus_state"] = {available, load, top_case, tick}

`c["worries"]` (systems/worries.py) is person-keyed *suspicion* and stays what it was; it is one producer
of cases here, in its own key so the two don't collide.

Specific subjects (person/event/...) have one case each: a repeat registration or fresh evidence refreshes
it. Generic `area` worries (workplace, family, finances, politics, media, health, neighbourhood) are vague
background unease: capped at severity 3, created only when the character has no other active worry, and
refreshed by area-tagged evidence found by the hourly poll (new memories, news, conversation lines).
"""

import zlib

HOUR = 3600                              # ticks in a simulated hour (1 tick = 1 simulated second)

DURATION_PER_SEVERITY = HOUR             # a severity-5 worry lasts five hours; area worries half
AREA_DURATION_FACTOR = 0.5
FOCUS_PER_SEVERITY = 2                   # percentage points of focus per severity point
CASE_COST_CAP = 25
MAX_LOAD = 80                            # the most focus worries can take together
CONFLICT_LOAD_CAP = 35                   # ... and quarrels with other people, however many, take no more than this of it
MIN_SEVERITY = 2                         # below this nothing is registered
AREA_SEVERITY_CAP = 3
REFRESH_NUDGE = 1                        # a refresh may raise severity by this much ...
REFRESH_OVER_REPORTED = 2                # ... but never above what was last reported + this
MAX_EVIDENCE = 8
KEEP_CLOSED_CASES = 6                    # resolved/lapsed cases kept for the record
POLL_EVERY_TICKS = HOUR
SMALL_CHILD_AGE = 8
SMALL_CHILD_AREAS = {"family", "health"}   # the only generic worries a small child has

# Generic areas. definitions.json -> "worry_areas" overrides/extends these ({area: {tags, keywords}}).
DEFAULT_AREAS = {
    "workplace":     {"tags": ["work", "job", "boss", "coworker", "workplace", "fired", "layoff", "shift", "career"],
                      "keywords": ["my job", "boss", "fired", "laid off", "coworker", "work shift", "my career"]},
    "family":        {"tags": ["family", "relative", "parent", "child", "sibling", "kin", "household"],
                      "keywords": ["my family", "my kids", "my parents", "my brother", "my sister"]},
    "finances":      {"tags": ["money", "finance", "bill", "debt", "rent", "loan", "eviction", "unpaid", "broke"],
                      "keywords": ["overdue", "can't afford", "cannot afford", "debt", "rent is", "eviction", "overdraft", "unpaid bill"]},
    "politics":      {"tags": ["politics", "election", "government", "tax", "policy", "protest", "party"],
                      "keywords": ["election", "government", "new tax", "protest", "the council"]},
    "media":         {"tags": ["news", "media", "headline"],
                      "keywords": ["on the news", "headline", "newspaper"]},
    "health":        {"tags": ["health", "illness", "sick", "doctor", "injury", "symptom", "hospital", "disease"],
                      "keywords": ["feeling ill", "my health", "diagnos", "symptom", "hospital"]},
    "neighbourhood": {"tags": ["neighbourhood", "local", "crime", "police", "burglary", "noise", "safety"],
                      "keywords": ["break-in", "burglary", "unsafe", "police activity", "crime"]},
}

# how worried by nature
ANXIOUS_TRAITS = {"nervous": 0.25, "paranoid": 0.3, "pessimistic": 0.2, "anxious": 0.3, "neurotic": 0.3}
STEADY_TRAITS = {"calm": -0.2, "resilient": -0.2, "optimistic": -0.15, "stoic": -0.2}
CLOSE_KIN = {"parent", "child", "spouse", "partner", "sibling", "guardian", "dependent", "adoptive_parent", "step_parent"}


def _areas(world):
    areas = {k: dict(v) for k, v in DEFAULT_AREAS.items()}
    for k, v in ((world or {}).get("definitions") or {}).get("worry_areas", {}).items():
        areas[k] = {"tags": list(v.get("tags", [])), "keywords": list(v.get("keywords", []))}
    return areas


def _cases(c):
    return c.setdefault("worry_cases", {})


def active_cases(c):
    return [case for case in (c.get("worry_cases") or {}).values() if case.get("status") == "active"]


def _duration(severity, kind):
    return int(severity * DURATION_PER_SEVERITY * (AREA_DURATION_FACTOR if kind == "area" else 1.0))


def _focus_cost(severity):
    return min(CASE_COST_CAP, int(round(severity * FOCUS_PER_SEVERITY)))


# ---------------------------------------------------------------------------
# severity
# ---------------------------------------------------------------------------

def propensity(c):
    """How readily this character worries: ~0.6 (very steady) to ~1.8 (very anxious)."""
    traits = set(c.get("traits") or [])
    p = 1.0 + sum(v for t, v in ANXIOUS_TRAITS.items() if t in traits) + sum(v for t, v in STEADY_TRAITS.items() if t in traits)
    stress = c.get("stress")
    if isinstance(stress, (int, float)):
        p += max(0.0, min(0.3, float(stress) * 0.3))
    return max(0.5, min(1.8, p))


def closeness(c, other_id):
    """How much what happens to `other_id` matters to this character."""
    rel = (c.get("relationships") or {}).get(other_id)
    if not rel:
        return 0.5
    kin = rel.get("kinship")
    if kin in CLOSE_KIN:
        return 1.5
    if kin:
        return 1.2
    friendship = rel.get("friendship") or 0
    if friendship >= 30:
        return 1.3
    if friendship >= 10:
        return 1.0
    return 0.8 if (rel.get("familiarity") or 0) >= 5 else 0.5


def compute_severity(c, base, other_id=None):
    """severity = base x closeness x propensity, clamped to 1-10."""
    s = float(base) * propensity(c) * (closeness(c, other_id) if other_id else 1.0)
    return max(1.0, min(10.0, round(s, 1)))


# ---------------------------------------------------------------------------
# registering, refreshing, closing
# ---------------------------------------------------------------------------

def case_id_for(subject):
    return f"{subject['kind']}:{subject.get('ref') or ''}"


def register_worry(c, subject, severity, source, note, world, tags=None, summary=None, ref=None):
    """Register a worry, or refresh the one that already exists for this subject.
    subject = {"kind", "ref", "label"}. Returns the case, or None if nothing was registered
    (too mild, a small child worrying about a stranger, a generic area while another worry is active)."""
    tick = (world or {}).get("tick", 0)
    kind = subject["kind"]
    sev = float(severity)
    if kind == "area":
        sev = min(sev, AREA_SEVERITY_CAP)
    if sev < MIN_SEVERITY:
        return None
    if (c.get("age") or 30) < SMALL_CHILD_AGE and kind not in ("self", "area") \
            and not (kind == "person" and (c.get("relationships") or {}).get(subject.get("ref"), {}).get("kinship")):
        return None                                  # a small child worries about themselves and their family
    if kind == "area" and (c.get("age") or 30) < SMALL_CHILD_AGE and subject.get("ref") not in SMALL_CHILD_AREAS:
        return None                                  # politics and money are not a small child's worries
    cases = _cases(c)
    cid = case_id_for(subject)
    case = cases.get(cid)
    entry = {"tick": tick, "source": source, "ref": ref, "note": note}

    if case and case.get("status") == "active":
        if str(source).startswith("scan:"):
            # derived from a standing situation: the case follows the situation (up or down), it doesn't creep;
            # while relief is fresh (systems/worry_relief.py) it is not pushed back above what relief brought it to
            if tick < case.get("eased_until", 0):
                sev = min(sev, case["severity"])
            case["severity"] = case["reported"] = sev
            case["focus_cost"] = _focus_cost(sev)
            return _refresh(c, case, sev, entry, tick, nudge=False)
        return _refresh(c, case, sev, entry, tick)

    if kind == "area" and active_cases(c):
        return None                                  # background unease only while nothing specific is on their mind
    case = cases[cid] = {
        "id": cid, "status": "active", "subject": dict(subject),
        "severity": sev, "focus_cost": _focus_cost(sev), "reported": sev,
        "origin": source,                            # who opened it ("scan:*" cases are closed by the scan when the situation ends)
        "created": tick, "expires": tick + _duration(sev, kind), "last_refreshed": tick, "refreshes": 0,
        "tags": sorted(set(tags or []) | ({str(subject["ref"])} if subject.get("ref") else set())),
        "evidence": [entry],
        "summary": summary or note, "mitigated_by": [],
    }
    _prune_closed(cases)
    _remember(c, case, world, created=True)
    update_focus(c, world)
    _mitigate(c, world)
    return case


def _refresh(c, case, reported, entry, tick, nudge=True):
    """Fresh evidence: extend the case and, at most once per tick, nudge its severity up by REFRESH_NUDGE
    (never above what the reporter reported + REFRESH_OVER_REPORTED, never above 10)."""
    case["last_refreshed"] = tick
    case["refreshes"] = case.get("refreshes", 0) + 1
    case["evidence"] = ((case.get("evidence") or []) + [entry])[-MAX_EVIDENCE:]
    kind = case["subject"]["kind"]
    if nudge and kind != "area" and case.get("_nudged") != tick:
        case["reported"] = max(float(reported), case.get("reported", 0))
        cap = min(10.0, case["reported"] + REFRESH_OVER_REPORTED)
        case["severity"] = max(case["severity"], min(case["severity"] + REFRESH_NUDGE, cap))
        case["focus_cost"] = _focus_cost(case["severity"])
        case["_nudged"] = tick
    case["expires"] = max(case["expires"], tick + _duration(case["severity"], kind))
    update_focus(c, {"tick": tick})
    return case


def refresh_case(c, case, world, source, note, ref=None, negative=True):
    """Fresh evidence for an existing active case."""
    tick = world.get("tick", 0)
    return _refresh(c, case, case.get("reported", case["severity"]),
                    {"tick": tick, "source": source, "ref": ref, "note": note}, tick, nudge=negative)


def close_case(c, case_id, world, status="resolved", reason=None):
    case = (c.get("worry_cases") or {}).get(case_id)
    if not case or case.get("status") != "active":
        return None
    case["status"] = status
    case["closed"] = (world or {}).get("tick", 0)
    if reason:
        case["closed_reason"] = reason
    update_focus(c, world)
    return case


def _prune_closed(cases):
    closed = sorted((cs for cs in cases.values() if cs.get("status") != "active"), key=lambda cs: cs.get("closed", 0))
    for cs in closed[:max(0, len(closed) - KEEP_CLOSED_CASES)]:
        cases.pop(cs["id"], None)


def _remember(c, case, world, created):
    """A memory that the worry exists. Tagged so the poll never takes it for fresh evidence."""
    try:
        from brain.memory import store_memory
        label = case["subject"].get("label") or case["subject"].get("ref") or "something"
        people = [case["subject"]["ref"]] if case["subject"]["kind"] == "person" and case["subject"].get("ref") else []
        store_memory(c, case["summary"] if case["summary"].lower().startswith(("i ", "i'")) else f"I can't stop worrying about {label}: {case['summary']}",
                     importance=min(0.9, 0.3 + case["severity"] / 15.0), tags=["worry", "worry_case"], people=people,
                     tick=(world or {}).get("tick", 0), source="internal")
    except Exception:
        pass


def _mitigate(c, world):
    """Someone whose focus is low starts looking for relief (systems/worry_relief.py)."""
    try:
        from systems.worry_relief import sync_mitigation
        sync_mitigation(c, world)
    except Exception as exc:
        print(f"[worry_cases] mitigation failed: {exc!r}")


# ---------------------------------------------------------------------------
# focus
# ---------------------------------------------------------------------------

def update_focus(c, world):
    """Expire what has run out, then recompute the focus budget. Cheap: a character has a handful of cases."""
    tick = (world or {}).get("tick", 0)
    cases = c.get("worry_cases") or {}
    for case in cases.values():
        if case.get("status") == "active" and tick >= case["expires"]:
            case["status"] = "lapsed"
            case["closed"] = tick
    act = active_cases(c)
    quarrels = sum(cs["focus_cost"] for cs in act if (cs.get("subject") or {}).get("kind") == "conflict")
    load = min(MAX_LOAD, sum(cs["focus_cost"] for cs in act) - quarrels + min(CONFLICT_LOAD_CAP, quarrels))
    top = max(act, key=lambda cs: cs["focus_cost"], default=None)
    state = c.setdefault("focus_state", {})
    new = {"available": 100 - load, "load": load, "top_case": top["id"] if top else None}
    if any(state.get(k) != v for k, v in new.items()):        # untouched when nothing changed: it is a synced key
        state.update(new)
    return state


def focus_available(c, world):
    """Percent of focus left after active worries (100 when there are none)."""
    if not c.get("worry_cases"):
        return 100
    return update_focus(c, world)["available"]


# ---------------------------------------------------------------------------
# the hourly poll
# ---------------------------------------------------------------------------

def _negative_memory(m):
    return (m.get("emotional_impact") or 0) < 0 or (m.get("importance") or 0) >= 0.7


def _new_memories(c, since):
    out = []
    for m in reversed(c.get("memories") or []):
        if (m.get("tick") or 0) <= since:
            break
        if "worry_case" in (m.get("tags") or []):
            continue
        out.append(m)
    return out


def _area_hit(areas, tags, text):
    tags = {t.lower() for t in tags}
    low = (text or "").lower()
    hits = []
    for name, spec in areas.items():
        if tags & {t.lower() for t in spec.get("tags", [])} or any(k.lower() in low for k in spec.get("keywords", [])):
            hits.append(name)
    return hits


def poll_worries(c, world):
    """Look at what has happened since the last poll and let it refresh or start worries.
    Cost is proportional to the NEW memories and news, not the whole store."""
    tick = world.get("tick", 0)
    state = c.setdefault("focus_state", {})
    since = state.get("last_poll", tick - POLL_EVERY_TICKS)
    state["last_poll"] = tick
    update_focus(c, world)
    scanned = {}
    try:
        from systems.worry_producers import scan_state          # standing situations: grudges, health, money, ...
        scanned = scan_state(c, world)
    except Exception as exc:
        print(f"[worry_cases] state scan failed: {exc!r}")
    areas = _areas(world)
    act = {cs["id"]: cs for cs in active_cases(c)}

    evidence = []      # (tags, people, text, negative, source, ref)
    for m in _new_memories(c, since):
        evidence.append((m.get("tags") or [], m.get("people") or [], m.get("text") or "", _negative_memory(m), "memory", m.get("id")))
    for item in reversed(world.get("news") or []):
        if (item.get("tick") or 0) <= since:
            break
        evidence.append((item.get("tags") or [], item.get("related_entities") or [], f"{item.get('headline', '')} {item.get('summary', '')}",
                         item.get("sentiment") == "negative", "news", item.get("id")))

    refreshed, started = [], []
    for tags, people, text, negative, source, ref in evidence:
        tagset = {t.lower() for t in tags}
        # specific cases: the person is involved, or a case tag shows up
        for cid, case in list(act.items()):
            if case["subject"]["kind"] == "area":
                continue
            ref_id = case["subject"].get("ref")
            if (ref_id and ref_id in people) or tagset & {t.lower() for t in case.get("tags", []) if t != ref_id}:
                refresh_case(c, case, world, source, (text or "")[:120], ref=ref, negative=negative)
                refreshed.append(cid)
        # generic areas
        if not negative:
            continue
        for name in _area_hit(areas, tags, text):
            cid = f"area:{name}"
            case = (c.get("worry_cases") or {}).get(cid)
            if case and case.get("status") == "active":
                refresh_case(c, case, world, source, (text or "")[:120], ref=ref, negative=False)
                refreshed.append(cid)
            elif not active_cases(c):
                base = 1.0 + (2.0 if source == "news" else 1.5)
                made = register_worry(c, {"kind": "area", "ref": name, "label": name}, compute_severity(c, base), source,
                                      (text or "")[:120], world, tags=areas[name]["tags"],
                                      summary=f"{name}: {(text or '')[:80]}".strip(), ref=ref)
                if made:
                    started.append(cid)
                    act = {cs["id"]: cs for cs in active_cases(c)}
    update_focus(c, world)
    _mitigate(c, world)
    return {"refreshed": refreshed, "started": started, "scan": scanned}


def tick_worry_polls(world):
    """Scheduled job: poll each character about once an hour (staggered per character)."""
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        if c.get("is_workplace_npc") or c.get("is_service_worker") or c.get("alive") is False:
            continue
        state = c.setdefault("focus_state", {})
        if "last_poll" not in state:                 # first sight: spread the characters over the hour
            state["last_poll"] = tick - (zlib.crc32(str(c.get("id")).encode()) % POLL_EVERY_TICKS)
        if tick - state["last_poll"] >= POLL_EVERY_TICKS:
            poll_worries(c, world)


# ---------------------------------------------------------------------------
# what the character sees
# ---------------------------------------------------------------------------

def context_lines(c, world):
    """Lines for the prompt: what is on their mind, and how much room it leaves."""
    if not c.get("worry_cases"):
        return []
    state = update_focus(c, world)
    act = sorted(active_cases(c), key=lambda cs: -cs["focus_cost"])
    if not act:
        return []
    lines = []
    for case in act[:3]:
        lines.append(f"On your mind: {case['summary']}")
    from systems.worry_breakdown import in_breakdown, recently_broke_down
    if in_breakdown(c):
        lines.append("You are falling apart: you can't think, you can only react.")
    elif recently_broke_down(c, world):
        lines.append("You broke down a little while ago. You are drained, and a bit lighter for it.")
    abort = c.get("_focus_abort")
    if abort and world.get("tick", 0) - abort.get("tick", 0) < 2 * HOUR:
        lines.append(f"You tried to {str(abort.get('activity')).replace('_', ' ')} but couldn't concentrate on it.")
    avail = state["available"]
    if avail <= 30:
        lines.append(f"Your worries take up almost all of your attention; you can barely concentrate ({avail}% of your focus is left).")
    elif avail <= 60:
        lines.append(f"Worry takes up part of your focus ({avail}% left), so demanding tasks are harder than usual.")
    return lines
