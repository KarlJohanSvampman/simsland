# =========================================================
# ENSURE NARRATIVES
# =========================================================

def ensure_narratives(c):

    c.setdefault(
        "narratives",
        []
    )


# =========================================================
# ADD NARRATIVE
# =========================================================

def add_narrative(

    c,

    text,

    tags=None,

    importance=0.5
):

    ensure_narratives(c)

    c["narratives"].append({

        "text": text,

        "tags": tags or [],

        "importance": importance
    })

    c["narratives"] = (
        c["narratives"][-20:]
    )


# =========================================================
# RELATIONSHIP NARRATIVES
# =========================================================

def consolidate_relationship_narratives(c):

    memories = c.get(
        "memories",
        []
    )

    people = {}

    for m in memories:

        for pid in m.get(
            "people",
            []
        ):

            people.setdefault(
                pid,
                []
            ).append(m)

    for pid, mems in people.items():

        positive = 0
        negative = 0

        for m in mems:

            impact = m.get(
                "emotional_impact",
                0
            )

            if impact > 0:
                positive += impact

            elif impact < 0:
                negative += abs(impact)

        # =====================================
        # POSITIVE ARC
        # =====================================

        if positive > 20:

            add_narrative(

                c,

                f"You feel increasingly "
                f"close to {pid}.",

                tags=[
                    "relationship",
                    pid
                ],

                importance=0.7
            )

        # =====================================
        # NEGATIVE ARC
        # =====================================

        elif negative > 20:

            add_narrative(

                c,

                f"Your relationship with "
                f"{pid} feels strained.",

                tags=[
                    "relationship",
                    pid
                ],

                importance=0.7
            )

# =========================================================
# LIFE STRESS NARRATIVES
# =========================================================

def consolidate_life_narratives(c):

    stress = c.get(
        "stress",
        0
    )

    money = c.get(
        "money",
        0
    )

    # =====================================
    # STRESS
    # =====================================

    if stress > 80:

        add_narrative(

            c,

            "Life has felt overwhelming lately.",

            tags=["stress"],

            importance=0.9
        )

    # =====================================
    # FINANCIAL
    # =====================================

    if money < 50:

        add_narrative(

            c,

            "Money problems are becoming "
            "hard to ignore.",

            tags=["economy"],

            importance=0.8
        )