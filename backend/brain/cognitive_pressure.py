# =========================================================
# BUILD COGNITIVE PRESSURE
# =========================================================

def build_cognitive_pressure(c):

    intentions = c.get(
        "active_intentions",
        []
    )

    if not intentions:
        return []

    pressures = []

    top = intentions[:3]

    for i in top:

        category = i.get(
            "category"
        )

        intention_type = i.get(
            "type"
        )

        # =================================
        # SURVIVAL
        # =================================

        if category == "survival":

            if intention_type == "sleep":

                pressures.append(
                    "You are struggling "
                    "with severe fatigue."
                )

            elif intention_type == "drink":

                pressures.append(
                    "You feel dehydrated "
                    "and physically uncomfortable."
                )

            elif intention_type == "use_toilet":

                pressures.append(
                    "You urgently need "
                    "to find a toilet."
                )

            elif intention_type == "eat_food":

                pressures.append(
                    "Hunger is distracting "
                    "your thoughts."
                )

        # =================================
        # HEALTH
        # =================================

        elif category == "health":

            pressures.append(
                "Your physical comfort "
                "and hygiene feel important."
            )

        # =================================
        # SOCIAL
        # =================================

        elif category == "social":

            pressures.append(
                "You strongly desire "
                "social connection."
            )

        # =================================
        # IDENTITY
        # =================================

        elif category == "identity":

            pressures.append(
                "You are unusually aware "
                "of your self-image."
            )

        # =================================
        # SCHEDULE
        # =================================

        elif category == "schedule":

            pressures.append(
                "You feel pressure to "
                "maintain your responsibilities."
            )

    return pressures