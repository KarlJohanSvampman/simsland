from brain.memory import (
    recall_relevant
)

from social.relationship_score import (
    relationship_score
)


# =========================================================
# RELATIONSHIP SUMMARY
# =========================================================

def summarize_relationship(

    c,

    other
):

    score = relationship_score(

        c,

        other["id"]
    )

    if score > 80:

        return (
            f"You feel very close to "
            f"{other['name']}."
        )

    if score > 40:

        return (
            f"You generally like "
            f"{other['name']}."
        )

    if score < -50:

        return (
            f"You strongly dislike "
            f"{other['name']}."
        )

    if score < 0:

        return (
            f"You feel uneasy around "
            f"{other['name']}."
        )

    return (
        f"You have neutral feelings "
        f"toward {other['name']}."
    )


# =========================================================
# VISIBLE PEOPLE
# =========================================================

def build_visible_people(

    c,

    world
):

    visible = []

    for other in world.get(
        "characters",
        {}
    ).values():

        if other["id"] == c["id"]:
            continue

        dx = abs(
            other["x"] - c["x"]
        )

        dy = abs(
            other["y"] - c["y"]
        )

        if dx <= 8 and dy <= 8:

            visible.append({

                "id":
                    other["id"],

                "name":
                    other["name"],

                "emotion":
                    other.get(
                        "emotion",
                        "neutral"
                    ),

                "relationship":
                    summarize_relationship(
                        c,
                        other
                    )
            })

    return visible


# =========================================================
# RELEVANT MEMORIES
# =========================================================

def build_memories(

    c,

    limit=10
):

    memories = recall_relevant(

        c,

        "recent important events",

        limit
    )

    results = []

    for m in memories:

        results.append({

            "text":
                m.get("text"),

            "importance":
                m.get(
                    "importance",
                    0
                ),

            "emotion":
                m.get(
                    "emotional_impact",
                    0
                ),

            "tags":
                m.get(
                    "tags",
                    []
                )
        })

    return results


# =========================================================
# ACTIVE INTENTIONS
# =========================================================

def build_intentions(c):

    intentions = []

    for i in c.get(
        "active_intentions",
        []
    ):

        intentions.append({

            "type":
                i.get("type"),

            "priority":
                i.get("priority"),

            "progress":
                i.get(
                    "progress",
                    0
                ),

            "reason":
                i.get("reason")
        })

    return intentions


# =========================================================
# AVAILABLE ACTIONS
# =========================================================

def build_available_actions(

    c,

    world
):

    return [

        "move",

        "speak",

        "interact",

        "wait",

        "call",

        "text",

        "eat",

        "sleep",

        "work",

        "socialize"
    ]


# =========================================================
# MAIN CONTEXT BUILDER
# =========================================================

def build_context(

    c,

    world
):

    context = {

        # =====================================
        # IDENTITY
        # =====================================

        "identity": {

            "name":
                c.get("name"),

            "age":
                c.get("age"),

            "traits":
                c.get(
                    "traits",
                    []
                ),

            "occupation":
                c.get(
                    "occupation"
                )
        },

        # =====================================
        # INTERNAL STATE
        # =====================================

        "internal_state": {

            "emotion":
                c.get(
                    "emotion",
                    "neutral"
                ),

            "needs":
                c.get(
                    "needs",
                    {}
                ),

            "stress":
                c.get(
                    "stress",
                    0
                ),

            "energy":
                c.get(
                    "energy",
                    100
                )
        },

        # =====================================
        # ACTIVE INTENTIONS
        # =====================================

        "intentions":
            build_intentions(c),

        # =====================================
        # MEMORIES
        # =====================================

        "memories":
            build_memories(c),

        # =====================================
        # VISIBLE PEOPLE
        # =====================================

        "visible_people":
            build_visible_people(
                c,
                world
            ),

        # =====================================
        # CURRENT LOCATION
        # =====================================

        "location": {

            "building":
                c.get(
                    "building_id"
                ),

            "room":
                c.get(
                    "room_id"
                )
        },

        # =====================================
        # PHONE
        # =====================================

        "phone_notifications":
            c.get(
                "phone_notifications",
                []
            ),

        # =====================================
        # NEWS
        # =====================================

        "news":
            world.get(
                "news_feed",
                []
            )[:5],

        # =====================================
        # ACTIONS
        # =====================================

        "available_actions":
            build_available_actions(
                c,
                world
            )
    }

    return context