def apply_expenses(world):
    """
    Issue a weekly bill to each household covering all recurring costs.
    Reads per-home expense fields (rent, electricity, water, gasoline,
    internet) then adds market-index-scaled food costs on top.
    """
    cal = world.get("calendar", {})
    if not (cal.get("weekday") == "Monday" and cal.get("hour") == 0):
        return

    from systems.housing import get_household_home, weekly_home_expenses
    env = world.get("environment", {})

    for h in world.get("households", {}).values():
        home      = get_household_home(h, world)
        n_members = max(1, len(h.get("members", [])))

        # Fixed home costs (rent, utilities, gasoline, internet)
        if home:
            fixed = weekly_home_expenses(home) * env.get("cost_of_living_index", 1.0)
        else:
            fixed = 150.0 * env.get("cost_of_living_index", 1.0)

        # Variable: food scales with household size and market price
        food = 80.0 * n_members * env.get("cost_of_living_index", 1.0)

        # Hobbies: each member's hobbies contribute annual_cost / 52 per week
        hobby_templates = world.get("definitions", {}).get("hobby_templates", {})
        hobbies_weekly = 0.0

        # Credit card minimum payments (current_debt / 12, see credit.py)
        # folded into the same weekly bill as everything else -- the debt
        # is real household upkeep the same way rent is, per explicit user
        # direction. Tracked per-CARD (credit_card_payments) so
        # mail.py::attempt_pay_bills() can apply the real paydown once the
        # bill settles; credit_card_by_member is the same data grouped by
        # owner purely for the friction narrative (see brain/
        # context_builder.py::_sec_finances) -- "someone else is paying
        # for my sibling's credit card debt".
        from systems.credit import get_credit_cards, minimum_payment
        credit_card_weekly = 0.0
        credit_card_payments = []
        for cid in h.get("members", []):
            c = world.get("characters", {}).get(cid)
            if not c:
                continue
            for hid in c.get("hobbies", []):
                tmpl = hobby_templates.get(hid)
                if tmpl:
                    hobbies_weekly += tmpl.get("annual_cost", 0) / 52.0

            for card in get_credit_cards(c):
                monthly_min = minimum_payment(card)
                if monthly_min <= 0:
                    continue
                weekly = round(monthly_min / 4.345, 2)
                credit_card_weekly += weekly
                credit_card_payments.append({
                    "character_id": cid, "name": c.get("name", cid),
                    "card_id": card["id"], "amount": weekly,
                })

        credit_card_by_member = []
        for entry in credit_card_payments:
            existing = next((m for m in credit_card_by_member if m["character_id"] == entry["character_id"]), None)
            if existing:
                existing["amount"] = round(existing["amount"] + entry["amount"], 2)
            else:
                credit_card_by_member.append({
                    "character_id": entry["character_id"], "name": entry["name"], "amount": entry["amount"],
                })

        # Loan payments -- same weekly-slice treatment as credit cards.
        # loan_payments carries EVERY loan (solo + joint) for actual
        # paydown; loan_by_borrower is the solo-only subset used for the
        # friction narrative -- joint loans deliberately aren't attributed
        # to any one person, both borrowers agreed to and benefit from
        # those, so they're not the "someone else is paying for my debt"
        # case, but their balance still needs to go down like any other.
        from systems.loans import weekly_loan_payments
        chars = world.get("characters", {})
        loan_weekly = 0.0
        loan_payments = weekly_loan_payments(h, world)
        loan_by_borrower = []
        for entry in loan_payments:
            loan_weekly += entry["amount"]
            if len(entry["borrower_ids"]) == 1:
                borrower = chars.get(entry["borrower_ids"][0])
                loan_by_borrower.append({
                    "character_id": entry["borrower_ids"][0],
                    "name": borrower.get("name", entry["borrower_ids"][0]) if borrower else entry["borrower_ids"][0],
                    "amount": entry["amount"],
                })

        # Subscriptions (home/life insurance, home internet, home
        # security monitoring, entertainment -- systems/subscriptions.py)
        # plus vehicle insurance (a per-vehicle field, not a household
        # subscription record -- see that module's own docstring for
        # why). Both are real recurring costs the same way rent/credit
        # cards/loans already are.
        from systems.subscriptions import weekly_subscriptions_total, household_vehicle_insurance_weekly
        subscriptions_weekly = weekly_subscriptions_total(h)
        vehicle_insurance_weekly = household_vehicle_insurance_weekly(world, h.get("id"))

        total = round(
            fixed + food + hobbies_weekly + credit_card_weekly + loan_weekly
            + subscriptions_weekly + vehicle_insurance_weekly,
            2,
        )

        h.setdefault("bills_due", []).append({
            "type":         "weekly",
            "amount":       total,
            "remaining":    total,
            "contributors": {},
            "breakdown": {
                "fixed_home":         round(fixed, 2),
                "food":               round(food, 2),
                "hobbies":            round(hobbies_weekly, 2),
                "credit_cards":       round(credit_card_weekly, 2),
                "loans":              round(loan_weekly, 2),
                "subscriptions":      round(subscriptions_weekly, 2),
                "vehicle_insurance":  round(vehicle_insurance_weekly, 2),
            },
            "credit_card_payments":  credit_card_payments,
            "credit_card_by_member": credit_card_by_member,
            "loan_payments":         loan_payments,
            "loan_by_borrower":      loan_by_borrower,
        })

        # Cache so the schedule generator can read it without recalculating
        h["weekly_expenses"] = total


def household_economy(world, household_id):
    h = world["households"].get(household_id)
    if not h:
        return None
    members = [
        world["characters"][cid]
        for cid in h.get("members", [])
        if cid in world["characters"]
    ]
    return {
        **h,
        "members":    [m["name"] for m in members],
        "market":     world.get("market"),
    }
