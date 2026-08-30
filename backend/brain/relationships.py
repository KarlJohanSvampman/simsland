import time
import math

from systems.contacts import (
    update_contact,
    maybe_learn_phone
)

from brain.beliefs import (
    belief_alignment
)


# =========================================================
# ENSURE STORAGE
# =========================================================

def ensure_relationships(c):

    c.setdefault(
        "relationships",
        {}
    )


# =========================================================
# ENSURE RELATIONSHIP
# =========================================================

def ensure_relationship(

    c,

    other_id
):

    ensure_relationships(c)

    rels = c["relationships"]

    if other_id not in rels:

        rels[other_id] = {

            # =============================================
            # CORE SOCIAL STATE
            # =============================================

            "familiarity": 0,

            "trust": 0,

            "friendship": 0,

            "respect": 0,

            "attraction": 0,

            # True once the character makes a public approach revealing their interest
            "attraction_visible": False,

            "romantic_interest": 0,

            "sexual_interest": 0,

            "comfort": 0,

            "dependency": 0,

            "resentment": 0,

            "hostility": 0,

            "fear": 0,

            "rivalry": 0,

            "chemistry": 0,

            # =============================================
            # HISTORY
            # =============================================

            "history_score": 0,

            "memories_shared": 0,

            "interaction_count": 0,

            # Cumulative proximity/exposure ticks, distinct from
            # interaction_count -- incremented just by being visibly nearby,
            # not by actually interacting. See systems/influence.py.
            "exposure_ticks": 0,

            "positive_interactions": 0,

            "negative_interactions": 0,

            # =============================================
            # METADATA
            # =============================================

            "compatibility": 0,

            "state": "stranger",

            # Contact-designation tier (definitions.json's
            # contact_designations) -- deliberately separate from "state"
            # above (that's live stat-threshold-driven and gates 10+
            # unrelated behavior systems). This is purely hours-in-room
            # driven, re-evaluated once a week -- see
            # systems/contact_designation.py.
            "designation": "stranger",

            # Real hours spent physically co-present this week, reset by
            # the weekly designation-evaluation pass. See
            # systems/contact_designation.py.
            "hours_this_week": 0.0,

            "labels": [],

            "kinship": None,

            # Personal expectations THIS character holds of this specific
            # other one (dress/friends/career/faith/partner-choice type
            # value-alignment clashes, not the role-based checkboxes in
            # c["expectations"]) -- keyed by topic string, see
            # systems/persona_expectations.py.
            "personal_expectations": {},

            # Favor ledger -- recent favors THIS character granted TO the
            # other party (systems/favors.py), plus the frustration that
            # committing to (and not being repaid for) favors builds up.
            "favors": [],
            "favor_frustration": 0.0,

            # systems/intimate_item_discovery.py -- stumbled onto
            # evidence of the other person's private sex life (a found
            # item, discovered computer history). Not a grievance --
            # nothing was done TO the discoverer, just a standing dent
            # to how they see this person.
            "creeped_out": 0.0,

            # systems/life_comparison.py -- builds only from comparisons
            # that land favorably for the OTHER person, never the
            # observer's own wins. Decays like every other relationship-
            # stat tracker this session has built.
            "jealousy": 0.0,

            "known_secrets": [],

            "shared_groups": [],

            "last_interaction": 0,

            "last_seen": 0
        }

    return rels[other_id]


# =========================================================
# MODIFY RELATIONSHIP
# =========================================================

def modify_relationship(

    c,

    other_id,

    stat,

    amount
):

    rel = ensure_relationship(

        c,

        other_id
    )

    rel[stat] = clamp_relationship(

        rel.get(stat, 0)

        + amount
    )

    update_relationship_state(
        c,
        other_id
    )


# =========================================================
# UPDATE STATE LABEL
# =========================================================

def update_relationship_state(

    c,

    other_id
):

    rel = ensure_relationship(

        c,

        other_id
    )

    friendship = rel["friendship"]

    attraction = rel["attraction"]

    hostility = rel["hostility"]

    familiarity = rel["familiarity"]

    trust = rel["trust"]

    if hostility > 60:

        state = "enemy"

    elif attraction > 60:

        state = "romantic_interest"

    elif friendship > 60:

        state = "close_friend"

    elif friendship > 30:

        state = "friend"

    elif familiarity > 15:

        state = "acquaintance"

    elif trust < -40:

        state = "distrusted"

    else:

        state = "stranger"

    rel["state"] = state


# =========================================================
# APPLY INTERACTION
# =========================================================

def apply_interaction(

    c,

    other,

    speech_act
):

    oid = other["id"]

    rel = ensure_relationship(
        c,
        oid
    )

    other_rel = ensure_relationship(
        other,
        c["id"]
    )

    # =====================================================
    # CONTACTS
    # =====================================================

    update_contact(c, other)
    update_contact(other, c)

    maybe_learn_phone(c, other)
    maybe_learn_phone(other, c)

    # =====================================================
    # INTERACTION COUNTS
    # =====================================================

    rel["interaction_count"] += 1
    other_rel["interaction_count"] += 1

    rel["last_interaction"] = time.time()
    other_rel["last_interaction"] = time.time()

    rel["last_seen"] = time.time()
    other_rel["last_seen"] = time.time()

    # =====================================================
    # FAMILIARITY ALWAYS RISES
    # =====================================================

    rel["familiarity"] += 0.5
    other_rel["familiarity"] += 0.5

    # =====================================================
    # SPEECH ACT EFFECTS
    # =====================================================

    positive = {

        "compliment",

        "comfort",

        "supportive",

        "flirt",

        "joke"
    }

    negative = {

        "insult",

        "dismissive",

        "challenge",

        "threat"
    }

    vulnerable = {

        "confession",

        "vulnerable"
    }

    # -----------------------------------------------------
    # POSITIVE
    # -----------------------------------------------------

    if speech_act in positive:

        rel["friendship"] += 2
        other_rel["friendship"] += 2

        rel["chemistry"] += 1
        other_rel["chemistry"] += 1

        rel["comfort"] += 1
        other_rel["comfort"] += 1

        rel["positive_interactions"] += 1
        other_rel["positive_interactions"] += 1

    # -----------------------------------------------------
    # FLIRT
    # -----------------------------------------------------

    if speech_act == "flirt":

        rel["attraction"] += 4
        other_rel["attraction"] += 2

        rel["romantic_interest"] += 3

    # -----------------------------------------------------
    # VULNERABILITY
    # -----------------------------------------------------

    if speech_act in vulnerable:

        rel["trust"] += 3
        other_rel["trust"] += 2

        rel["comfort"] += 2
        other_rel["comfort"] += 2

    # -----------------------------------------------------
    # NEGATIVE
    # -----------------------------------------------------

    if speech_act in negative:

        rel["hostility"] += 4
        other_rel["hostility"] += 5

        rel["resentment"] += 2
        other_rel["resentment"] += 3

        rel["negative_interactions"] += 1
        other_rel["negative_interactions"] += 1

        rel["trust"] -= 3
        other_rel["trust"] -= 4

    # =====================================================
    # CLAMP
    # =====================================================

    normalize_relationship(rel)
    normalize_relationship(other_rel)

    update_relationship_state(
        c,
        oid
    )

    update_relationship_state(
        other,
        c["id"]
    )


# =========================================================
# FIRST IMPRESSION
# =========================================================

def first_impression(

    c,

    other
):

    rel = ensure_relationship(

        c,

        other["id"]
    )

    if rel["familiarity"] > 0:
        return

    appearance = other.get(
        "appearance",
        {}
    )

    score = 0

    posture = appearance.get(
        "posture"
    )

    eyes = appearance.get(
        "eyes"
    )

    if posture in [

        "confident",

        "straight"
    ]:

        score += 3

    elif posture in [

        "slouched",

        "hesitant"
    ]:

        score -= 1

    if eyes == "expressive":

        score += 2

    elif eyes == "lifeless":

        score -= 3

    rel["familiarity"] += 5

    rel["attraction"] += score

    rel["chemistry"] += score * 0.5

    normalize_relationship(rel)

    update_relationship_state(
        c,
        other["id"]
    )


# =========================================================
# COMPATIBILITY
# =========================================================

def calculate_compatibility(

    c,

    other
):

    try:

        alignment = belief_alignment(
            c,
            other
        )

    except Exception:

        alignment = 0

    shared_traits = len(set(

        c.get("traits", [])

        &

        set(other.get(
            "traits",
            []
        ))
    ))

    compatibility = (

        alignment * 0.7

        +

        shared_traits * 5
    )

    rel = ensure_relationship(

        c,

        other["id"]
    )

    rel["compatibility"] = int(
        compatibility
    )

    return compatibility


# =========================================================
# NORMALIZE
# =========================================================

def normalize_relationship(rel):

    for k, v in rel.items():

        if isinstance(v, (int, float)):

            rel[k] = clamp_relationship(v)


# =========================================================
# DECAY
# =========================================================

def decay_relationships(world):

    now = time.time()

    for c in world[
        "characters"
    ].values():

        for oid, rel in c.get(
            "relationships",
            {}
        ).items():

            last = rel.get(
                "last_interaction",
                now
            )

            dt = now - last

            # =============================================
            # VERY SLOW DECAY
            # =============================================

            if dt > 3600:

                rel["comfort"] *= 0.9995

                rel["friendship"] *= 0.9997

                rel["attraction"] *= 0.9996

                rel["resentment"] *= 0.9998

                rel["hostility"] *= 0.9999

                normalize_relationship(
                    rel
                )


# =========================================================
# CLAMP
# =========================================================

def clamp_relationship(v):

    return max(

        -100,

        min(
            100,
            float(v)
        )
    )