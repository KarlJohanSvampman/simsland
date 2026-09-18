"""
api/finances.py

Per-character finance detail for the Life tab's Finances section -- bank
account balances, credit card debt, household loans this character is a
borrower on, and a combined total debt / weekly debt cost figure.

Character data reaches the frontend over the WS snapshot/delta protocol,
but world["banks"] and each household's real loans (world["households"]
[...]["loans"]) are never part of that payload (both are non-spatial,
not viewport data) -- so this is a plain REST poll, mirroring
api/overview.py's shape, not a WS addition.
"""

from fastapi import APIRouter

from db import load_world

router = APIRouter()


@router.get("/finances/{character_id}")
def get_character_finances(character_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    c = world.get("characters", {}).get(character_id)
    if not c:
        return {"ok": False, "error": "character not found"}

    from systems.banking import BANK_NAME_TO_KEY, get_balance
    from systems.personal_items import get_item
    from systems.credit import minimum_payment

    wallet = get_item(c, "wallet")
    wallet_items = wallet.get("items", []) if wallet else []

    bank_accounts = []
    for item in wallet_items:
        if item.get("object_type") != "bank_card":
            continue
        bank_key = BANK_NAME_TO_KEY.get(item.get("bank"))
        balance = get_balance(world, bank_key, item.get("account_number")) if bank_key else None
        bank_accounts.append({
            "bank":    item.get("bank"),
            "balance": balance,
        })

    credit_cards = []
    credit_total = 0.0
    for item in wallet_items:
        if item.get("object_type") != "credit_card":
            continue
        debt = item.get("current_debt", 0.0) or 0.0
        credit_total += debt
        credit_cards.append({
            "provider":        item.get("provider"),
            "current_debt":    debt,
            "max_credit":      item.get("max_credit", 0.0),
            "minimum_payment": minimum_payment(item),
        })

    household = world.get("households", {}).get(c.get("household_id"), {})

    loans = []
    loan_total = 0.0
    for loan in household.get("loans", {}).values():
        if character_id not in loan.get("borrower_ids", []):
            continue
        balance = loan.get("balance", 0.0) or 0.0
        if balance <= 0:
            continue
        loan_total += balance

        # A standard amortized payment (systems/loans.py::_monthly_payment,
        # already how monthly_payment itself was computed) is part interest,
        # part real paydown -- split it back out here so the Life tab can
        # show both halves rather than one opaque total. Interest accrues
        # on the CURRENT balance each cycle; whatever's left of the fixed
        # payment after that is the actual amount the borrower is putting
        # toward the debt itself.
        rate = loan.get("rate", 0.0) or 0.0
        monthly_payment = loan.get("monthly_payment", 0.0) or 0.0
        monthly_interest = round(balance * (rate / 12), 2)
        monthly_principal = round(max(0.0, monthly_payment - monthly_interest), 2)

        loans.append({
            "id":                loan.get("id"),
            "kind":              loan.get("kind"),
            "provider":          loan.get("provider"),
            "balance":           balance,
            "rate_pct":          round(rate * 100, 2),
            "monthly_payment":   monthly_payment,
            "monthly_interest":  monthly_interest,
            "monthly_principal": monthly_principal,
            "weekly_payment":    round(monthly_payment / 4.345, 2),
            "weekly_interest":   round(monthly_interest / 4.345, 2),
            "weekly_principal":  round(monthly_principal / 4.345, 2),
        })

    # Reuse the already-computed weekly bill breakdown (economy.py::
    # apply_expenses) rather than recomputing credit/loan weekly slices
    # here -- this is exactly what the household is actually being
    # charged this cycle.
    bills = household.get("bills_due", [])
    breakdown = bills[-1].get("breakdown", {}) if bills else {}
    weekly_debt_cost = round(
        (breakdown.get("credit_cards", 0.0) or 0.0)
        + (breakdown.get("loans", 0.0) or 0.0),
        2,
    )

    government_debt = c.get("government_debt", 0.0) or 0.0
    total_debt = round(credit_total + loan_total + government_debt, 2)

    return {
        "ok": True,
        "bank_accounts":    bank_accounts,
        "credit_cards":     credit_cards,
        "loans":            loans,
        "weekly_debt_cost": weekly_debt_cost,
        "government_debt":  round(government_debt, 2),
        "total_debt":       total_debt,
    }
