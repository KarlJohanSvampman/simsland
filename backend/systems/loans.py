"""
systems/loans.py

Loans -- unsecured (loan providers) and secured (banks, collateral
required). Stored on the HOUSEHOLD (h["loans"]), not the individual
character: a loan can have one borrower or several joint co-borrowers
(explicit user direction -- two characters can apply together, combining
income for a bigger loan, splitting repayment, when the loan funds
something both benefit from), and household-level is also where the
weekly bill cycle (economy.py::apply_expenses) already lives.

h["loans"] = {
    loan_id: {
        "id", "provider", "kind": "secured"|"unsecured",
        "borrower_ids": [cid, ...],       # 1 = solo, 2+ = joint
        "principal", "balance", "rate", "monthly_payment", "term_months",
        "start_tick", "collateral_value" (secured only),
    }
}

Loan sizing is relative to the borrower(s)' income and, for secured
loans, real capital pledged as collateral (explicit user direction) --
this sim has no property-equity mechanic, so "collateral" here means a
caller-supplied dollar figure of real, currently-held capital (bank
balance) being pledged, not a fictional home valuation.
"""

# Contractual terms are fixed at issuance (explicit spec: "the contract
# with loan providers is set and cannot be changed"), unlike a credit
# card's flexible minimum-only repayment.
UNSECURED_TERM_MONTHS = 36
UNSECURED_ANNUAL_RATE = 0.14
UNSECURED_INCOME_MULTIPLE = 0.4   # max loan = 0.4x combined annual income
UNSECURED_MIN_CREDIT_SCORE = 520

SECURED_TERM_MONTHS = 60
SECURED_ANNUAL_RATE = 0.06
SECURED_INCOME_MULTIPLE = 0.6
SECURED_LOAN_TO_VALUE = 0.9       # up to 90% of pledged collateral value
SECURED_MIN_CREDIT_SCORE = 580

# Mortgage -- the one property-equity-backed loan kind this file's own
# original docstring flagged as missing ("this sim has no property-
# equity mechanic"). Distinct from a plain secured loan (collateral =
# real currently-held cash) because a mortgage's collateral IS the home
# itself, at its own real home["value"] (see housing.py), not a caller-
# supplied cash figure. Every household starts with one on their home
# (see originate_mortgage() below) -- 30-year term, no down payment,
# matching "everyone starts out with a loan on their home" verbatim.
MORTGAGE_TERM_MONTHS = 360
MORTGAGE_ANNUAL_RATE = 0.055


def annual_income(c):
    job = c.get("job") or {}
    if job.get("average_salary"):
        return float(job["average_salary"])
    return float(c.get("hourly_wage", 0)) * 40 * 52


def max_loan_amount(borrowers, kind, collateral_value=0.0):
    combined_income = sum(annual_income(c) for c in borrowers)
    if kind == "secured":
        return round(combined_income * SECURED_INCOME_MULTIPLE
                     + collateral_value * SECURED_LOAN_TO_VALUE, 2)
    return round(combined_income * UNSECURED_INCOME_MULTIPLE, 2)


def _eligible(borrowers, kind):
    threshold = SECURED_MIN_CREDIT_SCORE if kind == "secured" else UNSECURED_MIN_CREDIT_SCORE
    from systems.credit import CREDIT_SCORE_DEFAULT
    # Joint application: every co-borrower must individually clear the
    # bar -- one bad-credit co-signer shouldn't be laundered through a
    # good-credit partner.
    return all(c.get("credit_score", CREDIT_SCORE_DEFAULT) >= threshold for c in borrowers)


def _monthly_payment(principal, annual_rate, term_months):
    r = annual_rate / 12
    if r == 0:
        return round(principal / term_months, 2)
    payment = principal * r / (1 - (1 + r) ** -term_months)
    return round(payment, 2)


def take_loan(world, borrowers, provider, kind, amount, target_bank_key, target_account,
              collateral_value=0.0):
    """borrowers: list of character dicts (1 = solo, 2+ = joint).
    Disburses `amount` into target_account at target_bank_key (an
    existing bank account one of the borrowers specified) via
    banking.py. Returns the loan dict on approval, None on decline."""
    if not borrowers or amount <= 0:
        return None
    if not _eligible(borrowers, kind):
        return None
    if amount > max_loan_amount(borrowers, kind, collateral_value):
        return None
    if kind == "secured" and collateral_value <= 0:
        return None

    from systems.banking import deposit
    if not deposit(world, target_bank_key, target_account, amount):
        return None

    household_id = borrowers[0].get("household_id")
    household = world.get("households", {}).get(household_id)
    if not household:
        return None

    term = SECURED_TERM_MONTHS if kind == "secured" else UNSECURED_TERM_MONTHS
    rate = SECURED_ANNUAL_RATE if kind == "secured" else UNSECURED_ANNUAL_RATE

    import uuid
    loan = {
        "id":              f"loan_{uuid.uuid4().hex[:8]}",
        "provider":        provider,
        "kind":            kind,
        "borrower_ids":    [c["id"] for c in borrowers],
        "principal":       round(amount, 2),
        "balance":         round(amount, 2),
        "rate":            rate,
        "term_months":     term,
        "monthly_payment": _monthly_payment(amount, rate, term),
        "start_tick":      world.get("tick", 0),
        "collateral_value": round(collateral_value, 2) if kind == "secured" else 0.0,
    }
    household.setdefault("loans", {})[loan["id"]] = loan
    return loan


def make_payment(loan, amount):
    """Pay down loan balance directly. Returns amount actually applied."""
    applied = min(amount, loan.get("balance", 0.0))
    loan["balance"] = round(loan.get("balance", 0.0) - applied, 2)
    return applied


def originate_mortgage(world, household, home):
    """Every household starts with a mortgage on their home (see the
    call site in household_manager.py/housing.py's home-assignment
    flow). Unlike take_loan() above, this doesn't deposit cash anywhere
    -- a mortgage finances the home purchase itself, which this sim
    already just assigns for free, so there's no "the bank hands you
    money" step to model. No credit-score/income eligibility gate
    either -- everyone needs somewhere to live, matching "everyone
    starts out with a loan on their home" verbatim; a real secured loan
    (take_loan, above) remains fully gated as before.

    home["rent"] is zeroed once a real mortgage exists -- it's the "rent
    OR mortgage payment" field (see housing.py's own comment), and
    weekly_loan_payments() below (already folded into economy.py's
    weekly bill, unchanged) picks up the mortgage automatically from
    here on purely because it's a loan with a positive balance; having
    BOTH a flat rent AND a real mortgage payment would double-charge.

    Returns the new loan dict, or None if the household already has a
    mortgage, has no members to attach it to, or the home has no real
    value set."""
    if any(l.get("kind") == "mortgage" for l in household.get("loans", {}).values()):
        return None
    value = home.get("value", 0)
    if value <= 0:
        return None

    chars = world.get("characters", {})
    borrower_ids = [
        cid for cid in household.get("members", [])
        if (chars.get(cid) or {}).get("age_group") in ("adult", "elderly")
    ] or list(household.get("members", []))[:1]
    if not borrower_ids:
        return None

    import uuid
    loan = {
        "id":               f"loan_{uuid.uuid4().hex[:8]}",
        "provider":         "starter_mortgage",
        "kind":             "mortgage",
        "borrower_ids":     borrower_ids,
        "principal":        round(value, 2),
        "balance":          round(value, 2),
        "rate":             MORTGAGE_ANNUAL_RATE,
        "term_months":      MORTGAGE_TERM_MONTHS,
        "monthly_payment":  _monthly_payment(value, MORTGAGE_ANNUAL_RATE, MORTGAGE_TERM_MONTHS),
        "start_tick":       world.get("tick", 0),
        "collateral_value": round(value, 2),
    }
    household.setdefault("loans", {})[loan["id"]] = loan
    home["rent"] = 0
    return loan


def weekly_loan_payments(household, world):
    """List of {loan_id, borrower_ids, amount} weekly-equivalent payment
    slices (monthly_payment / ~4.345 weeks) for every open loan on this
    household -- mirrors credit.py's minimum_payment folding into
    economy.py's weekly bill. Only loans with a positive balance still
    owe anything."""
    out = []
    for loan in household.get("loans", {}).values():
        if loan.get("balance", 0.0) <= 0:
            continue
        out.append({
            "loan_id":       loan["id"],
            "borrower_ids":  loan["borrower_ids"],
            "amount":        round(loan["monthly_payment"] / 4.345, 2),
        })
    return out
