"""
social/contracts.py -- explicit agreements and implicit expectations (design section 8).

Contracts are kept in world["social_contracts"] (systems/social_contracts.py, which also checks the terms it can check
automatically and handles authority contracts). This module gives them the shape of the design and the lifecycle:

    contract += {"title", "description", "created_by", "conditions", "effective_at", "expires_at",
                 "state": proposed | negotiated | accepted | active | violated | disputed | renegotiating |
                          fulfilled | expired | terminated,
                 "origin_conversation_id", "origin_confrontation_id", "issue_id", "revision_history",
                 "violation_records": [ContractViolation]}
    term     += {"id", "responsible_party", "obligation", "frequency", "deadline", "conditions", "consequences",
                 "status": pending | kept | violated | disputed}
    ContractViolation = {"id", "contract_id", "term_id", "responsible_party", "observed_by", "violation_type",
                         "evidence", "severity", "timestamp", "disputed"}

("status" stays the older field the checkers read: "active" while the agreement is in force, whatever its state.)

An agreement comes out of a conversation the AI read as reaching one (social/discourse.py); a renegotiation makes a
new version and keeps the old one in revision_history. A violation doesn't imply guilt: it can be disputed, which
makes it count for less.

Implicit expectations are what someone assumes another should do without anything having been agreed:

    c["implicit_expectations"][other id] = [{"expectation", "since", "issue_id"}]

A confrontation about an expectation is told which kind it is (social/context.py): "you expect it" is not "they
agreed to it".
"""

import copy
import uuid

from social.core import chars, emit, now, name

STATES = ("proposed", "negotiated", "accepted", "active", "violated", "disputed", "renegotiating", "fulfilled",
          "expired", "terminated")
IN_FORCE = ("accepted", "active", "violated", "disputed", "renegotiating")


def get(world, kid):
    return (world.get("social_contracts") or {}).get(kid)


def normalize(k):
    """Give an older contract the design's fields (idempotent)."""
    k.setdefault("title", None)
    k.setdefault("description", "")
    k.setdefault("created_by", None)
    k.setdefault("conditions", [])
    k.setdefault("effective_at", k.get("created_tick"))
    k.setdefault("expires_at", k.get("expires_tick"))
    k.setdefault("origin_conversation_id", None)
    k.setdefault("origin_confrontation_id", k.get("created_by_conflict"))
    k.setdefault("issue_id", None)
    k.setdefault("revision_history", [])
    k.setdefault("violation_records", [])
    if "state" not in k:
        k["state"] = {"active": "active", "broken": "violated", "expired": "expired", "renegotiating": "renegotiating",
                      "fulfilled": "fulfilled", "cancelled": "terminated"}.get(k.get("status"), "active")
    for i, t in enumerate(k.get("terms") or []):
        t.setdefault("id", f"term_{i + 1}")
        t.setdefault("responsible_party", t.get("party"))
        t.setdefault("obligation", str(t.get("commitment") or "").replace("_", " "))
        t.setdefault("frequency", None)
        t.setdefault("deadline", None)
        t.setdefault("conditions", [])
        t.setdefault("consequences", [])
        t.setdefault("status", "pending")
    if not k["title"]:
        k["title"] = "; ".join(t["obligation"] for t in k.get("terms") or [])[:80] or "an agreement"
    return k


def between(world, people, in_force=True):
    people = set(people)
    out = []
    for k in (world.get("social_contracts") or {}).values():
        if len(people & set(k.get("parties") or [])) >= min(2, len(people)):
            normalize(k)
            if not in_force or k["state"] in IN_FORCE:
                out.append(k)
    return out


def create(world, parties, terms, title=None, created_by=None, conversation_id=None, confrontation_id=None,
           issue_id=None, description=None):
    """An agreement the parties reached (accepted, and in force from now)."""
    from systems.social_contracts import create_contract
    legacy = []
    for i, t in enumerate(terms):
        legacy.append({"party": t["responsible_party"], "commitment": t["obligation"], "check_type": "manual",
                       "params": {}, "id": f"term_{i + 1}", "responsible_party": t["responsible_party"],
                       "obligation": t["obligation"], "frequency": t.get("frequency"), "deadline": t.get("deadline"),
                       "conditions": t.get("conditions") or [], "consequences": t.get("consequences") or [],
                       "status": "pending"})
    k = create_contract(parties, legacy, world, created_by_conflict=confrontation_id)
    normalize(k)
    k.update(title=(title or k["title"])[:80], description=str(description or "")[:300], created_by=created_by,
             origin_conversation_id=conversation_id, origin_confrontation_id=confrontation_id, issue_id=issue_id,
             state="active")
    if issue_id:
        from social import issues as I
        issue = I.get(world, issue_id)
        if issue:
            issue["related_contract_id"] = k["id"]
            I.event(world, issue, "agreement", k["title"], ref=k["id"])
    for p in parties:
        c = chars(world).get(p)
        if c:
            _drop_implicit(c, [o for o in parties if o != p], k)
    emit("SocialContractProposed", {"contract_id": k["id"], "parties": list(parties)})
    emit("SocialContractAccepted", {"contract_id": k["id"], "parties": list(parties)})
    emit("social_contract_created", {"contract_id": k["id"], "parties": list(parties), "terms": legacy})
    return k


def renegotiate(world, kid, terms, conversation_id=None, by=None, reason=None):
    k = get(world, kid)
    if not k:
        return None
    normalize(k)
    k["revision_history"].append({"tick": now(world), "terms": copy.deepcopy(k["terms"]), "state": k["state"],
                                  "by": by, "reason": reason, "conversation_id": conversation_id})
    new_terms = []
    for i, t in enumerate(terms):
        new_terms.append({"party": t["responsible_party"], "commitment": t["obligation"], "check_type": "manual",
                          "params": {}, "id": f"term_{len(k['revision_history'])}_{i + 1}",
                          "responsible_party": t["responsible_party"], "obligation": t["obligation"],
                          "frequency": t.get("frequency"), "deadline": None, "conditions": [], "consequences": [],
                          "status": "pending"})
    k["terms"] = new_terms
    k["state"] = "active"
    k["status"] = "active"
    emit("SocialContractRenegotiated", {"contract_id": kid, "by": by})
    return k


def record_violation(world, k, term, responsible_id, observed_by=None, violation_type="missed", evidence=None,
                     severity=None, disputed=False):
    """A ContractViolation on the record (systems/social_contracts.report_violation calls this; so does the AI's
    reading of a conversation where someone says it wasn't kept)."""
    normalize(k)
    v = {"id": f"viol_{uuid.uuid4().hex[:6]}", "contract_id": k["id"], "term_id": (term or {}).get("id"),
         "responsible_party": responsible_id, "observed_by": list(observed_by or []),
         "violation_type": violation_type, "evidence": str(evidence or "")[:200],
         "severity": severity if severity is not None else (5 if disputed else 10), "timestamp": now(world),
         "disputed": bool(disputed)}
    k["violation_records"].append(v)
    del k["violation_records"][:-40]
    if term:
        term["status"] = "disputed" if disputed else "violated"
    k["state"] = "disputed" if disputed else "violated"
    emit("SocialContractViolated", {"contract_id": k["id"], "violation_id": v["id"], "responsible_id": responsible_id,
                                    "disputed": bool(disputed)})
    return v


def violation(world, k, responsible_id, what, observed_by=None, disputed=False, evidence=None):
    """Someone didn't keep it (or is said not to have). Goes through the usual path (memories, the other party
    woken, a grievance -- which feeds the issue and their frustration) and is recorded as a ContractViolation."""
    normalize(k)
    term = next((t for t in k["terms"] if t.get("responsible_party") == responsible_id), None) or \
        {"party": responsible_id, "commitment": what, "id": None}
    from systems.social_contracts import report_violation
    k["_pending_violation"] = {"disputed": disputed, "evidence": evidence or what, "observed_by": observed_by}
    report_violation(k, responsible_id, term, world)
    k.pop("_pending_violation", None)


def kept(world, k, responsible_id, term_id=None):
    normalize(k)
    for t in k["terms"]:
        if t.get("responsible_party") == responsible_id and (term_id is None or t["id"] == term_id):
            t["status"] = "kept"
    if k["state"] in ("violated", "disputed"):
        k["state"] = "active"
    from social import standing
    for p in k["parties"]:
        if p != responsible_id and chars(world).get(p):
            standing.change(chars(world)[p], responsible_id, world, "contract_kept", cause=f"kept to: {k['title']}")


def terminate(world, k, how="terminated"):
    normalize(k)
    k["state"] = how if how in STATES else "terminated"
    k["status"] = {"fulfilled": "fulfilled", "expired": "expired"}.get(how, "cancelled")


# ---- implicit expectations ----------------------------------------------------------------------------------------

def expect(world, c, other_id, expectation, issue_id=None):
    """c assumes other_id should do this -- nothing has been agreed."""
    lst = c.setdefault("implicit_expectations", {}).setdefault(other_id, [])
    if any(e["expectation"].lower() == str(expectation).lower() for e in lst):
        return
    lst.append({"expectation": str(expectation)[:160], "since": now(world), "issue_id": issue_id})
    del lst[:-8]


def _drop_implicit(c, others, k):
    for o in others:
        lst = (c.get("implicit_expectations") or {}).get(o) or []
        words = " ".join(t["obligation"].lower() for t in k["terms"])
        lst[:] = [e for e in lst if not any(w in words for w in e["expectation"].lower().split() if len(w) > 4)]


def context_lines(world, c, other_id):
    out = []
    for k in between(world, [c["id"], other_id]):
        mine = [t["obligation"] for t in k["terms"] if t.get("responsible_party") == c["id"]]
        theirs = [t["obligation"] for t in k["terms"] if t.get("responsible_party") == other_id]
        bits = []
        if theirs:
            bits.append(f"{name(world, other_id).split(' ')[0]} agreed to {', '.join(theirs)}")
        if mine:
            bits.append(f"you agreed to {', '.join(mine)}")
        state = "" if k["state"] == "active" else f" ({k['state']})"
        out.append(f"Agreement '{k['title']}'{state}: " + "; ".join(bits))
    for e in (c.get("implicit_expectations") or {}).get(other_id) or []:
        out.append(f"You expect {name(world, other_id).split(' ')[0]} to {e['expectation']} -- "
                   "though it was never actually agreed.")
    return out
