import random

from brain.relationships import (
    ensure_relationship
)

from social.relationship_score import (
    relationship_score
)


# =========================================================
# UPDATE SOCIAL INTENTIONS
# =========================================================

def update_social_intentions(

    c,

    world
):

    relationships = c.get(
        "relationships",
        {}
    )

    if not relationships:
        return

    for other_id in relationships:

        other = world[
            "characters"
        ].get(
            other_id
        )

        if not other:
            continue

        generate_social_intentions(

            c,

            other,

            world
        )


# =========================================================
# GENERATE
# =========================================================

def generate_social_intentions(

    c,

    other,

    world
):

    rel = ensure_relationship(

        c,

        other["id"]
    )

    emotion = c.get(
        "emotion",
        "neutral"
    )

    score = relationship_score(
        c,
        other
    )

    # =====================================================
    # SOCIAL NEEDS
    # =====================================================

    # Loneliness = frustration of the socialize lt_need (0-1)
    loneliness = c.get("lt_needs", {}).get("socialize", {}).get("frustration", 0.0)

    from systems.body import body_energy
    energy = body_energy(c)

    # =====================================================
    # BASIC VALUES
    # =====================================================

    friendship = rel[
        "friendship"
    ]

    trust = rel[
        "trust"
    ]

    attraction = rel[
        "attraction"
    ]

    hostility = rel[
        "hostility"
    ]

    comfort = rel[
        "comfort"
    ]

    resentment = rel[
        "resentment"
    ]

    familiarity = rel[
        "familiarity"
    ]

    romantic_interest = rel[
        "romantic_interest"
    ]

    dependency = rel[
        "dependency"
    ]

    # =====================================================
    # SOCIAL CONTACT
    # =====================================================

    contact_score = (

        loneliness * 0.6

        +

        friendship * 0.25

        +

        comfort * 0.20

        +

        familiarity * 0.10
    )

    if emotion in [

        "sad",

        "lonely",

        "insecure"
    ]:

        contact_score += 10

    if energy < 0.2:

        contact_score *= 0.5

    if hostility > 40:

        contact_score *= 0.2

    if contact_score > 20:

        add_social_intention(

            c,

            {

                "type":
                    "contact_person",

                "target_id":
                    other["id"],

                "priority":
                    int(contact_score),

                "reason":
                    "social_connection"
            }
        )

    # =====================================================
    # VISIT
    # =====================================================

    visit_score = (

        friendship * 0.20

        +

        comfort * 0.30

        +

        attraction * 0.10
    )

    if rel["state"] in [

        "close_friend",

        "romantic_interest"
    ]:

        visit_score += 10

    if visit_score > 30:

        add_social_intention(

            c,

            {

                "type":
                    "visit_person",

                "target_id":
                    other["id"],

                "priority":
                    int(visit_score),

                "reason":
                    "desire_proximity"
            }
        )

    # =====================================================
    # FLIRT
    # =====================================================

    flirt_score = (

        attraction * 0.5

        +

        romantic_interest * 0.4

        +

        chemistry_modifier(rel)
    )

    if trust < 0:

        flirt_score *= 0.4

    if hostility > 20:

        flirt_score *= 0.2

    if flirt_score > 35:

        add_social_intention(

            c,

            {

                "type":
                    "flirt",

                "target_id":
                    other["id"],

                "priority":
                    int(flirt_score),

                "reason":
                    "romantic_interest"
            }
        )

    # =====================================================
    # COMPLIMENT (looks vs. character) — see attraction.py
    # ::compute_ideal_match(). Mirrors flirt_score's shape/thresholds;
    # whichever half of the ideal-partner match is strong gets its own
    # intention so the LLM knows what to actually praise.
    # =====================================================

    from systems.attraction import compute_ideal_match
    ideal_match = compute_ideal_match(c, other)

    compliment_looks_score = ideal_match["physical"] * 60 + familiarity * 0.2
    compliment_character_score = ideal_match["trait"] * 60 + friendship * 0.2

    if hostility > 20:
        compliment_looks_score *= 0.2
        compliment_character_score *= 0.2

    if compliment_looks_score > 45:
        add_social_intention(c, {
            "type":      "compliment_looks",
            "target_id": other["id"],
            "priority":  int(compliment_looks_score),
            "reason":    "ideal_physical_match",
        })

    if compliment_character_score > 45:
        add_social_intention(c, {
            "type":      "compliment_character",
            "target_id": other["id"],
            "priority":  int(compliment_character_score),
            "reason":    "ideal_personality_match",
        })

    # =====================================================
    # SEEK COMFORT
    # =====================================================

    comfort_score = (

        trust * 0.3

        +

        comfort * 0.5
    )

    if emotion in [

        "sad",

        "anxious",

        "depressed"
    ]:

        comfort_score += 20

    if comfort_score > 30:

        add_social_intention(

            c,

            {

                "type":
                    "seek_comfort",

                "target_id":
                    other["id"],

                "priority":
                    int(comfort_score),

                "reason":
                    "emotional_support"
            }
        )

    # =====================================================
    # AVOIDANCE
    # =====================================================

    avoid_score = (

        hostility * 0.5

        +

        resentment * 0.4
    )

    if avoid_score > 35:

        add_social_intention(

            c,

            {

                "type":
                    "avoid_person",

                "target_id":
                    other["id"],

                "priority":
                    int(avoid_score),

                "reason":
                    "negative_relationship"
            }
        )

    # =====================================================
    # APOLOGY
    # =====================================================

    apology_score = (

        friendship * 0.2

        +

        trust * 0.2

        +

        resentment * 0.2
    )

    if emotion in [

        "guilty",

        "ashamed"
    ]:

        apology_score += 20

    if apology_score > 25:

        add_social_intention(

            c,

            {

                "type":
                    "apologize",

                "target_id":
                    other["id"],

                "priority":
                    int(apology_score),

                "reason":
                    "relationship_repair"
            }
        )

    # =====================================================
    # GOSSIP
    # =====================================================

    gossip_score = (

        friendship * 0.15

        +

        familiarity * 0.10
    )

    if emotion in [

        "excited",

        "dramatic"
    ]:

        gossip_score += 10

    if gossip_score > 18:

        add_social_intention(

            c,

            {

                "type":
                    "gossip",

                "target_id":
                    other["id"],

                "priority":
                    int(gossip_score),

                "reason":
                    "social_bonding"
            }
        )


# =========================================================
# ADD
# =========================================================

def add_social_intention(

    c,

    intention
):

    c.setdefault(
        "active_intentions",
        []
    )

    # =====================================================
    # DEDUPLICATION
    # =====================================================

    for existing in c[
        "active_intentions"
    ]:

        if (

            existing.get("type")
            ==
            intention["type"]

            and

            existing.get("target_id")
            ==
            intention["target_id"]
        ):

            existing["priority"] = max(

                existing.get(
                    "priority",
                    0
                ),

                intention[
                    "priority"
                ]
            )

            return

    c[
        "active_intentions"
    ].append(
        intention
    )


# =========================================================
# CHEMISTRY
# =========================================================

def chemistry_modifier(rel):

    chemistry = rel.get(
        "chemistry",
        0
    )

    return chemistry * 0.25