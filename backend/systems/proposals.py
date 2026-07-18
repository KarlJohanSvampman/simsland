"""
systems/proposals.py

Unified propose/respond negotiation engine for anything shaped like "one
character proposes something to N others, who can accept, decline, or (for
chore and social-ask proposals) counter with different details." Three
kinds share this one engine rather than being near-duplicate modules:

  "chore"           — propose doing a household chore together (e.g. "let's
                       cook dinner"); recipients may accept, decline, or
                       counter-propose different params (a different time,
                       a different recipe/chore). Resolves to a participant
                       list that starts the chore via systems/task_process.py.
  "recurring_offer" — after an enjoyed joint chore, offer to turn it into a
                       recurring social contract. Accept/decline only, no
                       counter-proposing a schedule makes sense here.
  "social_ask"      — a general negotiation between two characters over
                       anything (a favor, money, forgiveness, plans) — the
                       conversation-level counterpart to "chore", with no
                       household/building gate at all (see
                       propose_social_ask()). Recipients may accept,
                       decline, or counter, same as chores. Resolution has
                       no special hand-off (unlike chore/recurring_offer) —
                       it's visible via _build_proposal_context() and the
                       accepted/declined outcome is enough on its own.
  "request"         — like social_ask, but checked against the recipient's
                       systems/social_rules.py standing policies first (see
                       propose_request()). When a rule cleanly resolves it,
                       the caller (action_router.py) auto-responds on the
                       recipient's behalf immediately, no LLM turn needed;
                       otherwise it behaves exactly like social_ask.

Built after finding the one existing negotiation precedent in this
codebase — systems/intimacy.py's touch-proposal system (hug/kiss/etc.) —
has three real, confirmed bugs this engine deliberately does not repeat:

  1. Its context-surfacing function is defined but never wired into
     context_builder.py::build_context() — incoming proposals are
     genuinely invisible to the recipient's LLM; resolution happens via a
     tick-based probability sweep instead of real AI choice. This engine's
     context function IS wired in (see context_builder.py).
  2. Its action types are missing from action_validator.py's
     VALID_ACTIONS — silently dropped before ever reaching the router from
     the live agent loop. propose_chore/respond_chore are registered
     there (see action_validator.py).
  3. Its locality gate checks current_location/characters_by_location,
     fields nothing in this codebase ever writes — always silently
     passes regardless of real proximity. This engine gates on
     c["building_id"], the one field movement.py actually keeps live.

Resolution rule for "chore" proposals (genuinely new territory — no
existing precedent to extend; intimacy.py's negotiation and
social_contracts.py's modification-response are both strictly two-party):

  - Lock-in on first non-counter response: once a recipient accepts or
    declines, that's final. Stops one still-countering character from
    blocking others who already answered.
  - Proposer-mediated reconciliation, not auto-merge: recipients' counters
    are proposals TO THE PROPOSER, not to each other. Each round the
    proposer sees all pending counters and decides new params for the
    next round; only still-countering/pending recipients get re-asked.
  - Shared round cap (no per-character cap needed, since lock-in already
    prevents holdup).
  - Timeout fallback is decline, never auto-accept — auto-binding someone
    to terms they never confirmed would be the exact "consent bypassed by
    a heuristic" failure this engine exists to avoid repeating.
"""

from uuid import uuid4

MAX_ROUNDS = 3


# =========================================================
# PROPOSE
# =========================================================

def propose(proposer, recipients, kind, chore_id, params, world):
    """recipients: list of character dicts (not ids) already filtered to
    who should be asked — see propose_chore_to_household() below for the
    household/locality-aware convenience wrapper most callers should use
    instead of calling this directly."""
    proposal = {
        "id": str(uuid4()),
        "kind": kind,
        "household_id": proposer.get("household_id"),
        "proposer_id": proposer["id"],
        "chore_id": chore_id,
        "params": dict(params or {}),
        "recipients": [r["id"] for r in recipients],
        "responses": {r["id"]: "pending" for r in recipients},
        "counter_params": {},
        "round": 0,
        "max_rounds": MAX_ROUNDS,
        "created_tick": world.get("tick", 0),
        "status": "open",
    }
    world.setdefault("proposals", {})[proposal["id"]] = proposal
    return proposal


def propose_chore_to_household(proposer, world, chore_id, params, kind="chore"):
    """Convenience wrapper: validates the proposer is actually somewhere
    their household owns (proposer["building_id"] in
    household["building_ids"]) — a validity gate, separate from picking
    recipients — then defaults recipients to household members sharing
    the proposer's current building (c["building_id"], the only
    live-maintained spatial field; NOT current_location, which nothing in
    this codebase ever writes despite reading as a locality check
    elsewhere)."""
    household_id = proposer.get("household_id")
    household = world.get("households", {}).get(household_id)
    if not household:
        return {"ok": False, "reason": "no_household"}

    if proposer.get("building_id") not in household.get("building_ids", []):
        return {"ok": False, "reason": "not_at_home"}

    characters = world.get("characters", {})
    recipients = [
        characters[mid] for mid in household.get("members", [])
        if mid != proposer["id"]
        and mid in characters
        and characters[mid].get("building_id") == proposer.get("building_id")
    ]
    if not recipients:
        return {"ok": False, "reason": "no_one_to_ask"}

    proposal = propose(proposer, recipients, kind, chore_id, params, world)
    return {"ok": True, "proposal": proposal}


# =========================================================
# RESPOND
# =========================================================

def respond(recipient, world, proposal_id, response, counter_params=None):
    proposal = world.get("proposals", {}).get(proposal_id)
    if not proposal or proposal["status"] != "open":
        return {"ok": False, "reason": "no_active_proposal"}

    rid = recipient["id"]
    if rid not in proposal["responses"]:
        return {"ok": False, "reason": "not_a_recipient"}

    current = proposal["responses"][rid]
    if current in ("accept", "decline"):
        # Locked in — further calls from this character are rejected so
        # one still-countering recipient can't reopen a decision another
        # recipient already made.
        return {"ok": False, "reason": "already_resolved"}

    if response == "counter":
        if proposal["kind"] not in ("chore", "social_ask", "request"):
            return {"ok": False, "reason": "counter_not_supported_for_this_kind"}
        proposal["responses"][rid] = "counter"
        proposal["counter_params"][rid] = dict(counter_params or {})
    elif response in ("accept", "decline"):
        proposal["responses"][rid] = response
    else:
        return {"ok": False, "reason": "unknown_response"}

    _maybe_resolve(proposal, world)
    return {"ok": True, "state": proposal["responses"][rid]}


def proposer_advance_round(proposer, world, proposal_id, new_params=None):
    """Called by the proposer to react to a round of counters: optionally
    revises params for the next round (new_params, applied to still-
    pending/countering recipients only — anyone already locked in keeps
    their status), then re-opens those recipients as "pending" for the
    next round. If the round cap is reached, still-unresolved recipients
    default to declined rather than being auto-accepted."""
    proposal = world.get("proposals", {}).get(proposal_id)
    if not proposal or proposal["status"] != "open":
        return {"ok": False, "reason": "no_active_proposal"}
    if proposal["proposer_id"] != proposer["id"]:
        return {"ok": False, "reason": "not_the_proposer"}

    if new_params:
        proposal["params"].update(new_params)

    proposal["round"] += 1
    still_open = [
        rid for rid, state in proposal["responses"].items()
        if state == "counter"
    ]
    if proposal["round"] >= proposal["max_rounds"]:
        for rid in still_open:
            proposal["responses"][rid] = "decline"
    else:
        for rid in still_open:
            proposal["responses"][rid] = "pending"
            proposal["counter_params"].pop(rid, None)

    _maybe_resolve(proposal, world)
    return {"ok": True, "round": proposal["round"]}


def _maybe_resolve(proposal, world):
    if any(state == "pending" or state == "counter" for state in proposal["responses"].values()):
        return
    proposal["status"] = "resolved"
    accepted = [
        rid for rid, state in proposal["responses"].items() if state == "accept"
    ] + [proposal["proposer_id"]]
    proposal["participants"] = accepted

    if proposal["kind"] == "chore":
        household = world.get("households", {}).get(proposal["household_id"])
        if household is not None:
            # Single-slot handoff cache, consumed by the activities.py
            # interaction that actually starts the chore (e.g.
            # do_laundry_fill's complete_activity() branch) — this stays a
            # single slot rather than a queue since chore proposals are
            # rare, deliberate events, not a high-frequency stream.
            household["_pending_chore"] = {
                "chore_id":     proposal["chore_id"],
                "participants": accepted,
                "resolved_tick": world.get("tick", 0),
            }
    elif proposal["kind"] == "recurring_offer":
        _finalize_recurring_offer(proposal, world)


# =========================================================
# SOCIAL ASK — general negotiation between two characters, no
# household/building gate. Counter-proposing is supported (see respond()).
# =========================================================

def propose_social_ask(proposer, recipient, world, ask, params=None):
    """recipient: a single character dict — whoever the proposer is asking.
    No locality/household gate at all, unlike propose_chore_to_household():
    a social ask can be made of anyone the proposer is actually talking to
    (the caller — action_router.py's _route_propose_social — is what
    ensures there's a real target)."""
    proposal = propose(proposer, [recipient], "social_ask", ask, params, world)
    return {"ok": True, "proposal": proposal}


# =========================================================
# REQUEST — a one-sided ask evaluated against the recipient's own
# systems/social_rules.py standing policies. See
# action_router.py::_route_propose_request for the auto-resolution
# call site: when a rule cleanly matches, the caller resolves this
# proposal immediately (impersonating the recipient) rather than
# waiting for their LLM turn. No locality/household gate, same as
# social_ask. Counter-proposing is supported (see respond()).
# =========================================================

def propose_request(proposer, recipient, world, topic, situation, urgency):
    """recipient: a single character dict. topic/situation/urgency are
    stored in params — chore_id carries topic (mirrors how social_ask
    reuses chore_id as its generic "what" field) so existing
    kind-agnostic code (_maybe_resolve, narrative notes) can read the
    same field regardless of kind."""
    params = {"situation": situation, "urgency": urgency}
    proposal = propose(proposer, [recipient], "request", topic, params, world)
    return {"ok": True, "proposal": proposal}


# =========================================================
# RECURRING OFFER — accept/decline only, no counter-proposing a schedule
# =========================================================

def offer_recurring(proposer, participants, world, chore_id, schedule_params):
    """participants: character dicts who jointly completed the chore this
    offer is based on. schedule_params: {days, start_hour, end_hour}."""
    recipients = [p for p in participants if p["id"] != proposer["id"]]
    if not recipients:
        return {"ok": False, "reason": "no_one_to_ask"}
    proposal = propose(proposer, recipients, "recurring_offer", chore_id, schedule_params, world)
    return {"ok": True, "proposal": proposal}


def _finalize_recurring_offer(proposal, world):
    from systems.social_contracts import create_contract

    accepted_ids = [
        rid for rid, state in proposal["responses"].items() if state == "accept"
    ] + [proposal["proposer_id"]]
    if len(accepted_ids) < 2:
        return   # nobody actually wants the recurring arrangement, no contract

    params = proposal["params"]
    days = params.get("days", ["monday"])
    start_hour = params.get("start_hour", 18)
    end_hour = params.get("end_hour", 19)

    # _contract_blocks() (systems/scheduling.py) expects ONE term PER
    # PARTY, not one term shared across all parties — confirmed by reading
    # its filter (`term.get("party") != c["id"]`).
    terms = [
        {
            "party":      pid,
            "commitment": proposal["chore_id"],
            "check_type": "recurring_activity",
            "params":     {"days": days, "start_hour": start_hour, "end_hour": end_hour,
                            "activity": proposal["chore_id"]},
        }
        for pid in accepted_ids
    ]
    create_contract(accepted_ids, terms, world)
