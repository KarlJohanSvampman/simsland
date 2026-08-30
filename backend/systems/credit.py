"""
systems/credit.py

Credit cards: apply-only (never starting inventory -- see
character_gen.py, which only grants a bank_card), gated by
c["credit_score"]. The credit line (max_credit/current_debt) lives
directly on the card item instance -- see
personal_items.py::make_credit_card() -- not on an external account like
a bank_card's balance (banking.py).

Minimum payment is current_debt / 12 (fixed contractual shape from the
original spec: "the current_debt should be divided by 12 (months in
year) and that is the next monthly cost"). That monthly figure is folded
into the household's existing weekly bill cycle as a per-member
attributed line -- see economy.py::apply_expenses().
"""

import random

CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850
CREDIT_SCORE_DEFAULT = 650

# Below this score, every provider declines. Limit ramps linearly from
# _LIMIT_AT_THRESHOLD (just barely approved) to _LIMIT_AT_MAX_SCORE
# (perfect score) between here and CREDIT_SCORE_MAX.
APPROVAL_THRESHOLD = 580
_LIMIT_AT_THRESHOLD = 500
_LIMIT_AT_MAX_SCORE = 20000

# Monthly minimum-payment behavior's effect on score -- missed payments
# hurt more than on-time payments help, matching real credit dynamics.
SCORE_DELTA_ON_TIME_PAYMENT = 2
SCORE_DELTA_MISSED_PAYMENT  = -25
# Simple interest applied to any carried balance each monthly cycle.
MONTHLY_INTEREST_RATE = 0.02


def initial_credit_score(age=None, employed=False):
    """Rough real-world-shaped starting score for character generation:
    young/unemployed skew low, established adults skew mid-high, random
    on top. Not applied to every character today (starting inventory
    never includes a credit card), but every character still needs a
    score the moment they consider applying for one."""
    base = CREDIT_SCORE_DEFAULT
    if age is not None and age < 25:
        base -= 80
    if not employed:
        base -= 40
    score = base + random.randint(-60, 60)
    return max(CREDIT_SCORE_MIN, min(CREDIT_SCORE_MAX, score))


def credit_limit_for_score(score):
    if score < APPROVAL_THRESHOLD:
        return 0
    span = CREDIT_SCORE_MAX - APPROVAL_THRESHOLD
    frac = (score - APPROVAL_THRESHOLD) / span if span else 1.0
    return round(_LIMIT_AT_THRESHOLD + frac * (_LIMIT_AT_MAX_SCORE - _LIMIT_AT_THRESHOLD), -1)


def is_eligible(c):
    return c.get("credit_score", CREDIT_SCORE_DEFAULT) >= APPROVAL_THRESHOLD


def _wallet(c):
    from systems.personal_items import get_item
    return get_item(c, "wallet")


def get_credit_cards(c):
    w = _wallet(c)
    if not w:
        return []
    return [i for i in w.get("items", []) if i.get("object_type") == "credit_card"]


def has_credit_card(c, provider=None):
    return any(card.get("provider") == provider or provider is None
               for card in get_credit_cards(c))


def apply_for_credit_card(c, world, provider):
    """Score-gated application -- approves/declines immediately (real
    banks don't make you wait days to find out, unlike the loan/mortgage
    appointment flow). Returns the new card dict on approval, None on
    decline. No-op (returns None) if this character already holds a card
    from this provider."""
    if has_credit_card(c, provider):
        return None
    if not is_eligible(c):
        return None

    wallet = _wallet(c)
    if not wallet:
        from systems.personal_items import make_wallet, add_item
        wallet = make_wallet(cash=0.0, owner_id=c.get("id"))
        add_item(c, wallet)

    from systems.personal_items import make_credit_card
    from systems.containers import add_to_container
    limit = credit_limit_for_score(c.get("credit_score", CREDIT_SCORE_DEFAULT))
    card = make_credit_card(provider, limit, owner_id=c.get("id"))
    result = add_to_container(wallet, card)
    if not result.get("success"):
        return None
    # add_to_container() deep-copies the item into the container -- `card`
    # above is a stale, disconnected reference the moment it's added, so
    # any later charge()/make_payment() on it wouldn't touch the real
    # stored card. Return the actual stored instance instead.
    return next(i for i in wallet["items"] if i["id"] == card["id"])


def charge(card, amount):
    """Spend against the card's credit line. Returns False if it would
    exceed max_credit."""
    if amount <= 0:
        return False
    if card.get("current_debt", 0.0) + amount > card.get("max_credit", 0.0):
        return False
    card["current_debt"] = round(card.get("current_debt", 0.0) + amount, 2)
    return True


def minimum_payment(card):
    return round(card.get("current_debt", 0.0) / 12, 2)


def make_payment(card, amount):
    """Pay down current_debt directly (cash already collected by the
    caller -- see economy.py's weekly bill cycle / mail.py::
    attempt_pay_bills). Returns the amount actually applied (capped at
    the outstanding balance). Tracked separately in _payments_this_month
    so tick_monthly_card_cycle() can judge payment behavior without it
    being masked by a new charge raising current_debt right back up."""
    applied = min(amount, card.get("current_debt", 0.0))
    card["current_debt"] = round(card.get("current_debt", 0.0) - applied, 2)
    card["_payments_this_month"] = round(card.get("_payments_this_month", 0.0) + applied, 2)
    return applied


def apply_monthly_interest_and_scoring(card, c, paid_minimum):
    """Accrues interest on any remaining balance and nudges credit_score
    based on whether the minimum got paid. See tick_monthly_card_cycle()
    below for the actual monthly caller."""
    if card.get("current_debt", 0.0) > 0:
        card["current_debt"] = round(card["current_debt"] * (1 + MONTHLY_INTEREST_RATE), 2)
    delta = SCORE_DELTA_ON_TIME_PAYMENT if paid_minimum else SCORE_DELTA_MISSED_PAYMENT
    score = c.get("credit_score", CREDIT_SCORE_DEFAULT) + delta
    c["credit_score"] = max(CREDIT_SCORE_MIN, min(CREDIT_SCORE_MAX, score))


def tick_monthly_card_cycle(c):
    """Called once per character per monthly cycle (see sim_loop.py's
    _is_month_start_midnight block) -- the weekly bill cycle
    (economy.py::apply_expenses / mail.py::attempt_pay_bills) pays down
    current_debt in small weekly slices via make_payment(), which tracks
    _payments_this_month separately from current_debt specifically so a
    new charge that month (which also raises current_debt) can't mask
    real payments as a missed minimum."""
    for card in get_credit_cards(c):
        prior = card.get("_month_start_debt", 0.0)
        min_due = round(prior / 12, 2)
        paid_minimum = min_due <= 0 or card.get("_payments_this_month", 0.0) >= min_due - 0.01
        apply_monthly_interest_and_scoring(card, c, paid_minimum)
        card["_month_start_debt"] = card.get("current_debt", 0.0)
        card["_payments_this_month"] = 0.0
