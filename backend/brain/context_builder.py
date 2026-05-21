from brain.memory import (
    biased_recall
)

from social.relationship_score import (
    relationship_score
)

from social.reputation import (
    get_reputation
)

from brain.beliefs import (
    compute_alignment
)

from brain.cognitive_pressure import (
    build_cognitive_pressure
)

from systems.social import (

    build_relationship_context,

    build_message_context
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

    memories = biased_recall(

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
# SOCIAL CONTEXT
# =========================================================

def build_social_context(

    c,

    world
):

    return {

        "relationships":

            build_relationship_context(
                c,
                world
            ),

        "recent_messages":

            build_message_context(
                c,
                world
            )
    }

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

        "active_intentions":
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
            ),

        "conversations":
            build_conversation_context(
                c,
                world
            ),
        "current_turn":
            get_current_turn(
                c,
                world
            ),
        "beliefs": build_belief_context(c),
        "political_alignment": compute_alignment(c),
        "life_narratives": build_narratives(c),
        "self_model": build_self_model(c).
        "public_reputation":build_reputation_context(c,world),
        "schedule": build_schedule_context(c),
        "body_state": build_body_context(c),
        "household_resources":build_household_resource_context( c,world),
        "cognitive_pressure": build_cognitive_pressure(c),
        "social": build_social_context(c,world)
    }

    return context


# =========================================================
# ACTIVE CONVERSATIONS
# =========================================================

def build_conversation_context(

    c,

    world
):

    results = []

    for conv in world.get(
        "conversations",
        {}
    ).values():

        if not conv.get("active"):
            continue

        if c["id"] not in conv[
            "participants"
        ]:
            continue

        results.append({

            "topic":
                conv["topic"],

            "tone":
                conv["tone"],

            "recent_history":
                conv["history"][-5:],

            "turn_owner":
                conv["turn_owner"]
        })

    return results

    # =========================================================
# CURRENT TURN
# =========================================================

def get_current_turn(

    c,

    world
):

    for conv in world.get(
        "conversations",
        {}
    ).values():

        if not conv.get("active"):
            continue

        if conv.get(
            "turn_owner"
        ) == c["id"]:

            return {

                "conversation_id":
                    conv["id"],

                "topic":
                    conv["topic"],

                "tone":
                    conv["tone"],

                "participants":
                    conv["participants"],

                "recent_history":
                    conv["history"][-5:]
            }

    return None

    # =========================================================
# BUILD BELIEF CONTEXT
# =========================================================

def build_belief_context(c):

    results = []

    for topic, belief in c.get(
        "beliefs",
        {}
    ).items():

        value = belief.get(
            "value",
            0
        )

        certainty = belief.get(
            "certainty",
            0
        )

        # =====================================
        # INTERPRETATION
        # =====================================

        if value > 0.6:

            interpretation = (
                f"You strongly support "
                f"{topic}."
            )

        elif value > 0.2:

            interpretation = (
                f"You somewhat support "
                f"{topic}."
            )

        elif value < -0.6:

            interpretation = (
                f"You strongly oppose "
                f"{topic}."
            )

        elif value < -0.2:

            interpretation = (
                f"You somewhat oppose "
                f"{topic}."
            )

        else:

            interpretation = (
                f"You feel conflicted or "
                f"uncertain about {topic}."
            )

        results.append({

            "topic":
                topic,

            "certainty":
                certainty,

            "interpretation":
                interpretation
        })

    return results

# =========================================================
# BUILD NARRATIVES
# =========================================================

def build_narratives(c):

    return c.get(
        "narratives",
        []
    )[-5:]


# =========================================================
# BUILD SELF MODEL
# =========================================================

def build_self_model(c):

    results = []

    for key, v in c.get(
        "self_model",
        {}
    ).items():

        results.append({

            "aspect": key,

            "identity":
                v.get("value"),

            "confidence":
                v.get(
                    "confidence",
                    0
                )
        })

    return results

# =========================================================
# PUBLIC REPUTATION
# =========================================================

def build_reputation_context(

    c,

    world
):

    rep = get_reputation(

        world,

        c["id"]
    )

    return {

        "trust":
            rep["trust"],

        "respect":
            rep["respect"],

        "fear":
            rep["fear"],

        "controversy":
            rep["controversy"]
    }

    # =========================================================
# BUILD SCHEDULE CONTEXT
# =========================================================

def build_schedule_context(c):

    block = c.get(
        "active_schedule_block"
    )

    if not block:
        return None

    return {

        "type":
            block["type"],

        "start":
            block["start"],

        "end":
            block["end"]
    }

# =========================================================
# BODY CONTEXT
# =========================================================

def build_body_context(c):

    b = c.get(
        "body",
        {}
    )

    issues = []

    if b.get("bladder", 0) > 70:

        issues.append(
            "You urgently need "
            "to use a toilet."
        )

    if b.get("fatigue", 0) > 70:

        issues.append(
            "You feel exhausted."
        )

    if b.get("hygiene", 100) < 30:

        issues.append(
            "You feel dirty and "
            "socially uncomfortable."
        )

    if b.get("hunger", 0) > 70:

        issues.append(
            "You are very hungry."
        )

    return issues

# =========================================================
# HOUSEHOLD RESOURCE CONTEXT
# =========================================================

def build_household_resource_context(

    c,

    world
):

    household_id = c.get(
        "household_id"
    )

    if not household_id:
        return None

    household = get_household(
        world,
        household_id
    )

    if not household:
        return None

    resources = household.get(
        "resources",
        {}
    )

    return {

        "food":
            resources.get(
                "food",
                0
            ),

        "quick_food":
            resources.get(
                "quick_food",
                0
            ),

        "drinks":
            resources.get(
                "drinks",
                0
            )
    }



