import uuid
import time

from brain.embeddings import (
    add_memory_vector,
    search
)


# =========================================================
# IMPORTANCE SCORING
# =========================================================

def score_importance(

    c,

    text,

    base
):

    score = float(base)

    emotion = c.get(
        "emotion"
    )

    if emotion in [

        "angry",

        "happy",

        "fear",

        "sad"
    ]:

        score += 0.15

    lowered = text.lower()

    if any(

        k in lowered

        for k in [

            "fight",

            "love",

            "death",

            "money",

            "kiss",

            "argument",

            "threat",

            "cry"
        ]
    ):

        score += 0.25

    # =====================================
    # ATTENTION BOOST
    # =====================================

    attention = c.get(
        "attention",
        {}
    )

    focus = attention.get(
        "focus"
    )

    if focus:

        score += (
            focus.get(
                "strength",
                0
            ) * 0.35
        )

    return min(
        1.0,
        score
    )


# =========================================================
# STORE MEMORY
# =========================================================

def store_memory(

    c,

    text,

    importance=0.5,

    tags=None,

    kind="memory",

    tick=0,

    people=None,

    emotional_impact=0,

    source=None,

    **extra
):

    if not text:
        return None

    tags = tags or []

    people = people or []

    # =====================================
    # ATTENTION
    # =====================================

    attention = c.get(
        "attention",
        {}
    )

    focus = attention.get(
        "focus"
    )

    # =====================================
    # FINAL IMPORTANCE
    # =====================================

    final_importance = score_importance(

        c,

        text,

        importance
    )

    # =====================================
    # MEMORY OBJECT
    # =====================================

    mem = {

        "id":
            f"mem_{uuid.uuid4().hex[:8]}",

        "kind":
            kind,

        "text":
            text,

        "importance":
            final_importance,

        "tags":
            tags,

        "tick":
            tick,

        "created_at":
            time.time(),

        # =================================
        # SOCIAL
        # =================================

        "people":
            people,

        # =================================
        # ATTENTION
        # =================================

        "attentional_focus":

            focus.get(
                "key"
            )

            if focus else None,

        # =================================
        # EMOTION
        # =================================

        "emotional_impact":
            emotional_impact,

        # =================================
        # SOURCE
        # =================================

        "source":
            source,

        # =================================
        # EXTRA
        # =================================

        **extra
    }

    # =====================================
    # STORE
    # =====================================

    c.setdefault(
        "memories",
        []
    ).append(mem)

    prune_memories(c)

    # =====================================
    # VECTOR INDEX
    # =====================================

    try:

        add_memory_vector(

            c["id"],

            mem["id"],

            text
        )

    except Exception:

        pass

    return mem


# =========================================================
# BASIC RECALL
# =========================================================

def recall(

    c,

    query_or_tags,

    limit=6
):

    query = (

        " ".join(query_or_tags)

        if isinstance(
            query_or_tags,
            list
        )

        else str(query_or_tags)
    )

    tags = set(
        query.split()
    )

    # =====================================
    # SEMANTIC SEARCH
    # =====================================

    try:

        sem_ids = {

            r["memory_id"]

            for r in search(
                c["id"],
                query,
                limit
            )
        }

    except Exception:

        sem_ids = set()

    scored = []

    now = time.time()

    for m in c.get(
        "memories",
        []
    ):

        age = now - m.get(
            "created_at",
            now
        )

        recency = max(
            0,
            1 - (age / 86400)
        )

        score = (

            m.get(
                "importance",
                0.5
            ) * 10

            +

            len(
                tags & set(
                    m.get(
                        "tags",
                        []
                    )
                )
            ) * 3

            +

            recency * 2

            +

            (
                6

                if m.get("id")
                in sem_ids

                else 0
            )
        )

        scored.append(
            (
                score,
                m
            )
        )

    scored.sort(

        key=lambda x: x[0],

        reverse=True
    )

    return [

        m

        for _, m in scored[:limit]
    ]


# =========================================================
# SMART RECALL
# =========================================================

def recall_relevant(

    c,

    query,

    k=5
):

    return recall(
        c,
        query,
        k
    )


# =========================================================
# PRUNE MEMORIES
# =========================================================

def prune_memories(

    c,

    max_memories=150
):

    memories = c.get(
        "memories",
        []
    )

    if len(memories) <= max_memories:
        return

    now = time.time()

    def score(m):

        age = now - m.get(
            "created_at",
            now
        )

        recency = max(
            0,
            1 - (age / 86400)
        )

        return (

            m.get(
                "importance",
                0
            ) * 2

            +

            recency
        )

    memories.sort(

        key=score,

        reverse=True
    )

    c["memories"] = memories[
        :max_memories
    ]


# =========================================================
# DECAY
# =========================================================

def decay_memories(c):

    now = time.time()

    kept = []

    for m in c.get(
        "memories",
        []
    ):

        age = now - m.get(
            "created_at",
            now
        )

        decay_factor = (
            0.999995 ** age
        )

        m["importance"] *= (
            decay_factor
        )

        if m["importance"] > 0.03:

            kept.append(m)

    kept.sort(

        key=lambda m: m.get(
            "importance",
            0
        ),

        reverse=True
    )

    c["memories"] = kept[-150:]


# =========================================================
# BIASED RECALL
# =========================================================

def biased_recall(

    c,

    query="",

    limit=10
):

    memories = c.get(
        "memories",
        []
    )

    emotion = c.get(
        "emotion",
        "neutral"
    )

    beliefs = c.get(
        "beliefs",
        {}
    )

    scored = []

    now = time.time()

    for m in memories:

        score = 0.0

        # =================================
        # BASE IMPORTANCE
        # =================================

        score += m.get(
            "importance",
            0
        ) * 8

        # =================================
        # RECENCY
        # =================================

        age = now - m.get(
            "created_at",
            now
        )

        recency = max(
            0,
            1 - (age / 86400)
        )

        score += recency * 3

        # =================================
        # QUERY MATCH
        # =================================

        if query:

            lowered = query.lower()

            if lowered in m.get(
                "text",
                ""
            ).lower():

                score += 5

        # =================================
        # EMOTIONAL BIAS
        # =================================

        emotional_impact = abs(

            m.get(
                "emotional_impact",
                0
            )
        )

        if emotion in [

            "angry",

            "afraid",

            "sad"
        ]:

            score += (
                emotional_impact * 2
            )

        # =================================
        # BELIEF REINFORCEMENT
        # =================================

        for topic in m.get(
            "tags",
            []
        ):

            belief = beliefs.get(
                topic
            )

            if not belief:
                continue

            score += (

                belief.get(
                    "certainty",
                    0
                ) * 2
            )

        scored.append(
            (
                score,
                m
            )
        )

    scored.sort(

        key=lambda x: x[0],

        reverse=True
    )

    return [

        m

        for _, m in scored[:limit]
    ]

# =========================================================
# REWRITE MEMORY SALIENCE
# Nudge an existing memory's importance up or down.
# Used by reflection.py when emotion reappraisal makes a
# memory feel more or less significant in hindsight.
# =========================================================

def rewrite_memory_salience(c, memory, delta):
    """
    Adjust `memory["importance"]` by `delta` (positive or negative),
    clamped to [0.0, 1.0].  `memory` must be a dict already in
    c["memories"] — we update it in place.
    """
    if not isinstance(memory, dict):
        return
    current = memory.get("importance", 0.5)
    memory["importance"] = max(0.0, min(1.0, current + delta))
