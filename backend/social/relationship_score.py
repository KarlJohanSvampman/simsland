# =========================================================
# RELATIONSHIP SCORE
# =========================================================

def relationship_score(

    c,

    other_id
):

    trust = (
        c.get("trust", {})
        .get(other_id, 0)
    )

    attraction = (
        c.get("attraction", {})
        .get(other_id, 0)
    )

    chemistry = (
        c.get("chemistry", {})
        .get(other_id, 0)
    )

    familiarity = (
        c.get("familiarity", {})
        .get(other_id, 0)
    )

    friendship = (
        c.get("friendship", {})
        .get(other_id, 0)
    )

    hostility = (
        c.get("hostility", {})
        .get(other_id, 0)
    )

    score = 0
    alignment = belief_alignment(
    c,
    other
    )

    score += alignment * 0.2
    score += trust * 0.25
    score += attraction * 0.25
    score += chemistry * 0.20
    score += familiarity * 0.15
    score += friendship * 0.25

    score -= hostility * 0.40

    return score