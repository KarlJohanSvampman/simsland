"""
systems/government_debt.py

Monthly income tax assessment on employed characters. income_tax_rate
(socioeconomics.py, exposed as world["environment"]["tax_rate"] -- a
fraction, e.g. 0.085) was already computed as a community stat but never
actually charged to anyone -- this makes it real.

Payment is attempted immediately: wallet cash first, then bank balance;
whatever can't be covered accrues onto c["government_debt"], a running
personal balance kept separate from household bills_due (this is an
individual tax obligation, not a shared household expense).

There's no fine/citation pipeline in systems/law.py to hook a consequence
into -- it's arrest/trial/jail for crimes only, nothing debt-related --
so the real consequence here is credit_score, the one lever every other
financial system in this session already respects.
"""

CREDIT_PENALTY_THRESHOLD = 500.0
CREDIT_PENALTY_DELTA = -15


def _monthly_income(c):
    from systems.loans import annual_income
    return annual_income(c) / 12


def assess_monthly_tax(c, world):
    """Called once per employed character per monthly cycle (see
    sim_loop.py's _is_month_start_midnight block)."""
    if not c.get("employed"):
        return

    tax_rate = world.get("environment", {}).get("tax_rate", 0.085)
    owed = round(_monthly_income(c) * tax_rate, 2)
    if owed <= 0:
        return

    from systems.personal_items import wallet_cash, spend_cash, get_item
    remaining = owed
    cash_available = wallet_cash(c)
    if cash_available > 0:
        draw = min(cash_available, remaining)
        if spend_cash(c, draw):
            remaining = round(remaining - draw, 2)

    if remaining > 0:
        from systems.banking import get_balance, withdraw, BANK_NAME_TO_KEY
        wallet = get_item(c, "wallet")
        for item in (wallet.get("items", []) if wallet else []):
            if remaining <= 0:
                break
            if item.get("object_type") != "bank_card":
                continue
            bank_key = BANK_NAME_TO_KEY.get(item.get("bank"))
            if not bank_key:
                continue
            balance = get_balance(world, bank_key, item["account_number"]) or 0
            draw = min(balance, remaining)
            if draw > 0 and withdraw(world, bank_key, item["account_number"], draw):
                remaining = round(remaining - draw, 2)

    if remaining > 0:
        c["government_debt"] = round(c.get("government_debt", 0.0) + remaining, 2)


def apply_debt_consequences(c):
    """Monthly credit-score ding for carrying government debt past the
    threshold -- called alongside assess_monthly_tax for the same
    character, same cycle."""
    if c.get("government_debt", 0.0) <= CREDIT_PENALTY_THRESHOLD:
        return
    from systems.credit import CREDIT_SCORE_MIN, CREDIT_SCORE_MAX, CREDIT_SCORE_DEFAULT
    score = c.get("credit_score", CREDIT_SCORE_DEFAULT) + CREDIT_PENALTY_DELTA
    c["credit_score"] = max(CREDIT_SCORE_MIN, min(CREDIT_SCORE_MAX, score))
