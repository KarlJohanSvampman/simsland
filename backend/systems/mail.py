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

    household.setdefault("mailbox", {
        "has_mail": False,
        "items": [],
        "unopened_count": 0
    })

    household["mailbox"]["items"].append(mail)
    household["mailbox"]["has_mail"] = True
    household["mailbox"]["unopened_count"] += 1

    return mail


def sort_household_mail(household, world):

    unopened = household.get("unopened_mail", [])

    remaining = []

    for mail in unopened:

        mail["opened"] = True

        if mail.get("type") == "bill":
            household.setdefault("unpaid_bills", []).append(mail)

        elif mail.get("requires_response"):
            household.setdefault("pending_responses", []).append(mail)

        else:
            household.setdefault("completed_documents", []).append(mail)

    household["unopened_mail"] = remaining

def respond_to_mail(c, household, mail, world):

    mail["responded"] = True
    mail["responded_by"] = c["id"]
    mail["responded_tick"] = world["tick"]

    household.setdefault("completed_documents", []).append(mail)

    if mail in household.get("pending_responses", []):
        household["pending_responses"].remove(mail)

def attempt_pay_bills(c, world):

    hid = c.get("household_id")
    if not hid:
        return

    household = world["households"].get(hid)
    if not household:
        return

    for bill in household.get("bills_due", []):

        if bill["remaining"] <= 0:
            continue

        wealth = c.get("wealth", 0)
        if wealth <= 0:
            continue

        # simple share logic
        members = household.get("members", [])
        share = bill["amount"] / max(1, len(members))

        contribution = min(share, wealth, bill["remaining"])

        c["wealth"] -= contribution
        bill["remaining"] -= contribution

        bill.setdefault("contributors", {})
        bill["contributors"][c["id"]] = bill["contributors"].get(c["id"], 0) + contribution