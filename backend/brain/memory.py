import uuid
import time
from brain.embeddings import add_memory_vector, search

# =========================
# IMPORTANCE SCORING
# =========================
def score_importance(c, text, base):
    score = base

    emotion = c.get("emotion")

    if emotion in ["angry", "happy", "fear"]:
        score += 0.2

    if any(k in text.lower() for k in ["fight", "love", "death", "money"]):
        score += 0.3

    return min(score, 1.0)


# =========================
# STORE MEMORY
# =========================

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

    importance = score_importance(
        c,
        text,
        float(importance)
    )

    mem = {

        "id":
            f"mem_{uuid.uuid4().hex[:8]}",

        "kind":
            kind,

        "text":
            text,

        "importance":
            importance,

        "tags":
            tags or [],

        "tick":
            tick,

        "created_at":
            time.time(),

        # =========================
        # SOCIAL CONTEXT
        # =========================

        "people":
            people or [],
        attention = c.get(
            "attention",
            {}
        )

        focus = attention.get(
            "focus"
        )

        importance = base_importance

        if focus:

            importance += (
                focus.get(
                    "strength",
                    0
                ) * 0.4
            )
        # =========================
        # EMOTIONAL WEIGHT
        # =========================

        "emotional_impact":
            emotional_impact,

        # =========================
        # SOURCE
        # =========================

        "source":
            source,

        **extra
    }

    c.setdefault(
        "memories",
        []
    ).append(mem)

    prune_memories(c)

    add_memory_vector(

        c["id"],

        mem["id"],

        text
    )

    return mem

# =========================
# BASIC RECALL (your original)
# =========================
def recall(c, query_or_tags, limit=6):
    query = " ".join(query_or_tags) if isinstance(query_or_tags, list) else str(query_or_tags)
    tags = set(query.split())

    sem_ids = {r["memory_id"] for r in search(c["id"], query, limit)}

    scored = []
    for m in c.get("memories", []):
        score = (
            m.get("importance", 0.5) * 10
            + len(tags & set(m.get("tags", []))) * 3
            + (6 if m.get("id") in sem_ids else 0)
        )
        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [m for _, m in scored[:limit]]


# =========================
# SMART RECALL (NEW)
# =========================
def recall_relevant(c, query, k=5):
    return recall(c, query, k)


# =========================
# PRUNING
# =========================
def prune_memories(c, max_memories=150):

    memories = c.get("memories", [])

    if len(memories) <= max_memories:
        return

    now = time.time()

    def score(m):
        age = now - m.get("created_at", now)
        return m["importance"] * 2.0 - (age * 0.0001)

    memories.sort(key=score, reverse=True)

    c["memories"] = memories[:max_memories]


# =========================
# DECAY (SINGLE CLEAN VERSION)
# =========================
def decay_memories(c):

    now = time.time()
    kept = []

    for m in c.get("memories", []):
        age = now - m.get("created_at", now)

        m["importance"] *= (0.999 ** age)

        if m["importance"] > 0.05:
            kept.append(m)

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

    intentions = c.get(
        "active_intentions",
        []
    )

    scored = []

    for m in memories:

        score = 0.0

        # =====================================
        # BASE IMPORTANCE
        # =====================================

        score += m.get(
            "importance",
            0
        )

        # =====================================
        # RECENCY
        # =====================================

        score += (
            m.get(
                "recency_score",
                0
            ) * 0.5
        )

        # =====================================
        # EMOTIONAL MATCH
        # =====================================

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

        # =====================================
        # BELIEF MATCH
        # =====================================

        for topic in m.get(
            "tags",
            []
        ):

            belief = beliefs.get(
                topic
            )

            if not belief:
                continue

            certainty = belief.get(
                "certainty",
                0
            )

            score += (
                certainty * 5
            )

        # =====================================
        # INTENTION MATCH
        # =====================================

        for i in intentions:

            itype = i.get("type")

            if not itype:
                continue

            if itype in m.get(
                "tags",
                []
            ):

                score += 8

        scored.append(
            (score, m)
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return [

        m for _, m
        in scored[:limit]
    ]

# =========================================================
# REWRITE MEMORY SALIENCE
# =========================================================

def rewrite_memory_salience(

    c,

    memory,

    emotional_shift
):

    current = memory.get(
        "importance",
        0.5
    )

    memory["importance"] = max(

        0,

        min(
            1.0,

            current
            +
            emotional_shift
        )
    )