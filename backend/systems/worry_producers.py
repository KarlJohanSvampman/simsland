"""
systems/worry_producers.py -- what gives a character something to worry about.

(docs/worry_system_plan.md, step 2. The case files and the focus budget are in systems/worry_cases.py.)

Two kinds of producer:

  Moments  -- a thing happens and the code that made it happen says so: a self-expectation is missed
              (on_expectation_missed), someone is seen hurting someone (on_witnessed_violence), someone
              dies in view (on_death_witnessed), the character's own loop guard trips (on_loop_trip).

  States   -- a situation that persists is read off the world once an hour by scan_state(), as part of
              the worry poll: grudges (open grievances), a pair ledger that keeps going one way,
              health (their own and a loved one's), money (overdue bills, unpaid tax), a high-stakes
              proposal still waiting for an answer. Every case a scan opens is tagged origin "scan:<what>";
              when the situation is over the next scan closes it (resolved), so nothing has to remember
              to clean up. A case opened by something else (pattern_concern, suspicion) for the same
              person is only refreshed, never closed, by a scan.

Severity is base x propensity, times closeness only where closeness is what makes it matter (a sick
child, a sick friend -- not a grudge or a grave event, which are bad whoever they involve); the bases
below are the "how bad is this kind of thing" numbers to tune from.
"""

from systems import worry_cases as wc

# --- moments ---------------------------------------------------------------------------------------------------
BASE_EXPECTATION_MISSED = 1.6
BASE_WORK_EXPECTATION_MISSED = 3.0       # go_to_work and anything else that is somebody's livelihood
MAX_EXPECTATION_CASES = 2                # a pile of missed things is ONE worry ("everything I'm behind on"), not seven
BASE_BEHIND = 3.0
BASE_WITNESSED_VIOLENCE = 4.5
BASE_WITNESSED_DEATH = 8.0
BASE_LOOP_TRIP = 3.0
BASE_OWN_BREAKDOWN = 3.0
BASE_WITNESSED_BREAKDOWN = 5.0

# --- states ----------------------------------------------------------------------------------------------------
GRIEVANCE_SCORE_TO_WORRY = 12.0          # (systems/grievances.py: cold shoulder starts at 15, confrontation at 30)
LEDGER_MIN_NEG_CAUSED = 12.0             # what the other person has done to them, in the ledger's units
LEDGER_OTHER_SHARE = 0.65                # ... and they are the source of at least this share of it
BASE_HEALTH_SELF = 2.0
BASE_HEALTH_LOVED_ONE = 3.5
BASE_BILL_OVERDUE = 5.0
BASE_GOVERNMENT_DEBT = 3.0
BASE_PENDING_CHOICE = 2.5
BASE_PENDING_ROMANTIC = 3.5
HIGH_STAKES_PROPOSALS = {"romantic", "social_ask", "request", "item_sale"}
PENDING_CHOICE_AFTER_TICKS = wc.HOUR      # a question is not a worry until it has been hanging for a while ...
PENDING_CHOICE_GIVE_UP_TICKS = 24 * wc.HOUR   # ... and after a day nobody is waiting any more
LOVED_ONE_CLOSENESS = 1.2
MAX_CHOICE_CASES = 2                      # the freshest few questions; nobody carries a dozen at once


def _name(world, cid):
    return (world.get("characters", {}).get(cid) or {}).get("name", "someone")


def _safe(fn, *args, **kwargs):
    """Producers must never break the thing they are attached to."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        print(f"[worry_producers] {getattr(fn, '__name__', fn)} failed: {exc!r}")
        return None


# ---------------------------------------------------------------------------
# moments
# ---------------------------------------------------------------------------

def on_expectation_missed(c, nd, world):
    def go():
        tid = nd["template_id"]
        template = (world.get("definitions", {}).get("expectation_templates") or {}).get(tid, {})
        label = template.get("label") or tid.replace("_", " ")
        base = BASE_WORK_EXPECTATION_MISSED if tid == "go_to_work" or template.get("category") in ("work", "job") \
            else BASE_EXPECTATION_MISSED
        base += 1.5 * float(nd.get("frustration", 0.0))
        why = nd.get("last_miss_reason")
        note = f"I missed '{label}'" + (f" ({why})" if why else "") + " and it is weighing on me"
        cid = f"expectation:{tid}"
        have = [k for k, cs in (c.get("worry_cases") or {}).items() if cs.get("status") == "active" and cs["subject"]["kind"] == "expectation"]
        if cid not in have and len(have) >= MAX_EXPECTATION_CASES:
            behind = "I'm falling behind on everything I'm supposed to be doing"
            wc.register_worry(c, {"kind": "self", "ref": "behind", "label": "everything I'm behind on"},
                              wc.compute_severity(c, BASE_BEHIND), "expectation", f"{note}; {behind}", world,
                              tags=["expectation", "behind"], summary=behind)
            return
        wc.register_worry(c, {"kind": "expectation", "ref": tid, "label": label}, wc.compute_severity(c, base),
                          "expectation", note, world, tags=["expectation", tid], summary=note)
    _safe(go)


def on_expectation_satisfied(c, tid, world):
    _safe(wc.close_case, c, f"expectation:{tid}", world, "resolved", "got it done")


def on_witnessed_violence(observer, offender, world):
    def go():
        tick = world.get("tick", 0)
        ref = f"violence:{offender.get('id')}:{tick // wc.HOUR}"
        note = f"I saw {offender.get('name', 'someone')} hurt someone and I can't get it out of my head"
        wc.register_worry(observer, {"kind": "event", "ref": ref, "label": "the violence I saw"},
                          wc.compute_severity(observer, BASE_WITNESSED_VIOLENCE), "witnessed",
                          note, world, tags=["violence", "incident", str(offender.get("id"))], summary=note)
    _safe(go)


def on_death_witnessed(dead, world):
    """Everyone who had the dead character in view."""
    def go():
        for c in world.get("characters", {}).values():
            if c.get("id") == dead.get("id") or c.get("alive") is False:
                continue
            seen = [p.get("id") for p in (c.get("perception") or {}).get("visible_people", [])]
            if dead.get("id") not in seen:
                continue
            note = f"I watched {dead.get('name', 'someone')} die"
            wc.register_worry(c, {"kind": "event", "ref": f"death:{dead.get('id')}", "label": f"{dead.get('name', 'a death')}"},
                              wc.compute_severity(c, BASE_WITNESSED_DEATH), "witnessed", note, world,
                              tags=["death", "incident", str(dead.get("id"))], summary=note)
    _safe(go)


def on_own_breakdown(c, world):
    note = "I fell apart, and I'm afraid it will happen again"
    _safe(wc.register_worry, c, {"kind": "self", "ref": "breakdown", "label": "how I fell apart"},
          wc.compute_severity(c, BASE_OWN_BREAKDOWN), "breakdown", note, world, tags=["breakdown", "erratic"], summary=note)


def on_witnessed_breakdown(observer, subject, world, minutes):
    """Someone fell apart where this character could see it: they are worried about them, and if they are close
    they mean to check in."""
    def go():
        sid = subject["id"]
        name = subject.get("name", "them")
        note = f"{name} fell apart in front of me and I'm worried about them"
        wc.register_worry(observer, {"kind": "person", "ref": sid, "label": name},
                          wc.compute_severity(observer, BASE_WITNESSED_BREAKDOWN, sid), "witnessed", note, world,
                          tags=["breakdown", "pattern", "concern", sid], summary=note)
        from brain.memory import store_memory
        store_memory(observer, f"I saw {name} break down for about {minutes} minutes -- crying, snapping, not themselves at all. "
                               f"I should check on them.", importance=0.6, tags=["worry", "pattern", "concern", "breakdown"],
                     people=[sid], tick=world.get("tick", 0), source="internal")
        if wc.closeness(observer, sid) >= 1.0 and (observer.get("age") or 30) >= 8:
            from brain.intentions import add_intention
            add_intention(observer, {"type": "check_in_on", "category": "social", "priority": 50, "target_id": sid,
                                     "reason": f"{name} had a breakdown in front of you -- ask if they're alright"})
    _safe(go)


def on_loop_trip(c, activity_label, world):
    note = f"I keep doing {activity_label} over and over and I can't seem to stop"
    _safe(wc.register_worry, c, {"kind": "self", "ref": "erratic", "label": "how I've been acting"},
          wc.compute_severity(c, BASE_LOOP_TRIP), "loop_guard", note, world, tags=["erratic", "loop"], summary=note)


# ---------------------------------------------------------------------------
# states
# ---------------------------------------------------------------------------

def _wanted_grievances(c, world):
    scores = {}
    top = {}
    for g in c.get("grievances", []):
        scores[g["caused_by"]] = scores.get(g["caused_by"], 0) + g["weight"]
        if g["caused_by"] not in top or g["weight"] > top[g["caused_by"]]["weight"]:
            top[g["caused_by"]] = g
    out = {}
    for pid, score in scores.items():
        if score < GRIEVANCE_SCORE_TO_WORRY or pid not in world.get("characters", {}):
            continue
        name = _name(world, pid)
        what = str(top[pid].get("event_type", "what they did")).replace("_", " ")
        out[f"conflict:{pid}"] = ({"kind": "conflict", "ref": pid, "label": name}, 2.0 + min(3.5, score / 12.0),
                                  f"I'm still angry with {name} ({what}) and it isn't settled", ["conflict", "grievance", pid], None)
    return out


def _wanted_ledger(c, world):
    from systems.relationship_ledger import summarize
    out = {}
    for oid in list((c.get("relationships") or {})):
        if oid not in world.get("characters", {}):
            continue
        s = summarize(world, c["id"], oid)
        if not s:
            continue
        theirs = s["by_char"].get(oid, {})
        mine = s["by_char"].get(c["id"], {})
        caused = theirs.get("neg_caused", 0.0)
        if caused < LEDGER_MIN_NEG_CAUSED or theirs.get("share_of_neg", 0) / 100.0 < LEDGER_OTHER_SHARE \
                or caused < 2 * mine.get("neg_caused", 0.0):
            continue
        name = _name(world, oid)
        out[f"person:{oid}"] = ({"kind": "person", "ref": oid, "label": name}, 2.0 + min(3.0, caused / 12.0),
                                f"{name} keeps hurting me and I don't know what to do about it", ["ledger", "hurt", oid], None)
    return out


def _health_trouble(who):
    hs = who.get("health_state") or {}
    emergencies = len(hs.get("active_emergencies") or {})
    visits = hs.get("doctor_visits_needed", 0) or 0
    sick = bool((who.get("health") or {}).get("sick"))
    return emergencies, visits, sick


def _wanted_health(c, world):
    out = {}
    emergencies, visits, sick = _health_trouble(c)
    if emergencies or visits or sick:
        base = min(8.0, BASE_HEALTH_SELF + 1.5 * visits + 3.0 * emergencies + (1.5 if sick else 0.0))
        note = "I'm not well and it worries me" if not emergencies else "something is badly wrong with my body and I'm frightened"
        out["self:health"] = ({"kind": "self", "ref": "health", "label": "my health"}, base, note, ["health", "illness"], None)
    for oid, rel in (c.get("relationships") or {}).items():
        other = world.get("characters", {}).get(oid)
        if not other or other.get("alive") is False or wc.closeness(c, oid) < LOVED_ONE_CLOSENESS:
            continue
        e2, v2, s2 = _health_trouble(other)
        if e2 or v2 or s2:
            name = other.get("name", "someone")
            base = BASE_HEALTH_LOVED_ONE + (2.0 if e2 else 0.0)
            out[f"person:{oid}"] = ({"kind": "person", "ref": oid, "label": name}, base,
                                    f"{name} is ill and I'm worried about them", ["health", "illness", oid], oid)
    return out


def _wanted_money(c, world):
    out = {}
    tick = world.get("tick", 0)
    h = (world.get("households") or {}).get(c.get("household_id")) or {}
    overdue = [b for b in h.get("bills_due", []) if (b.get("remaining") or 0) > 0 and tick > (b.get("due_tick") or 10 ** 12)]
    debt = c.get("government_debt", 0.0) or 0.0
    if overdue or debt > 0:
        base = max(BASE_BILL_OVERDUE if overdue else 0.0, BASE_GOVERNMENT_DEBT if debt > 0 else 0.0)
        base += min(2.0, 0.5 * max(0, len(overdue) - 1))
        note = "the bills are overdue and I don't know how we'll pay them" if overdue else "I owe tax I can't pay"
        out["self:money"] = ({"kind": "self", "ref": "money", "label": "money"}, base, note, ["money", "bill", "debt"], None)
    return out


def _wanted_choices(c, world):
    out = {}
    tick = world.get("tick", 0)
    open_ones = [p for p in (world.get("proposals") or {}).values()
                 if p.get("status") == "open" and p.get("kind") in HIGH_STAKES_PROPOSALS]
    for p in sorted(open_ones, key=lambda p: -p.get("created_tick", 0)):
        if len(out) >= MAX_CHOICE_CASES:
            break
        age = tick - p.get("created_tick", tick)
        if age < PENDING_CHOICE_AFTER_TICKS or age > PENDING_CHOICE_GIVE_UP_TICKS:
            continue
        mine = p.get("proposer_id") == c["id"]
        owe = c["id"] in (p.get("recipients") or []) and (p.get("responses") or {}).get(c["id"]) == "pending"
        if not (mine or owe):
            continue
        other = (p.get("recipients") or [None])[0] if mine else p.get("proposer_id")
        name = _name(world, other)
        base = BASE_PENDING_ROMANTIC if p.get("kind") == "romantic" else BASE_PENDING_CHOICE
        note = f"I'm still waiting to hear back from {name}" if mine else f"{name} is waiting for my answer and I haven't decided"
        out[f"choice:{p['id']}"] = ({"kind": "choice", "ref": p["id"], "label": f"{name}'s {p.get('kind')}"}, base, note,
                                    ["choice", "proposal", str(other)], None)
    return out


_SCANS = {"grievance": _wanted_grievances, "ledger": _wanted_ledger, "health": _wanted_health,
          "money": _wanted_money, "choice": _wanted_choices}


def scan_state(c, world):
    """Open, refresh and close the worries that follow from the character's standing situation.
    Returns {"opened": [...], "refreshed": [...], "closed": [...]}."""
    result = {"opened": [], "refreshed": [], "closed": []}
    wanted = {}
    for name, fn in _SCANS.items():
        found = _safe(fn, c, world) or {}
        for cid, spec in found.items():
            if cid not in wanted or spec[1] > wanted[cid][2]:          # two scans may want the same case: keep the graver
                wanted[cid] = (name,) + spec
    cases = c.get("worry_cases") or {}
    for cid, (name, subject, base, note, tags, other_id) in wanted.items():
        existing = cases.get(cid)
        was_active = bool(existing and existing.get("status") == "active")
        sev = wc.compute_severity(c, base, other_id)
        case = wc.register_worry(c, subject, sev, f"scan:{name}", note, world, tags=tags, summary=note)
        if case is None:
            continue
        (result["refreshed"] if was_active else result["opened"]).append(cid)
    for cid, case in list(cases.items()):
        if case.get("status") == "active" and str(case.get("origin", "")).startswith("scan:") and cid not in wanted:
            wc.close_case(c, cid, world, "resolved", "it's over")
            result["closed"].append(cid)
    return result
