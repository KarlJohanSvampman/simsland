import random

from brain.memory import (
    recall_relevant
)

from social.relationship_score import (
    relationship_score
)

DIALOGUE_ACTS = {

    "smalltalk": [

        "How's your day going?",

        "Been busy lately?",

        "What's new?"
    ],

    "joke": [

        "You always make things less boring.",

        "That reminds me of something ridiculous.",

        "You look like you need coffee."
    ],

    "flirt": [

        "You look really good today.",

        "I always enjoy talking with you.",

        "I've been thinking about you."
    ],

    "insult": [

        "You're unbelievable sometimes.",

        "I still haven't forgotten what happened.",

        "You really annoy me."
    ],

    "vent": [

        "Everything feels exhausting lately.",

        "I don't know what I'm doing anymore.",

        "Things have been rough."
    ],

    "share": [

        "Something good happened today.",

        "I've actually been feeling pretty great.",

        "Things are finally improving."
    ]
}

# =========================================================
# CONVERSATION TONE
# =========================================================

def conversation_tone(

    c,

    other
):

    score = relationship_score(

        c,

        other["id"]
    )

    if score > 70:
        return "warm"

    if score < -30:
        return "hostile"

    if score < 10:
        return "awkward"

    return "neutral"


# =========================================================
# CONVERSATION MEMORIES
# =========================================================

def conversation_memories(

    c,

    other
):

    return recall_relevant(

        c,

        other["name"],

        5
    )


# =========================================================
# CHOOSE TOPIC
# =========================================================

def choose_topic(

    memories
):

    tags = []

    for m in memories:

        tags.extend(
            m.get("tags", [])
        )

    if not tags:
        return "smalltalk"

    counts = {}

    for t in tags:

        counts[t] = (
            counts.get(t, 0)
            + 1
        )

    return max(
        counts,
        key=counts.get
    )


# =========================================================
# GENERATE LINE
# =========================================================

def generate_dialogue(

    c,

    other
):

    memories = conversation_memories(

        c,

        other
    )

    tone = conversation_tone(

        c,

        other
    )

    topic = choose_topic(
        memories
    )

    pools = {

        "warm": [

            "It's always nice talking to you.",

            "I've been thinking about you lately.",

            "Remember last time?"
        ],

        "neutral": [

            "How's your day going?",

            "Been busy lately?",

            "What's new?"
        ],

        "awkward": [

            "Uh... hey.",

            "Things have been strange lately.",

            "How have you been?"
        ],

        "hostile": [

            "What do you want?",

            "I'm still upset about before.",

            "This better be important."
        ]
    }

    act = choose_dialogue_act(

        c,

        other,

        tone
    )

    pool = DIALOGUE_ACTS.get(
        act,
        DIALOGUE_ACTS["smalltalk"]
    )

    line = random.choice(pool)

    return {

        "text": line,

        "tone": tone,

        "topic": topic,

        "memories": memories,

        "act": act
    }


# =========================================================
# DIALOGUE ACT
# =========================================================

def choose_dialogue_act(

    c,

    other,

    tone
):

    emotion = c.get(
        "emotion",
        "neutral"
    )

    attraction = (
        c.get("attraction", {})
        .get(other["id"], 0)
    )

    hostility = (
        c.get("hostility", {})
        .get(other["id"], 0)
    )

    friendship = (
        c.get("friendship", {})
        .get(other["id"], 0)
    )

    # =====================================
    # HOSTILITY
    # =====================================

    if hostility > 70:

        return "insult"

    # =====================================
    # ROMANCE
    # =====================================

    if attraction > 75:

        return "flirt"

    # =====================================
    # FRIENDSHIP
    # =====================================

    if friendship > 60:

        return "joke"

    # =====================================
    # EMOTIONAL
    # =====================================

    if emotion == "sad":

        return "vent"

    if emotion == "happy":

        return "share"

    return "smalltalk"

# =========================================================
# APPLY DIALOGUE EFFECTS
# =========================================================

def apply_dialogue_effects(

    c,

    other,

    act
):

    friendship = c.setdefault(
        "friendship",
        {}
    )

    hostility = c.setdefault(
        "hostility",
        {}
    )

    attraction = c.setdefault(
        "attraction",
        {}
    )

    oid = other["id"]

    # =====================================
    # POSITIVE
    # =====================================

    if act in [

        "joke",

        "share",

        "comfort"
    ]:

        friendship[oid] = (

            friendship.get(oid, 0)
            + 1
        )

    # =====================================
    # FLIRT
    # =====================================

    if act == "flirt":

        attraction[oid] = (

            attraction.get(oid, 0)
            + 1
        )

    # =====================================
    # NEGATIVE
    # =====================================

    if act in [

        "insult",

        "threat"
    ]:

        hostility[oid] = (

            hostility.get(oid, 0)
            + 2
        )