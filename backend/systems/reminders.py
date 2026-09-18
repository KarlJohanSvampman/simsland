"""
reminders.py -- a general "watch a future date, react if unmet" sweep.

Modeled on calendar_events.py::check_calendar_reminders()'s day-gate
shape (a per-real-calendar-day guard, sweep the population/households
once). No such generic engine existed anywhere in this codebase before
this round -- bills sat forever with no due date until a hard trim
silently dropped them, and a letter expecting a reply had no concept of
a deadline at all. Two real consumers ship with this sweep:

  - Bills (economy.py::apply_expenses()) past their due_tick with
    remaining > 0 get a real late fee, a resend count, and a fresh
    reminder mail.
  - Personal letters (mail.py::create_personal_letter()) with
    requires_response=True, responded=False, and reply_by_tick passed
    get a single follow-up reminder letter back to the same recipient.
"""

from systems.mail import create_personal_letter

# How much a late bill grows each time it's caught unpaid past its due
# date, and how far out the next check is pushed -- without re-arming
# due_tick, the very next day's sweep would catch the same bill again
# and re-apply the fee every single day.
LATE_FEE_RATE = 0.10
RESEND_INTERVAL_DAYS = 7
_TICKS_PER_DAY = 86400


def _today_key(world):
    cal = world.get("calendar", {})
    return "{}-{}-{}".format(cal.get("year", 0), cal.get("month", 0), cal.get("day", 0))


def _send_bill_reminder(household, world, bill):
    """A fresh, visible mail item -- the household actually SEES 'second
    notice, now with a late fee' rather than the debt just silently
    existing. Reuses create_form_request_mail()'s existing shape (a
    formal request the household can act on) rather than a new
    constructor."""
    from systems.mail import create_form_request_mail

    title = (
        "Second Notice: Overdue Bill" if bill["times_resent"] == 1
        else f"Notice #{bill['times_resent'] + 1}: Overdue Bill"
    )
    create_form_request_mail(
        household, world,
        sender="Billing Department",
        title=title,
        form_template="pay_overdue_bill",
        due_ticks=RESEND_INTERVAL_DAYS * _TICKS_PER_DAY,
        source_event_id=bill.get("id"),
    )


def _sweep_bills(world):
    tick = world.get("tick", 0)
    for household in world.get("households", {}).values():
        for bill in household.get("bills_due", []):
            if bill.get("remaining", 0) <= 0:
                continue
            due_tick = bill.get("due_tick")
            if due_tick is None or tick < due_tick:
                continue

            bill["remaining"] = round(bill["remaining"] * (1 + LATE_FEE_RATE), 2)
            bill["amount"] = round(bill.get("amount", 0) * (1 + LATE_FEE_RATE), 2)
            bill["times_resent"] = bill.get("times_resent", 0) + 1
            bill["penalty_applied"] = True
            # Re-arm so this same bill isn't caught (and re-fee'd) again
            # on every subsequent day's sweep -- only once the next
            # resend window has also passed.
            bill["due_tick"] = tick + RESEND_INTERVAL_DAYS * _TICKS_PER_DAY

            _send_bill_reminder(household, world, bill)


def _sweep_mail_replies(world):
    tick = world.get("tick", 0)
    for household in world.get("households", {}).values():
        mailbox = household.get("mailbox", {})
        for mail in mailbox.get("items", []):
            if mail.get("type") != "personal_letter":
                continue
            if not mail.get("requires_response"):
                continue
            if mail.get("responded"):
                continue
            if mail.get("reminder_sent"):
                continue
            reply_by = mail.get("reply_by_tick")
            if reply_by is None or tick < reply_by:
                continue

            create_personal_letter(
                household, world,
                addressed_to_id=mail.get("addressed_to"),
                letter_type=mail.get("letter_type", "reminder"),
                content=f"Following up -- I still haven't heard back from you: {mail.get('title', 'my earlier letter')}",
                sender_label=mail.get("sender", "Unknown"),
            )
            mail["reminder_sent"] = True


def check_reminders(world):
    """Call once per tick (mirrors calendar_events.py's own call shape);
    internally guards to run once per real calendar day."""
    today_key = _today_key(world)
    if world.get("_reminder_sweep_day") == today_key:
        return
    world["_reminder_sweep_day"] = today_key

    _sweep_bills(world)
    _sweep_mail_replies(world)
