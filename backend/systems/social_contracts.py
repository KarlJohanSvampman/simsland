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
