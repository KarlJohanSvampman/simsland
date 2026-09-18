"""
systems/contract_clauses.py

A conditional_clause is a stored condition on a document (an employment
contract, a purchase receipt's warranty, ...) that either fires
automatically once its condition is met, or -- for an "optional" clause
-- queues a real choice the benefiting party must act on rather than
firing on its own. Modeled directly on systems/reminders.py's proven
once-per-real-day sweep shape.

Document-agnostic by design: sweeps BOTH c["employment_contract"] and
any "document"-templated inventory item whose own content carries a
conditional_clauses map (e.g. a purchase receipt's warranty terms --
see systems/procurement.py) -- the sweep and the checker/effect
dispatch below don't care which kind of document a clause came from,
only that its shape matches.
"""

_TICKS_PER_DAY = 86400


def _today_key(world):
    cal = world.get("calendar", {})
    return "{}-{}-{}".format(cal.get("year", 0), cal.get("month", 0), cal.get("day", 0))


# =========================================================
# CHECKERS -- check_type -> (c, world, document, params) -> bool
# Intentionally small and extensible, same philosophy as systems/
# social_contracts.py's own _CHECKERS dict, which grew incrementally.
# =========================================================

def _check_payment_overdue(c, world, document, params):
    last_paid = document.get("last_paid_tick", 0)
    days = params.get("days", 7)
    return world.get("tick", 0) - last_paid >= days * _TICKS_PER_DAY


def _check_hours_shortfall(c, world, document, params):
    """Real, simple proxy: compares the CURRENT week's actually-
    scheduled work hours against the contract's own hours_per_week.
    A real rolling multi-week shortfall tracker is a reasonable future
    refinement; this checks live, real schedule data rather than
    inventing a parallel history tracker for a starter checker."""
    contract_hours = document.get("hours_per_week", 0)
    if not contract_hours:
        return False
    actual_hours = 0.0
    for day_blocks in c.get("schedule", {}).get("week", {}).values():
        for b in day_blocks:
            if b.get("activity") != "work":
                continue
            sh, sm = (int(x) for x in b["start"].split(":"))
            eh, em = (int(x) for x in b["end"].split(":"))
            actual_hours += (eh * 60 + em) - (sh * 60 + sm)
    actual_hours /= 60.0
    return actual_hours < contract_hours * 0.5


def _check_missed_shifts_count(c, world, document, params):
    threshold = params.get("count", 3)
    nd = c.get("expectations", {}).get(f"contract:{document.get('id')}:show_up_for_shifts")
    return bool(nd and nd.get("missed_count", 0) >= threshold)


def _check_item_broken(c, world, document, params):
    """document here is the receipt's content dict; params carries the
    purchased item's own id. A real, checkable states.broken flag --
    see systems/procurement.py for what sets it."""
    item_id = params.get("item_id")
    item = next((i for i in c.get("inventory", []) if i.get("id") == item_id), None)
    return bool(item and item.get("states", {}).get("broken"))


_CLAUSE_CHECKERS = {
    "payment_overdue":     _check_payment_overdue,
    "hours_shortfall":     _check_hours_shortfall,
    "missed_shifts_count": _check_missed_shifts_count,
    "item_broken":         _check_item_broken,
}


# =========================================================
# EFFECTS -- effect_type -> (c, world, document, effect) -> None
# =========================================================

def _effect_grievance(c, world, document, effect):
    target_id = effect.get("target_id")
    if not target_id or target_id == c.get("id"):
        return
    from systems.grievances import add_grievance
    add_grievance(c, target_id, "contract_violated", world, details={"clause_effect": effect})


def _effect_wage_adjustment(c, world, document, effect):
    pct = effect.get("pct", 0.0)
    if document.get("hourly_wage") is not None:
        document["hourly_wage"] = round(document["hourly_wage"] * (1 + pct), 2)
        c["hourly_wage"] = document["hourly_wage"]


def _effect_quit_without_penalty(c, world, document, effect):
    from systems.jobs import quit_job
    quit_job(c, world)


def _effect_terminate_contract(c, world, document, effect):
    c["employment_contract"] = None
    c["employed"] = False


def _effect_refund(c, world, document, effect):
    """Per the user's explicit ask: a refund isn't instant money -- it's
    a real $ value assigned to the document once conditions are
    confirmed met, which only actually pays out after the character
    mails (or prints-then-mails) the document to the responsible party
    and a real ~1-day delivery delay passes. See action_router.py::
    _route_mail_claim_document() and tick_pending_payouts() below."""
    document["claim_value"] = document.get("price", 0)


def _effect_replace_item(c, world, document, effect):
    item_id = document.get("item_id")
    item = next((i for i in c.get("inventory", []) if i.get("id") == item_id), None)
    if item:
        item.setdefault("states", {})["broken"] = False


def _effect_free_repair(c, world, document, effect):
    _effect_replace_item(c, world, document, effect)


_CLAUSE_EFFECTS = {
    "grievance":            _effect_grievance,
    "wage_adjustment":      _effect_wage_adjustment,
    "quit_without_penalty": _effect_quit_without_penalty,
    "terminate_contract":   _effect_terminate_contract,
    "refund":               _effect_refund,
    "replace_item":         _effect_replace_item,
    "free_repair":          _effect_free_repair,
}


def _iter_clause_documents(c):
    """Yields real documents this character holds that could carry
    conditional_clauses: the employment contract, and any "document"-
    templated inventory item whose own content carries a clauses map
    (a receipt's warranty terms)."""
    contract = c.get("employment_contract")
    if contract and contract.get("conditional_clauses"):
        yield contract
    for item in c.get("inventory", []):
        if item.get("template_id") != "document":
            continue
        if item.get("document_type") == "employment_contract":
            continue  # already covered via c["employment_contract"] above --
            # the physical copy's content dict shares the same nested
            # conditional_clauses object (a shallow dict() copy at
            # creation time), so sweeping both would double-process the
            # identical clauses every single day.
        content = item.get("content") or {}
        if content.get("conditional_clauses"):
            yield content


def process_clause(c, world, document, clause_id, clause):
    """Exposed (not underscored) since procurement.py/insurance.py may
    want to force-check a single freshly-created clause without waiting
    for the next daily sweep."""
    tick = world.get("tick", 0)

    valid_until = clause.get("valid_until_tick")
    if valid_until is not None and tick > valid_until:
        return  # expired -- never fires again, regardless of trigger_mode

    max_inv = clause.get("max_invocations")
    if max_inv is not None and clause.get("invocation_count", 0) >= max_inv:
        return  # exhausted

    if clause.get("trigger_mode") == "automatic" and clause.get("triggered"):
        return  # automatic clauses are one-shot

    checker = _CLAUSE_CHECKERS.get(clause.get("check_type"))
    if not checker or not checker(c, world, document, clause.get("params", {})):
        return

    if clause.get("trigger_mode") == "automatic":
        effect = (clause.get("effect_options") or [{}])[0]
        fn = _CLAUSE_EFFECTS.get(effect.get("type"))
        if fn:
            fn(c, world, document, effect)
        clause["triggered"] = True
        clause["invocation_count"] = clause.get("invocation_count", 0) + 1
    else:
        # Optional -- queue a real choice for the beneficiary rather
        # than firing on its own (systems/social_contracts.py::
        # queue_violation_escalation()'s "queue, don't force" precedent).
        pending = c.setdefault("pending_clause_invocations", [])
        if any(p["clause_id"] == clause_id for p in pending):
            return
        pending.append({
            "document_id":     document.get("id"),
            "clause_id":       clause_id,
            "description":     clause.get("description", ""),
            "effect_options":  clause.get("effect_options", []),
            "detected_tick":   tick,
        })


MAIL_CLAIM_DELIVERY_DAYS = 1


def tick_pending_payouts(world):
    """Real, delayed money -- a mailed-in claim (systems/action_router.py
    ::_route_mail_claim_document()) only actually pays out once this
    sweep catches its arrives_tick, crediting the character's OWN bank
    account (a real reimbursement lands in your account, not shared
    household funds), not instantly on invocation."""
    tick = world.get("tick", 0)
    pending = world.get("pending_payouts", [])
    if not pending:
        return
    remaining = []
    for payout in pending:
        if tick < payout["arrives_tick"]:
            remaining.append(payout)
            continue
        c = world.get("characters", {}).get(payout["character_id"])
        if c:
            from systems.personal_items import get_item
            from systems.banking import BANK_NAME_TO_KEY, deposit
            wallet = get_item(c, "wallet")
            card = next((i for i in (wallet.get("items", []) if wallet else [])
                         if i.get("object_type") == "bank_card"), None)
            bank_key = BANK_NAME_TO_KEY.get(card.get("bank")) if card else None
            if bank_key:
                deposit(world, bank_key, card.get("account_number"), payout["amount"])
    world["pending_payouts"] = remaining


def tick_contract_clauses(world):
    """Call once per tick (mirrors reminders.py::check_reminders()'s own
    call shape); internally guards to run once per real calendar day."""
    today_key = _today_key(world)
    if world.get("_clause_sweep_day") == today_key:
        return
    world["_clause_sweep_day"] = today_key

    for c in world.get("characters", {}).values():
        for document in _iter_clause_documents(c):
            for clause_id, clause in list(document.get("conditional_clauses", {}).items()):
                process_clause(c, world, document, clause_id, clause)
