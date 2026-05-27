import random


# =========================================================
# SHOULD CONTRIBUTE
# =========================================================

def should_contribute(

    c,

    household
):

    if c.get(
        "money",
        0
    ) <= 0:

        return False

    relationship_stress = household.get(
        "relationship_stress",
        0
    )

    generosity = c.get(
        "financial_behavior",
        {}
    ).get(
        "generosity",
        0.5
    )

    trust = c.get(
        "financial_behavior",
        {}
    ).get(
        "financial_trust",
        0.5
    )

    willingness = (

        generosity * 0.5 +

        trust * 0.5 -

        relationship_stress * 0.5
    )

    return random.random() < willingness


# =========================================================
# DETERMINE CONTRIBUTION
# =========================================================

def determine_contribution(

    c,

    household
):

    money = c.get(
        "money",
        0
    )

    if money <= 0:
        return 0

    frugality = c.get(
        "financial_behavior",
        {}
    ).get(
        "frugality",
        0.5
    )

    generosity = c.get(
        "financial_behavior",
        {}
    ).get(
        "generosity",
        0.5
    )

    ratio = (

        0.1 +

        generosity * 0.5 -

        frugality * 0.2
    )

    ratio = max(
        0.05,
        min(
            ratio,
            0.8
        )
    )

    return money * ratio


# =========================================================
# PROCESS CONTRIBUTIONS
# =========================================================

def process_household_contributions(world):

    for household in world.get(
        "households",
        {}
    ).values():

        for cid in household.get(
            "members",
            []
        ):

            c = world.get(
                "characters",
                {}
            ).get(cid)

            if not c:
                continue

            if not should_contribute(
                c,
                household
            ):
                continue

            amount = determine_contribution(
                c,
                household
            )

            if amount <= 0:
                continue

            amount = min(
                amount,
                c.get(
                    "money",
                    0
                )
            )

            c["money"] -= amount

            household[
                "shared_funds"
            ] += amount