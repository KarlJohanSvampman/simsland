"""
social/issues.py -- the problems people have with each other (design sections 6, 9, 11).

An issue is a perceived problem, not an established fact, and it persists: an argument about the dishes doesn't vanish
when the conversation ends -- frustration keeps building on it, and a talk days later picks the same issue back up.

    world["social_issues"][id] = {
        "id", "subject", "description", "category" (CATEGORIES),
        "involved_parties", "affected_parties", "created_by",
        "originating_event_id", "related_contract_id",
        "evidence": [{id, tick, kind, text, by, ref}],      what is known that bears on it
        "positions": {character id: IssuePosition},         each one's own reading of it
        "influences": {character id: [OpinionInfluence]},   who has been shaping that reading
        "status": open | dormant | resolved | reopened,
        "created_at", "resolved_at", "resolution",
        "conversation_ids", "confrontation_ids", "fight_ids",
        "events": [{tick, what, detail, ref}],
    }

    IssuePosition = {"character_id", "position" (their interpretation, in their words), "stance"
                     (favourable | opposed | neutral | uncertain), "confidence" 0..1, "emotional_investment" 0..1,
                     "evidence_ids", "source_ids", "last_updated", "basis" (observed | told | concluded)}

What actually happened (the world's records), what someone observed, what they believe, what they were told and what
they concluded stay apart: a position carries its basis and sources; evidence carries who supplied it.

Each involved character keeps a copy of their issues in c["issue_log"] (the Inspector's Issues tab).
"""

import copy
import uuid

from social.core import clamp, emit, now, chars, name

CATEGORIES = ("unmet_expectation", "broken_promise", "unfair_treatment", "disrespect", "personal_habit",
              "household_responsibility", "relationship_problem", "financial_dispute", "social_norm_violation",
              "ideological_disagreement", "interpersonal_boundary", "abuse_of_authority", "competition",
              "misunderstanding", "betrayal", "public_reputation", "dishonesty", "other")
STANCES = ("favourable", "opposed", "neutral", "uncertain")
LOG_CAP = 40
EVIDENCE_CAP = 40
EVENTS_CAP = 80
DORMANT_AFTER = 14 * 86400

# grievance event types (systems/grievances.py) -> the kind of problem they are
_GRIEVANCE_CATEGORY = {
    "insulted": "disrespect", "disrespected": "disrespect", "ignored_me": "disrespect", "excluded": "disrespect",
    "threatened": "interpersonal_boundary", "sexual_harassment": "interpersonal_boundary",
    "verbal_harassment": "interpersonal_boundary", "partner_harassed": "interpersonal_boundary",
    "ignored_rejection": "interpersonal_boundary", "restricted_freedom": "abuse_of_authority",
    "betrayed": "betrayal", "flirting_with_partner": "betrayal", "contract_violated": "broken_promise",
    "broke_promise": "broken_promise", "promised_errand_broken": "broken_promise",
    "ate_my_food": "personal_habit", "loud_at_night": "personal_habit", "left_mess": "household_responsibility",
    "neglected_plants": "household_responsibility", "family_dinner_skipped": "unmet_expectation",
    "stole": "financial_dispute", "favor_unreciprocated": "unfair_treatment", "resource_conflict": "competition",
    "lied": "dishonesty", "absence_lie_caught": "dishonesty", "absence_unresolved": "relationship_problem",
    "value_clash": "ideological_disagreement", "identity_shame": "social_norm_violation",
    "life_envy": "competition", "status_envy": "competition", "career_envy": "competition",
    "social_envy": "competition", "opportunity_envy": "competition", "romantic_envy": "competition",
    "romantic_rivalry": "competition", "team_rivalry": "competition", "partner_jealousy": "relationship_problem",
    "fight_loss_humiliation": "public_reputation", "witnessed_transgression": "social_norm_violation",
}


def category_for(event_type):
    return _GRIEVANCE_CATEGORY.get(str(event_type), "other")


def store(world):
    return world.setdefault("social_issues", {})


def get(world, iid):
    return (world.get("social_issues") or {}).get(iid)


# =========================================================
# LIFECYCLE
# =========================================================

def open_issue(world, subject, category, involved, created_by=None, affected=None, description=None,
               origin=None, contract_id=None, tick=None):
    iid = f"issue_{uuid.uuid4().hex[:8]}"
    issue = {
        "id": iid, "subject": str(subject or "something")[:90], "description": str(description or "")[:400],
        "category": category if category in CATEGORIES else "other",
        "involved_parties": sorted({p for p in involved if p}), "affected_parties": sorted({p for p in (affected or []) if p}),
        "created_by": created_by, "originating_event_id": origin, "related_contract_id": contract_id,
        "evidence": [], "positions": {}, "influences": {}, "status": "open",
        "created_at": tick if tick is not None else now(world), "resolved_at": None, "resolution": None,
        "last_activity": now(world), "conversation_ids": [], "confrontation_ids": [], "fight_ids": [], "events": [],
    }
    store(world)[iid] = issue
    event(world, issue, "opened", f"{issue['subject']} ({issue['category'].replace('_', ' ')})")
    emit("SocialIssueCreated", {"issue_id": iid, "parties": issue["involved_parties"], "category": issue["category"]})
    return issue


def between(world, a, b, status=("open", "reopened")):
    return [i for i in store(world).values() if a in i["involved_parties"] and b in i["involved_parties"]
            and (status is None or i["status"] in status)]


def _same_subject(x, y):
    x, y = str(x or "").lower(), str(y or "").lower()
    if not x or not y:
        return False
    if x == y or x in y or y in x:
        return True
    wx, wy = set(w for w in x.split() if len(w) > 3), set(w for w in y.split() if len(w) > 3)
    return bool(wx and wy and len(wx & wy) >= max(1, min(len(wx), len(wy)) // 2))


def find(world, a, b, subject=None, category=None, include_closed=False):
    pool = between(world, a, b, status=None if include_closed else ("open", "reopened", "dormant"))
    for i in sorted(pool, key=lambda i: -(i.get("last_activity") or 0)):
        if subject and _same_subject(i["subject"], subject):
            return i
    if category and category != "other":
        for i in sorted(pool, key=lambda i: -(i.get("last_activity") or 0)):
            if i["category"] == category and i["status"] != "resolved":
                return i
    return None


def find_or_open(world, involved, subject, category, created_by=None, **kw):
    a, b = (list(involved) + [None, None])[:2]
    issue = find(world, a, b, subject, category) if a and b else None
    if issue:
        if issue["status"] in ("dormant", "resolved"):
            reopen(world, issue, f"it came up again: {subject}")
        return issue, False
    return open_issue(world, subject, category, involved, created_by=created_by, **kw), True


def event(world, issue, what, detail=None, ref=None):
    issue["events"].append({"tick": now(world), "what": what, "detail": str(detail or "")[:200], "ref": ref})
    del issue["events"][:-EVENTS_CAP]
    issue["last_activity"] = now(world)
    sync(world, issue)


def resolve(world, issue, how, by=None):
    if issue["status"] == "resolved":
        return
    issue["status"] = "resolved"
    issue["resolved_at"] = now(world)
    issue["resolution"] = str(how)[:160]
    event(world, issue, "resolved", how, ref=by)
    from social import frustration
    for a in issue["involved_parties"]:
        c = chars(world).get(a)
        for b in issue["involved_parties"]:
            if c and b != a:
                frustration.calm(c, b, world, 0, issue_id=issue["id"], kind="resolved",
                                 cause=f"settled: {issue['subject']}")
    emit("SocialIssueUpdated", {"issue_id": issue["id"], "status": "resolved", "how": how})


def reopen(world, issue, why):
    issue["status"] = "reopened"
    issue["resolved_at"] = None
    event(world, issue, "reopened", why)
    emit("SocialIssueUpdated", {"issue_id": issue["id"], "status": "reopened", "why": why})


def resolve_between(world, a, b, how):
    for issue in between(world, a, b):
        resolve(world, issue, how)


def tick_dormancy(world):
    """An open issue nobody has touched in a while goes quiet (it isn't resolved; it can come back)."""
    t = now(world)
    for issue in store(world).values():
        if issue["status"] in ("open", "reopened") and t - (issue.get("last_activity") or t) > DORMANT_AFTER:
            issue["status"] = "dormant"
            event(world, issue, "went quiet", "nobody has brought it up in two weeks")


# =========================================================
# EVIDENCE AND POSITIONS
# =========================================================

def add_evidence(world, issue, kind, text, by=None, ref=None):
    """Something known that bears on the issue (an incident seen, a grievance, a violation, what someone said)."""
    if ref and any(e.get("ref") == ref for e in issue["evidence"]):
        return None
    ev = {"id": f"ev_{uuid.uuid4().hex[:6]}", "tick": now(world), "kind": kind, "text": str(text)[:200],
          "by": by, "ref": ref}
    issue["evidence"].append(ev)
    del issue["evidence"][:-EVIDENCE_CAP]
    event(world, issue, "evidence", f"{kind.replace('_', ' ')}: {text}", ref=ref)
    return ev


def position(issue, cid):
    return (issue.get("positions") or {}).get(cid)


def set_position(world, issue, cid, text=None, stance=None, confidence=None, investment=None, evidence_ids=None,
                 source_id=None, basis=None, said_to=None):
    """cid's own reading of the issue (in their words), revised -- not replaced by what anyone else thinks."""
    p = issue["positions"].get(cid) or {"character_id": cid, "position": "", "stance": "uncertain", "confidence": 0.4,
                                         "emotional_investment": 0.4, "evidence_ids": [], "source_ids": [],
                                         "last_updated": None, "basis": basis or "concluded", "history": []}
    changed = False
    if text and str(text).strip() and str(text).strip() != p["position"]:
        if p["position"]:
            p["history"].append({"tick": p["last_updated"], "position": p["position"], "stance": p["stance"]})
            del p["history"][:-10]
        p["position"] = str(text).strip()[:240]
        changed = True
    if stance in STANCES and stance != p["stance"]:
        p["stance"] = stance
        changed = True
    if confidence is not None:
        p["confidence"] = round(clamp(float(confidence), 0, 1), 2)
    if investment is not None:
        p["emotional_investment"] = round(clamp(float(investment), 0, 1), 2)
    for e in evidence_ids or []:
        if e not in p["evidence_ids"]:
            p["evidence_ids"].append(e)
    if source_id and source_id not in p["source_ids"]:
        p["source_ids"].append(source_id)
    if basis:
        p["basis"] = basis
    for heard in said_to or []:                      # who has heard them say it (and so knows their side)
        if heard != cid and heard not in p.setdefault("said_to", []):
            p["said_to"].append(heard)
    p["last_updated"] = now(world)
    issue["positions"][cid] = p
    if changed:
        event(world, issue, "position", f"{name(world, cid)}: {p['position']} ({p['stance']})")
    if cid not in issue["involved_parties"] and cid not in issue["affected_parties"]:
        issue.setdefault("bystanders", [])
        if cid not in issue["bystanders"]:
            issue["bystanders"].append(cid)
    sync(world, issue)
    return p


def record_influence(world, issue, observer_id, source_id, source_position, strength):
    """source told observer how they see the issue (design 11.1): kept per issue, and on the influence graph."""
    if not observer_id or not source_id or observer_id == source_id:
        return None
    observer = chars(world).get(observer_id)
    source = chars(world).get(source_id)
    if not observer or not source:
        return None
    trust = ((observer.get("relationships") or {}).get(source_id) or {}).get("trust") or 0
    entry = {"observer_id": observer_id, "source_id": source_id, "issue_id": issue["id"],
             "influence_strength": round(clamp(strength, 0, 1), 2), "source_position": str(source_position)[:200],
             "trust": trust, "evidence_ids": [], "last_influenced": now(world)}
    lst = issue["influences"].setdefault(observer_id, [])
    lst[:] = [x for x in lst if x["source_id"] != source_id] + [entry]
    try:
        from systems.influence import record_influence as graph
        graph(source, observer, round(strength, 2), world)
    except Exception:
        pass
    emit("OpinionInfluenced", {"observer_id": observer_id, "source_id": source_id, "issue_id": issue["id"],
                               "strength": entry["influence_strength"]})
    sync(world, issue)
    return entry


# =========================================================
# FILING
# =========================================================

def file_conversation(world, issue, conv_entry):
    if conv_entry["id"] not in issue["conversation_ids"]:
        issue["conversation_ids"].append(conv_entry["id"])
        event(world, issue, "conversation", (conv_entry.get("tags") or {}).get("subject"), ref=conv_entry["id"])
    ids = conv_entry.setdefault("issue_ids", [])
    if issue["id"] not in ids:
        ids.append(issue["id"])
    if issue["status"] == "dormant":
        issue["status"] = "open"


def file_fight(world, fight):
    """A fight between two people goes on the issue between them it was about (else their most recent open one,
    else a new one about what the fight was over)."""
    parties = [p for p in fight.get("parties") or [] if p in chars(world)]
    if len(parties) < 2:
        return None
    a, b = parties[:2]
    issue = find(world, a, b, fight.get("topic")) or \
        max(between(world, a, b), key=lambda i: i.get("last_activity") or 0, default=None)
    if issue is None:
        issue = open_issue(world, fight.get("topic") or "a fight", "relationship_problem", parties,
                           created_by=fight.get("aggressor"), tick=fight.get("tick"))
    if fight.get("id") not in issue["fight_ids"]:
        issue["fight_ids"].append(fight.get("id"))
        event(world, issue, "fight", f"{fight.get('topic')}: {str(fight.get('outcome', '')).replace('_', ' ')}"
              + (f", peaked at {fight['peak'].replace('_', ' ')}" if fight.get("peak") else ""), ref=fight.get("id"))
    return issue


def sync(world, issue):
    """Each character involved (or holding a position on it) keeps a copy for the Inspector."""
    who = set(issue["involved_parties"]) | set(issue["affected_parties"]) | set(issue.get("positions") or {})
    for cid in who:
        c = chars(world).get(cid)
        if not c:
            continue
        log = [i for i in c.get("issue_log") or [] if i["id"] != issue["id"]]
        log.append(copy.deepcopy(issue))
        log.sort(key=lambda i: i.get("created_at") or 0)
        c["issue_log"] = log[-LOG_CAP:]


def summary(world, issue, me=None):
    """One line for a character's prompt."""
    others = [name(world, p) for p in issue["involved_parties"] if p != me]
    mine = position(issue, me) if me else None
    line = f"{issue['subject']} ({issue['category'].replace('_', ' ')}, with {', '.join(others) or 'nobody'}, {issue['status']})"
    if mine and mine.get("position"):
        line += f" -- you think: {mine['position']}"
    for pid, p in (issue.get("positions") or {}).items():
        if pid != me and p.get("position") and me in (p.get("said_to") or []):
            line += f"; {name(world, pid).split(' ')[0]} has said: {p['position']}"
    return line
