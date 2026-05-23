from systems.relationships import (
    ensure_relationship
)

from brain.beliefs import (
    belief_alignment
)


# =========================================================
# RELATIONSHIP SCORE
# =========================================================

def relationship_score(

    c,

    other
):

    other_id = other["id"]

    rel = ensure_relationship(

        c,

        other_id
    )

    trust = rel["trust"]

    attraction = rel["attraction"]

    chemistry = rel["chemistry"]

    familiarity = rel["familiarity"]

    friendship = rel["friendship"]

    hostility = rel["hostility"]

    respect = rel["respect"]

    comfort = rel["comfort"]

    resentment = rel["resentment"]

    compatibility = rel.get(
        "compatibility",
        0
    )

    # =====================================================
    # BELIEF ALIGNMENT
    # =====================================================

    try:

        alignment = belief_alignment(
            c,
            other
        )

    except Exception:

        alignment = 0

    # =====================================================
    # SCORE
    # =====================================================

    score = 0

    score += alignment * 0.15

    score += trust * 0.25

    score += attraction * 0.15

    score += chemistry * 0.15

    score += familiarity * 0.10

    score += friendship * 0.20

    score += comfort * 0.10

    score += respect * 0.10

    score += compatibility * 0.05

    score -= hostility * 0.35

    score -= resentment * 0.25

    return score