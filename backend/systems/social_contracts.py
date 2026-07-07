"""
systems/social_contracts.py

Social contracts are agreements between two or more characters that
define mutual behavioural commitments. They are created by the
negotiation phase of the conflict pipeline.

Violation checking runs on a slow cadence and emits 'contract_violated'
when a term is broken, feeding back into the grievance system with
extra weight (betrayal of an explicit agreement hurts more than a
fresh incident).

Contract terms use 'check_type' to select the violation detector:
  behavior_tag  — the party performed an action tagged as forbidden
  resource_state — a household resource is in a bad state
  activity      — the party performed (or failed to perform) an activity
  schedule      — the party violated a time-of-day commitment
  manual        — checked only when explicitly reported
"""

import uuid


# ── Term checkers ─────────────────────────────────────────────────────────

def _check_behavior_tag(term, party_char, world):
    """True if the character recently performed the forbidden behaviour."""
    forbidden = term.get("params", {}).get("forbidden_tag")
    recent    = party_char.get("recent_behavior_tags", [])
    return forbidden and forbidden in recent


def _check_resource_state(term, party_char, world):
    """True if a household resource is below the committed minimum."""
    params  = term.get("params", {})
    hid     = party_char.get("household_id")
    if not hid:
        return False
    hh      = world.get("households", {}).get(hid, {})
    resource = params.get("resource")
    minimum  = params.get("minimum", 0)
    current  = hh.get("storage", {}).get(resource, 0)
    return current < minimum


def _check_activity(term, party_char, world):
    """True if the character is (or recently was) doing a forbidden activity."""
    forbidden = term.get("params", {}).get("forbidden_activity")
    current   = party_char.get("activity", {}).get("type")
    return forbidden and current == forbidden


def _check_schedule(term, party_char, world):
    """True if character is doing a forbidden activity during a restricted window."""
    params   = term.get("params", {})
    cal      = world.get("calendar", {})
    hour     = cal.get("hour", 0)
    start_h  = params.get("quiet_start", 22)
    end_h    = params.get("quiet_end",    8)
    in_window = (hour >= start_h) or (hour < end_h)
    if not in_window:
        return False
    forbidden = params.get("forbidden_activity")
    current   = party_char.get("activity", {}).get("type")
    return forbidden and current == forbidden


_CHECKERS = {
    "behavior_tag":   _check_behavior_tag,
    "resource_state": _check_resource_state,
    "activity":       _check_activity,
    "schedule":       _check_schedule,
    "manual":         lambda *_: False,
}


# ── Core API ──────────────────────────────────────────────────────────────

def create_contract(parties, terms, world, created_by_conflict=None):
    """
    Create a new social contract and store it on the world.
    parties  — list of character IDs
    terms    — list of {party, commitment, check_type, params}
    """
    cid = f"contract_{uuid.uuid4().hex[:8]}"
    contract = {
        "id":                  cid,
        "parties":             list(parties),
        "terms":               terms,
        "created_tick":        world["tick"],
        "expires_tick":        None,
        "status":              "active",   # active | broken | expired | renegotiating
        "violations":          [],
        "created_by_conflict": created_by_conflict,
    }
    world.setdefault("social_contracts", {})[cid] = contract

    # Attach contract reference to each party
    for pid in parties:
        char = world.get("characters", {}).get(pid)
        if char:
            char.setdefault("social_contract_ids", []).append(cid)

    return contract


def get_contracts_for_character(char_id, world):
    return [
        c for c in world.get("social_contracts", {}).values()
        if char_id in c["parties"] and c["status"] == "active"
    ]


def report_violation(contract, violator_id, term, world):
    """
    Mark a violation and emit 'contract_violated' so grievances are updated.
    Guards against re-firing the same violation within 60 ticks.
    """
    from core.event_bus import emit

    last = contract.get("_last_violation_tick", {}).get(violator_id, -999)
    if world["tick"] - last < 60:
        return  # cooldown

    contract.setdefault("violations", []).append({
        "violator":    violator_id,
        "commitment":  term["commitment"],
        "tick":        world["tick"],
    })
    contract.setdefault("_last_violation_tick", {})[violator_id] = world["tick"]

    # Notify the other parties
    for pid in contract["parties"]:
        if pid != violator_id:
            emit("contract_violated", {
                "contract_id":  contract["id"],
                "violator_id":  violator_id,
                "victim_id":    pid,
                "commitment":   term["commitment"],
                "event_type":   "contract_violated",
            })

    # Queue phone/text escalation if authority contract
    try:
        queue_violation_escalation(contract, violator_id, world)
    except Exception:
        pass


def check_contract_violations(world):
    """
    Called from sim_loop on a slow cadence. Checks every active term
    in every active contract.
    """
    characters = world.get("characters", {})
    for contract in list(world.get("social_contracts", {}).values()):
        if contract["status"] != "active":
            continue
        if contract.get("expires_tick") and world["tick"] > contract["expires_tick"]:
            contract["status"] = "expired"
            continue
        for term in contract.get("terms", []):
            party_char = characters.get(term["party"])
            if not party_char:
                continue
            checker = _CHECKERS.get(term.get("check_type", "manual"), lambda *_: False)
            if checker(term, party_char, world):
                report_violation(contract, term["party"], term, world)


def resolve_contract(contract_id, world, outcome="fulfilled"):
    """Manually close a contract (fulfilled, broken, or cancelled)."""
    contract = world.get("social_contracts", {}).get(contract_id)
    if contract:
        contract["status"] = outcome
        contract["resolved_tick"] = world["tick"]


# ═══════════════════════════════════════════════════════════════════════════
# AUTHORITY CONTRACT SYSTEM
# Extends the base contract engine with:
#   - Compliance history + weighted scoring
#   - Verbal negotiation state machine
#   - Departure / curfew / announcement check types
#   - Violation escalation (phone → in-person discipline)
# ═══════════════════════════════════════════════════════════════════════════

import random

# ── Compliance scoring ────────────────────────────────────────────────────

RECENCY_HALF_LIFE = 720   # ticks (~1 sim week); recent events weighted more

def record_compliance(contract, subject_id, outcome, world, delta=0):
    """
    Log a compliance event on a contract.
    outcome: "complied" | "violated" | "partial"
    delta: minutes early (negative) or late (positive) for schedule contracts
    """
    entry = {
        "tick":       world.get("tick", 0),
        "subject_id": subject_id,
        "outcome":    outcome,
        "delta":      delta,
    }
    contract.setdefault("compliance_history", []).append(entry)
    contract["compliance_history"] = contract["compliance_history"][-50:]
    _recompute_compliance_score(contract, world)


def _recompute_compliance_score(contract, world):
    """
    Weighted compliance score 0-1.  Recent events count more.
    Score drives authority willingness to negotiate and
    whether a new contract offer is accepted.
    """
    history = contract.get("compliance_history", [])
    if not history:
        contract["compliance_score"] = 0.5
        return

    now   = world.get("tick", 0)
    total_w = 0.0
    score_w = 0.0
    for e in history:
        age    = max(0, now - e.get("tick", now))
        weight = 0.5 ** (age / RECENCY_HALF_LIFE)
        total_w += weight
        if e["outcome"] == "complied":
            score_w += weight * 1.0
        elif e["outcome"] == "partial":
            score_w += weight * 0.4
        # violated = 0 contribution

    contract["compliance_score"] = round(score_w / total_w, 3) if total_w else 0.5


# ── Negotiation state machine ─────────────────────────────────────────────

CNEG_IDLE        = "idle"
CNEG_PROPOSED    = "proposed"
CNEG_ACCEPTED    = "accepted"
CNEG_REJECTED    = "rejected"
CNEG_COUNTERED   = "countered"

def init_contract_negotiation(contract):
    contract.setdefault("negotiation", {
        "state":          CNEG_IDLE,
        "proposed_by":    None,
        "proposed_terms": None,   # modified term dict (e.g. new deadline_hour)
        "exchange_offer": None,   # what subject offers in return
        "last_tick":      0,
    })


def propose_contract_modification(contract, subject_id, proposed_terms,
                                   exchange_offer, world):
    """
    Subject (e.g. teen) proposes modified terms.
    proposed_terms: partial dict of term overrides, e.g. {"deadline_hour": 24}
    exchange_offer: string describing what they offer ("I'll cook dinner all week")
    """
    init_contract_negotiation(contract)
    if contract["negotiation"]["state"] == CNEG_PROPOSED:
        return {"ok": False, "reason": "already_negotiating"}

    contract["negotiation"].update({
        "state":          CNEG_PROPOSED,
        "proposed_by":    subject_id,
        "proposed_terms": proposed_terms,
        "exchange_offer": exchange_offer,
        "last_tick":      world.get("tick", 0),
    })
    # Add to world pending queue so authority AI sees it
    world.setdefault("pending_contract_proposals", []).append({
        "contract_id": contract["id"],
        "subject_id":  subject_id,
        "tick":        world.get("tick", 0),
    })
    return {"ok": True}


def authority_responds_to_modification(contract, authority_id, response,
                                        counter_terms=None, world=None):
    """
    Authority accepts, rejects, or counters the proposed modification.
    response: "accept" | "reject" | "counter"
    """
    init_contract_negotiation(contract)
    neg = contract["negotiation"]
    if neg["state"] != CNEG_PROPOSED:
        return {"ok": False, "reason": "no_active_proposal"}

    tick = world.get("tick", 0) if world else 0

    if response == "accept":
        # Apply the proposed terms to the contract
        proposed = neg.get("proposed_terms") or {}
        for term in contract.get("terms", []):
            term.get("params", {}).update(proposed)
        # Log the exchange as a new obligation contract
        exchange = neg.get("exchange_offer")
        if exchange:
            contract.setdefault("exchange_obligations", []).append({
                "obligation": exchange,
                "promised_by": neg["proposed_by"],
                "tick":        tick,
                "fulfilled":   False,
            })
        neg["state"] = CNEG_ACCEPTED
        record_compliance(contract, neg["proposed_by"], "complied",
                          world or {"tick": tick})

    elif response == "reject":
        neg["state"] = CNEG_REJECTED

    elif response == "counter":
        neg["state"]          = CNEG_COUNTERED
        neg["proposed_terms"] = counter_terms or neg["proposed_terms"]
        neg["proposed_by"]    = authority_id

    neg["last_tick"] = tick
    return {"ok": True, "result": response}


def ai_authority_decision(contract, authority, subject, world):
    """
    AI decision: should authority accept the proposed modification?
    Returns "accept" | "reject" | "counter"

    Weighs:
      - Compliance score (recent track record)
      - Quality / reasonableness of exchange offer
      - Authority's strictness traits
      - How big the ask is (how much they want to change)
    """
    neg   = contract.get("negotiation", {})
    score = contract.get("compliance_score", 0.5)
    offer = neg.get("exchange_offer", "")

    # Base acceptance from compliance history
    accept_prob = 0.20 + score * 0.55   # 0.20-0.75 range

    # Exchange offer boosts acceptance
    if offer:
        offer_lower = offer.lower()
        if any(w in offer_lower for w in ("clean", "cook", "wash", "tidy", "homework")):
            accept_prob += 0.12
        if any(w in offer_lower for w in ("week", "month", "always")):
            accept_prob += 0.08
        if len(offer) > 20:   # detailed offer = more credible
            accept_prob += 0.05

    # Authority strictness
    traits = set(authority.get("traits", []) + authority.get("personality_traits", []))
    if "strict" in traits or "authoritarian" in traits:
        accept_prob -= 0.20
    if "lenient" in traits or "permissive" in traits:
        accept_prob += 0.15
    if "fair" in traits:
        accept_prob += 0.05

    # How big is the ask?
    proposed = neg.get("proposed_terms", {})
    original_hour = None
    for term in contract.get("terms", []):
        if "deadline_hour" in term.get("params", {}):
            original_hour = term["params"]["deadline_hour"]
    if original_hour is not None and "deadline_hour" in proposed:
        diff = proposed["deadline_hour"] - original_hour
        accept_prob -= diff * 0.04  # -4% per hour extension requested

    accept_prob = max(0.02, min(0.92, accept_prob))
    roll = random.random()

    if roll < accept_prob:
        return "accept"
    elif roll < accept_prob + 0.20:
        return "counter"
    else:
        return "reject"


# ── New check types ───────────────────────────────────────────────────────

def _check_curfew(term, party_char, world):
    """
    True if character is not home by deadline_hour.
    Only fires when calendar hour == deadline_hour and char is away from home.
    """
    params      = term.get("params", {})
    cal         = world.get("calendar", {})
    hour        = cal.get("hour", 0)
    deadline    = params.get("deadline_hour", 22)
    if hour != deadline:
        return False
    home_id  = party_char.get("home_id") or party_char.get("household_id")
    cur_loc  = party_char.get("current_location")
    homes    = world.get("homes", {})
    home     = homes.get(home_id, {})
    home_loc = home.get("location_id") or home_id
    return cur_loc != home_loc


def _check_announce_departure(term, party_char, world):
    """
    True if character departed without satisfying any allowed announcement method.
    Allowed methods: verbal (told an authorized recipient), note, text, call.
    Any authorized_recipient receiving the message satisfies the contract.
    """
    if not party_char.get("_departed_this_tick"):
        return False
    # If _announced_departure is set by any method, contract is satisfied
    if party_char.get("_announced_departure"):
        return False
    # Also check if a note was left this tick
    if party_char.get("_left_note_this_tick"):
        return False
    return True


def _check_presence_required(term, party_char, world):
    """True if character is not at required_location during required window."""
    params   = term.get("params", {})
    cal      = world.get("calendar", {})
    hour     = cal.get("hour", 0)
    req_loc  = params.get("required_location")
    req_start = params.get("start_hour", 0)
    req_end   = params.get("end_hour",   8)
    in_window = req_start <= hour < req_end
    if not in_window:
        return False
    cur_loc = party_char.get("current_location")
    return cur_loc != req_loc


# Patch new checkers into the existing map
_CHECKERS["curfew"]             = _check_curfew
_CHECKERS["announce_departure"] = _check_announce_departure
_CHECKERS["presence_required"]  = _check_presence_required


# ── Authority contract factory ────────────────────────────────────────────

def create_authority_contract(authority_id, subject_id, contract_type,
                               params, world, expires_ticks=None):
    """
    Convenience factory for common authority→subject contracts.
    contract_type: "curfew" | "announce_departure" | "chore" | "grounding" | "presence_required"
    """
    TEMPLATES = {
        "curfew": {
            "commitment":  "Be home by the agreed time",
            "check_type":  "curfew",
        },
        "announce_departure": {
            "commitment":  "Tell an authorized person before leaving",
            "check_type":  "announce_departure",
            # params may include: authorized_recipients (list of char IDs),
            #   allowed_methods (list: verbal|note|text|call)
        },
        "chore": {
            "commitment":  params.get("commitment", "Complete assigned chore"),
            "check_type":  "manual",
        },
        "grounding": {
            "commitment":  "Remain at home during grounding period",
            "check_type":  "presence_required",
        },
        "presence_required": {
            "commitment":  "Be present at required location during agreed hours",
            "check_type":  "presence_required",
        },
        "homework_before_play": {
            "commitment":  "Complete homework before leisure activities",
            "check_type":  "behavior_tag",
        },
    }

    tpl = TEMPLATES.get(contract_type, {
        "commitment": contract_type,
        "check_type": "manual",
    })

    term = {
        "party":       subject_id,
        "commitment":  tpl["commitment"],
        "check_type":  tpl["check_type"],
        "params":      dict(params),
        "authority_id": authority_id,
    }

    contract = create_contract(
        parties=[authority_id, subject_id],
        terms=[term],
        world=world,
    )
    contract["contract_type"]  = contract_type
    contract["authority_id"]   = authority_id
    contract["subject_id"]     = subject_id
    contract["compliance_score"] = 0.5
    contract["compliance_history"] = []
    init_contract_negotiation(contract)

    if expires_ticks:
        contract["expires_tick"] = world.get("tick", 0) + expires_ticks

    return contract


# ── Violation escalation ──────────────────────────────────────────────────

def queue_violation_escalation(contract, violator_id, world):
    """
    When a contract is violated and no explanation was given,
    queue the authority to contact the violator.
    Priority: phone_call → text (if no answer) → in-person when they return.
    """
    authority_id = contract.get("authority_id")
    if not authority_id:
        return

    chars = world.get("characters", {})
    authority = chars.get(authority_id)
    violator  = chars.get(violator_id)
    if not authority or not violator:
        return

    # Mark violator as "unreachable pending" so inquiry doesn't repeat
    violator.setdefault("pending_authority_contact", []).append({
        "authority_id": authority_id,
        "contract_id":  contract["id"],
        "tick":         world.get("tick", 0),
        "step":         "call",   # call → text → in_person
        "announced":    False,
    })

    # Queue phone call intention on authority
    authority.setdefault("intention_queue", []).append({
        "type":      "phone_call",
        "target_id": violator_id,
        "reason":    "contract_violation_inquiry",
        "contract_id": contract["id"],
        "priority":  8,
        "tick":      world.get("tick", 0),
    })
