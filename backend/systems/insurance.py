"""
systems/insurance.py

Per the user's explicit ask: real health insurance a character can
subscribe to -- a weekly premium, and coverage that pays a real share of
medical costs for as long as they've stayed continuously, actually-paid-
up enrolled. A missed premium payment (can't afford it that week) lapses
coverage immediately rather than quietly accruing a debt -- "pay for as
long as signed on to this insurance" reads as coverage requiring active
payment, not a grace period.

No medical-billing system exists anywhere else in this codebase yet to
generate a real cost FROM (confirmed via grep -- no hospital/treatment
bill concept exists at all) -- this ships the real plan/subscription/
premium mechanism plus a ready-to-call pay_medical_cost(), which the
first real medical-cost trigger (a future round) wires into directly.
"""

INSURANCE_PLANS = {
    "basic":    {"name": "Basic Health Plan",    "premium_weekly": 15.0, "coverage_pct": 0.40},
    "standard": {"name": "Standard Health Plan", "premium_weekly": 35.0, "coverage_pct": 0.65},
    "premium":  {"name": "Premium Health Plan",  "premium_weekly": 70.0, "coverage_pct": 0.90},
}


_TICKS_PER_DAY = 86400
VALIDITY_DAYS = 6 * 30   # a documented ~6-month approximation, not calendar-exact
RENEWAL_LEAD_DAYS = 14


def enroll(c, world, plan_id):
    if plan_id not in INSURANCE_PLANS:
        return False
    tick = world.get("tick", 0)
    c["insurance"] = {
        "plan_id": plan_id,
        "since_tick": tick,
        "expires_tick": tick + VALIDITY_DAYS * _TICKS_PER_DAY,
        "renewal_reminder_sent_day": None,
    }

    # A real, physical + digital proof-of-insurance document -- per the
    # user's explicit ask (needed later e.g. to register a vehicle).
    from systems.personal_items import make_document, add_item
    from systems.document_search import register_digital_copy
    plan = INSURANCE_PLANS[plan_id]
    doc = make_document("insurance_policy", {
        "plan_id": plan_id, "plan_name": plan["name"],
        "since_tick": tick, "expires_tick": c["insurance"]["expires_tick"],
        "has_digital_copy": True,
    }, world=world)
    add_item(c, doc)
    c["insurance"]["document_item_id"] = doc["id"]
    register_digital_copy(c, world, doc)
    return True


def renew_insurance(c, world):
    """A real, explicit renewal -- extends expires_tick another full
    validity window and issues a fresh document, same shape as
    enroll()'s. Coverage/premium itself is untouched (renewal is about
    the POLICY TERM, not re-subscribing)."""
    ins = c.get("insurance")
    if not ins:
        return False
    tick = world.get("tick", 0)
    ins["expires_tick"] = tick + VALIDITY_DAYS * _TICKS_PER_DAY
    ins["renewal_reminder_sent_day"] = None

    from systems.personal_items import make_document, add_item
    from systems.document_search import register_digital_copy
    plan = INSURANCE_PLANS.get(ins["plan_id"], {})
    doc = make_document("insurance_policy", {
        "plan_id": ins["plan_id"], "plan_name": plan.get("name"),
        "since_tick": ins.get("since_tick"), "expires_tick": ins["expires_tick"],
        "has_digital_copy": True,
    }, world=world)
    add_item(c, doc)
    ins["document_item_id"] = doc["id"]
    register_digital_copy(c, world, doc)
    return True


def cancel_insurance(c):
    c["insurance"] = None


def pay_weekly_premium(c, world):
    """Called from the same weekly cycle as economy.py's apply_expenses()
    / retirement.py's pay_weekly_pension()."""
    ins = c.get("insurance")
    if not ins:
        return
    plan = INSURANCE_PLANS.get(ins.get("plan_id"))
    if not plan:
        return

    from systems.personal_items import get_item
    from systems.banking import BANK_NAME_TO_KEY, withdraw

    wallet = get_item(c, "wallet")
    card = next((i for i in (wallet.get("items", []) if wallet else [])
                 if i.get("object_type") == "bank_card"), None)
    bank_key = BANK_NAME_TO_KEY.get(card.get("bank")) if card else None

    paid = bank_key and withdraw(world, bank_key, card.get("account_number"), plan["premium_weekly"])
    if not paid:
        c["insurance"] = None   # lapsed -- couldn't cover this week's premium


def _today_key(world):
    cal = world.get("calendar", {})
    return "{}-{}-{}".format(cal.get("year", 0), cal.get("month", 0), cal.get("day", 0))


def _send_renewal_reminder(c, world, ins):
    plan = INSURANCE_PLANS.get(ins.get("plan_id"), {})
    plan_name = plan.get("name", "your insurance")

    # Email leg -- a company-generated notice, not a real person-to-
    # person conversation, so this uses inbox.py's shared message shape
    # (the same mechanism the missed-call voicemail already uses)
    # rather than apply_speech(), which models an actual speaker.
    from systems.inbox import get_character_inbox, add_message
    add_message(
        get_character_inbox(c), "email", plan_name, c["id"],
        f"Reminder: {plan_name} is about to expire -- renew soon.",
        world.get("tick", 0),
    )

    # Physical mail leg -- real, existing document-spawning path.
    household = world.get("households", {}).get(c.get("household_id"))
    if household:
        from systems.mail import create_form_request_mail
        create_form_request_mail(
            household, world,
            sender=plan_name,
            title=f"Renewal Notice: {plan_name}",
            form_template="renew_insurance",
            due_ticks=RENEWAL_LEAD_DAYS * _TICKS_PER_DAY,
        )


def tick_insurance_renewals(world):
    """Once per real calendar day (mirrors reminders.py/contract_
    clauses.py's own day-gate shape): within RENEWAL_LEAD_DAYS of
    expiry, sends both a real email and a real physical mail reminder,
    once per real day, until renewed or lapsed."""
    today_key = _today_key(world)
    if world.get("_insurance_renewal_sweep_day") == today_key:
        return
    world["_insurance_renewal_sweep_day"] = today_key

    tick = world.get("tick", 0)
    lead_ticks = RENEWAL_LEAD_DAYS * _TICKS_PER_DAY
    for c in world.get("characters", {}).values():
        ins = c.get("insurance")
        if not ins or not ins.get("expires_tick"):
            continue
        if tick < ins["expires_tick"] - lead_ticks:
            continue
        if ins.get("renewal_reminder_sent_day") == today_key:
            continue
        ins["renewal_reminder_sent_day"] = today_key
        _send_renewal_reminder(c, world, ins)


def pay_medical_cost(c, world, cost):
    """The real payout hook. Covers `cost` (a real medical bill) via
    insurance if currently enrolled, character pays whatever's left (or
    all of it, uninsured) out of pocket via the same cash/bank/credit
    cascade every other purchase in this game uses. Returns the amount
    the character actually paid out of pocket."""
    if cost <= 0:
        return 0.0

    ins = c.get("insurance")
    covered = 0.0
    if ins:
        plan = INSURANCE_PLANS.get(ins.get("plan_id"))
        if plan:
            covered = cost * plan["coverage_pct"]

    remaining = round(max(0.0, cost - covered), 2)
    if remaining > 0:
        from systems.personal_items import pay_from_wallet
        pay_from_wallet(c, world, remaining)
    return remaining
