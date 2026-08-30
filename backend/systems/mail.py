import uuid

def create_form_request_mail(
    household,
    world,
    sender,
    title,
    form_template,
    due_ticks=1200,
    source_event_id=None
):

    mail = {
        "id": f"mail_{uuid.uuid4().hex[:8]}",
        "type": "formal_request",
        "sender": sender,
        "title": title,
        "requires_response": True,
        "response_type": "form",
        "form_template": form_template,
        "due_tick": world["tick"] + due_ticks,
        "opened": False,
        "responded": False,
        "urgency": 0.6,
        "source_event_id": source_event_id
    }

    # Per-key setdefault, not a whole-dict one -- household["mailbox"]
    # may already exist with OTHER keys already set (e.g. the physical
    # mailbox x/y position, schema_defaults.py's ensure_world_defaults),
    # in which case a whole-dict setdefault("mailbox", {...}) is a no-op
    # and silently never adds has_mail/items/unopened_count, crashing the
    # very next line.
    mailbox = household.setdefault("mailbox", {})
    mailbox.setdefault("has_mail", False)
    mailbox.setdefault("items", [])
    mailbox.setdefault("unopened_count", 0)

    mailbox["items"].append(mail)
    mailbox["has_mail"] = True
    mailbox["unopened_count"] += 1

    return mail


def sort_household_mail(household, world):
    """Open and categorise all unopened mail from the mailbox."""

    mailbox = household.setdefault("mailbox", {})
    mailbox.setdefault("has_mail", False)
    mailbox.setdefault("items", [])
    mailbox.setdefault("unopened_count", 0)

    for mail in mailbox.get("items", []):

        if mail.get("opened"):
            continue

        mail["opened"] = True

        if mail.get("type") == "bill":
            household.setdefault("unpaid_bills", []).append(mail)

        elif mail.get("requires_response"):
            household.setdefault("pending_responses", []).append(mail)

        else:
            household.setdefault("completed_documents", []).append(mail)

    # Recount so the has_mail flag stays accurate
    mailbox["unopened_count"] = sum(
        1 for m in mailbox["items"] if not m.get("opened")
    )
    mailbox["has_mail"] = mailbox["unopened_count"] > 0

def respond_to_mail(c, household, mail, world):

    mail["responded"] = True
    mail["responded_by"] = c["id"]
    mail["responded_tick"] = world["tick"]

    household.setdefault("completed_documents", []).append(mail)

    if mail in household.get("pending_responses", []):
        household["pending_responses"].remove(mail)

def attempt_pay_bills(c, world):
    """Pays down household bills_due (economy.py::apply_expenses(), issued
    weekly Monday-midnight) out of the household's shared wealth pool --
    called per-member each cycle, so whichever member gets to it first
    pays what the household can afford; bills_due entries created before
    a member paid it off in full stay skipped (remaining already <= 0)
    on every later call, so nothing double-pays.

    Settling a bill fully doesn't just zero out an abstract total -- its
    credit_card_payments/loan_payments slices (see economy.py) get
    applied to the real card/loan balances right here, otherwise Round
    C/D's debt would accrue every week but never actually go down even
    though the household kept "paying" it."""

    hid = c.get("household_id")
    if not hid:
        return

    household = world["households"].get(hid)
    if not household:
        return

    bills = household.get("bills_due", [])
    # Unbounded growth guard -- settled bills stay in the list forever
    # otherwise (nothing here or in economy.py ever removes them), same
    # trim pattern offgrid.py uses for world["events"].
    if len(bills) > 60:
        household["bills_due"] = bills = bills[-60:]

    for bill in bills:

        remaining = bill.get("remaining", 0)
        if remaining <= 0:
            continue

        available = household.get("wealth", 0)
        if available <= 0:
            continue

        pay = min(available, remaining)
        household["wealth"] = round(available - pay, 2)
        bill["remaining"] = round(remaining - pay, 2)
        contributors = bill.setdefault("contributors", {})
        contributors[c["id"]] = round(contributors.get(c["id"], 0) + pay, 2)

        if bill["remaining"] <= 0:
            _settle_bill_debts(household, world, bill)

    # Drop fully-settled bills instead of leaving them in the list forever
    # at remaining==0 -- nothing here or in economy.py ever removes them
    # otherwise, so bills_due would only ever grow (until the >60 cap
    # above kicks in), never actually shrink as debt gets paid down.
    household["bills_due"] = [b for b in bills if b.get("remaining", 0) > 0]


def _settle_bill_debts(household, world, bill):
    from systems.credit import get_credit_cards, make_payment as pay_credit_card
    from systems.loans import make_payment as pay_loan

    chars = world.get("characters", {})
    for entry in bill.get("credit_card_payments", []):
        member = chars.get(entry["character_id"])
        if not member:
            continue
        card = next((c for c in get_credit_cards(member) if c["id"] == entry["card_id"]), None)
        if card:
            pay_credit_card(card, entry["amount"])

    for entry in bill.get("loan_payments", []):
        loan = household.get("loans", {}).get(entry["loan_id"])
        if loan:
            pay_loan(loan, entry["amount"]) 