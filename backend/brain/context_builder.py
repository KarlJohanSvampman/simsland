from brain.memory import (
    biased_recall
)

from social.relationship_score import (
    relationship_score
)

from brain.beliefs import (
    compute_alignment
)

from brain.cognitive_pressure import (
    build_cognitive_pressure
)

from systems.social import (
    build_message_context
)

from brain.conversations import (
    find_conversation
)

from brain.memory import (
    biased_recall
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
# RELATIONSHIP CONTEXT
# Uses the full brain/relationships.py schema to produce a
# natural-language summary of each known relationship, sorted
# by significance (most emotionally charged first).
# =========================================================

def build_relationship_context(c, world, limit=10):
    import time
    now = time.time()
    chars = world.get("characters", {})
    results = []

    for other_id, rel in c.get("relationships", {}).items():
        # Skip if truly never met
        if rel.get("familiarity", 0) < 1 and rel.get("interaction_count", 0) == 0:
            continue

        other = chars.get(other_id)
        name = other["name"] if other else other_id

        state      = rel.get("state", "stranger")
        trust      = rel.get("trust", 0)
        friendship = rel.get("friendship", 0)
        hostility  = rel.get("hostility", 0)
        attraction = rel.get("attraction", 0)
        resentment = rel.get("resentment", 0)
        comfort    = rel.get("comfort", 0)
        familiarity= rel.get("familiarity", 0)

        # Core summary sentence
        if state == "close_friend":
            summary = f"{name} is one of your closest friends — you trust them deeply."
        elif state == "friend":
            summary = f"You consider {name} a friend."
        elif state == "romantic_interest":
            summary = f"You have romantic feelings toward {name}."
        elif state == "acquaintance":
            summary = f"You know {name} a little — more acquaintance than friend."
        elif state == "enemy":
            summary = f"You and {name} have real hostility between you."
        elif state == "distrusted":
            summary = f"You've met {name} but don't trust them."
        else:
            summary = f"You've met {name} but don't know them well yet."

        # Nuance additions
        extras = []
        if resentment > 40:
            extras.append("There's lingering resentment between you.")
        if attraction > 50 and state != "romantic_interest":
            extras.append(f"You find {name} attractive.")
        if comfort > 60:
            extras.append(f"You feel very comfortable around {name}.")
        if trust < -20:
            extras.append(f"You don't fully trust {name}.")
        if hostility > 30 and state != "enemy":
            extras.append(f"There's tension between you.")
        if extras:
            summary += " " + " ".join(extras)

        # Recency
        last = rel.get("last_interaction", 0)
        if last:
            elapsed = now - last
            if elapsed < 3600:
                recency = "very recently"
            elif elapsed < 86400:
                recency = "today"
            elif elapsed < 604800:
                recency = f"{int(elapsed/86400)}d ago"
            else:
                recency = f"{int(elapsed/604800)}w ago"
        else:
            recency = None

        significance = (
            abs(friendship) + abs(trust) + abs(hostility) +
            abs(attraction) + abs(resentment) + familiarity * 0.3
        )

        results.append({
            "name":             name,
            "id":               other_id,
            "state":            state,
            "summary":          summary,
            "trust":            round(trust),
            "friendship":       round(friendship),
            "hostility":        round(hostility),
            "attraction":       round(attraction),
            "last_interaction": recency,
            "_sig":             significance,
        })

    results.sort(key=lambda x: x.pop("_sig"), reverse=True)
    return results[:limit]


# =========================================================
# SOCIAL CONTEXT
# =========================================================

def build_social_context(

    c,

    world
):

    return {
        "relationships":   build_relationship_context(c, world),
        "recent_messages": build_message_context(c, world),
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
# Enumerates concrete targets from current perception so the
# LLM can reference real prop/character IDs in its action.
# =========================================================

def build_available_actions(c, world):

    perception = c.get("perception", {})

    # -----------------------------------------------
    # INTERACTABLE PROPS  (from visible_props)
    # -----------------------------------------------
    interactable = []

    for prop in perception.get("visible_props", []):
        tags = prop.get("tags", [])
        interactions = prop.get("interactions", [])

        if not tags and not interactions:
            continue

        interactable.append({
            "id":           prop["id"],
            "template":     prop.get("template"),
            "distance":     prop.get("distance"),
            "tags":         tags,
            "interactions": interactions,
        })

    # -----------------------------------------------
    # NEARBY CHARACTERS  (for speak/socialize targets)
    # -----------------------------------------------
    nearby_people = []

    for person in perception.get("visible_people", []):
        nearby_people.append({
            "id":       person["id"],
            "name":     person.get("name"),
            "distance": person.get("distance"),
        })

    # -----------------------------------------------
    # ACTION TYPES available this tick
    # -----------------------------------------------
    action_types = [
        "move",
        "speak",
        "interact",
        "wait",
        "eat",
        "sleep",
        "work",
        "socialize",
        "call",
        "text",
    ]

    return {
        "action_types":       action_types,
        "interactable_props": interactable,
        "nearby_characters":  nearby_people,
    }


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
        # PERCEPTION (SCENE)
        # =====================================
        "perception":
            c.get(
                "perception",
                {}
            ),
        # =====================================
        # ATTENTION
        # =====================================
        "attention_summary":
            build_attention_summary(
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
        "persistent_desires":
        [
            d

            for d in c.get(
                "persistent_desires",
                []
            )

            if not d.get(
                "resolved"
            )
        ][:5],
        "current_turn":
            get_current_turn(
                c,
                world
            ),
        "beliefs": build_belief_context(c),
        "political_alignment": compute_alignment(c),
        "life_narratives": build_narratives(c),
        "self_model": build_self_model(c),
        "schedule": build_schedule_context(c),
        "body_state": build_body_context(c),
        "household_resources":build_household_resource_context( c,world),
        "cognitive_pressure": build_cognitive_pressure(c),
        "social": build_social_context(c,world),
        "memories": build_memory_context(c),
        "active_conversations":build_active_conversations(c, world),
        "social_models":build_social_model_context(c)
    }

    return context


# =========================================================
# SOCIAL MODELS
# =========================================================

def build_social_model_context(

    c,

    limit=8
):

    models = c.get(
        "social_models",
        {}
    )

    results = []

    for target_id, model in models.items():

        results.append({

            "target_id":
                target_id,

            "summary":
                model["summary"],

            "trust":
                model["trust"],

            "respect":
                model["respect"],

            "fear":
                model["fear"],

            "perceived_traits":
                model[
                    "perceived_traits"
                ]
        })

    results.sort(

        key=lambda x: (

            abs(x["trust"])
            +
            abs(x["respect"])
        ),

        reverse=True
    )

    return results[:limit]

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



# =========================================================
# MEMORY CONTEXT
# =========================================================

def build_memory_context(

    c
):

    memories = biased_recall(

        c,

        limit=8
    )

    results = []

    for m in memories:

        results.append({

            "text":
                m["text"],

            "importance":
                m.get(
                    "importance",
                    0
                    ),

            "tags":
                m.get(
                    "tags",
                    []
                ),

            "people":
                m.get(
                    "people",
                    []
                )
        })

    return results
