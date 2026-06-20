# =========================================================
# SOCIAL MODELS
# =========================================================

from brain.memory import (
    store_memory
)


# =========================================================
# TRAIT INTERPRETATIONS
# =========================================================

TRAIT_INTERPRETATIONS = {

    # =====================================================
    # SOCIAL
    # =====================================================

    "confident": {

        "perceived": [
            "confident",
            "self-assured"
        ],

        "respect": 10
    },

    "awkward": {

        "perceived": [
            "awkward",
            "socially anxious"
        ],

        "trust": 5
    },

    "funny": {

        "perceived": [
            "funny",
            "easygoing"
        ],

        "attraction": 8
    },

    "charming": {

        "perceived": [
            "charismatic",
            "smooth"
        ],

        "attraction": 15,

        "trust": 5
    },

    "quiet": {

        "perceived": [
            "quiet",
            "hard to read"
        ]
    },

    "talkative": {

        "perceived": [
            "talkative",
            "attention-seeking"
        ]
    },

    "clingy": {

        "perceived": [
            "needy",
            "emotionally dependent"
        ],

        "respect": -5
    },

    "aggressive": {

        "perceived": [
            "intimidating",
            "volatile"
        ],

        "fear": 20
    },

    "passive": {

        "perceived": [
            "submissive",
            "non-confrontational"
        ]
    },

    "flirty": {

        "perceived": [
            "flirtatious",
            "playful"
        ],

        "attraction": 10
    },

    "dominant": {

        "perceived": [
            "dominant",
            "assertive"
        ],

        "respect": 8
    },

    "submissive": {

        "perceived": [
            "submissive",
            "timid"
        ]
    },

    "sarcastic": {

        "perceived": [
            "sarcastic",
            "hard to read"
        ]
    },

    "dramatic": {

        "perceived": [
            "dramatic",
            "emotionally intense"
        ]
    },

    "extroverted": {

        "perceived": [
            "outgoing",
            "social"
        ]
    },

    "introverted": {

        "perceived": [
            "reserved",
            "private"
        ]
    },

    # =====================================================
    # INTELLECTUAL
    # =====================================================

    "intelligent": {

        "perceived": [
            "smart",
            "analytical"
        ],

        "respect": 15
    },

    "creative": {

        "perceived": [
            "creative",
            "interesting"
        ],

        "attraction": 5
    },

    "curious": {

        "perceived": [
            "curious",
            "engaged"
        ]
    },

    "naive": {

        "perceived": [
            "naive",
            "easily manipulated"
        ]
    },

    "logical": {

        "perceived": [
            "logical",
            "emotionally detached"
        ]
    },

    "philosophical": {

        "perceived": [
            "deep thinker",
            "reflective"
        ]
    },

    # =====================================================
    # MORAL
    # =====================================================

    "kind": {

        "perceived": [
            "kind",
            "safe"
        ],

        "trust": 15
    },

    "generous": {

        "perceived": [
            "generous",
            "thoughtful"
        ],

        "trust": 10
    },

    "dishonest": {

        "perceived": [
            "untrustworthy",
            "fake"
        ],

        "trust": -20
    },

    "manipulative": {

        "perceived": [
            "manipulative",
            "calculating"
        ],

        "trust": -15,

        "fear": 10
    },

    "judgmental": {

        "perceived": [
            "critical",
            "condescending"
        ],

        "trust": -5
    },

    "loyal": {

        "perceived": [
            "dependable",
            "loyal"
        ],

        "trust": 20
    },

    "selfish": {

        "perceived": [
            "self-centered",
            "exploitative"
        ],

        "trust": -10
    },

    "empathetic": {

        "perceived": [
            "empathetic",
            "understanding"
        ],

        "trust": 15
    },

    # =====================================================
    # EMOTIONAL
    # =====================================================

    "emotional": {

        "perceived": [
            "emotionally expressive"
        ]
    },

    "cold": {

        "perceived": [
            "cold",
            "distant"
        ],

        "trust": -5
    },

    "sensitive": {

        "perceived": [
            "sensitive",
            "fragile"
        ]
    },

    "moody": {

        "perceived": [
            "unpredictable"
        ],

        "fear": 5
    },

    "anxious": {

        "perceived": [
            "nervous",
            "insecure"
        ]
    },

    "depressed": {

        "perceived": [
            "sad",
            "withdrawn"
        ]
    },

    "optimistic": {

        "perceived": [
            "hopeful",
            "uplifting"
        ]
    },

    "pessimistic": {

        "perceived": [
            "negative",
            "defeatist"
        ]
    },

    # =====================================================
    # STATUS
    # =====================================================

    "ambitious": {

        "perceived": [
            "driven",
            "status-oriented"
        ],

        "respect": 10
    },

    "lazy": {

        "perceived": [
            "lazy",
            "unmotivated"
        ],

        "respect": -10
    },

    "wealthy": {

        "perceived": [
            "successful",
            "high-status"
        ],

        "respect": 10
    },

    "arrogant": {

        "perceived": [
            "arrogant",
            "looks down on people"
        ],

        "respect": -10
    },

    "stylish": {

        "perceived": [
            "stylish",
            "put together"
        ],

        "attraction": 5
    },

    "messy": {

        "perceived": [
            "messy",
            "chaotic"
        ]
    }
}


# =========================================================
# ENSURE STORAGE
# =========================================================

def ensure_social_models(c):

    c.setdefault(
        "social_models",
        {}
    )

    c.setdefault(

        "llm_session",

        {

            "history": [],

            "last_used": 0
        }
    )


# =========================================================
# ENSURE MODEL
# =========================================================

def ensure_social_model(

    c,

    target_id
):

    ensure_social_models(c)

    models = c["social_models"]

    if target_id not in models:

        models[target_id] = {

            "summary":
                "Unknown person.",

            "trust":
                0,

            "respect":
                0,

            "fear":
                0,

            "attraction":
                0,

            "perceived_traits": [],

            "reputation_tags": [],

            "observations": [],

            "last_reflection":
                None,

            "confidence":
                0.1
        }

    return models[target_id]


# =========================================================
# CLAMP
# =========================================================

def clamp_social(v):

    return max(

        -100,

        min(
            100,

            int(v)
        )
    )


# =========================================================
# SUMMARY
# =========================================================

def build_summary(

    perceived_traits
):

    if not perceived_traits:

        return (
            "Hard to read."
        )

    return (

        "Seems "

        +

        ", ".join(
            perceived_traits[:6]
        )
    )


# =========================================================
# FIRST IMPRESSION
# =========================================================

def create_first_impression(

    observer,

    target
):

    model = ensure_social_model(

        observer,

        target["id"]
    )

    if model["confidence"] > 0.1:
        return model

    perceived = []

    trust = 0
    respect = 0
    attraction = 0
    fear = 0

    traits = target.get(
        "traits",
        []
    )

    for t in traits:

        cfg = TRAIT_INTERPRETATIONS.get(t)

        if not cfg:
            continue

        perceived.extend(

            cfg.get(
                "perceived",
                []
            )
        )

        trust += cfg.get(
            "trust",
            0
        )

        respect += cfg.get(
            "respect",
            0
        )

        attraction += cfg.get(
            "attraction",
            0
        )

        fear += cfg.get(
            "fear",
            0
        )

    perceived = list(set(perceived))

    model.update({

        "summary":
            build_summary(
                perceived
            ),

        "trust":
            clamp_social(trust),

        "respect":
            clamp_social(respect),

        "fear":
            clamp_social(fear),

        "attraction":
            clamp_social(attraction),

        "perceived_traits":
            perceived,

        "confidence":
            0.3
    })

    return model


# =========================================================
# OBSERVATIONS
# =========================================================

def add_social_observation(

    observer,

    target_id,

    text,

    emotional_weight=0
):

    model = ensure_social_model(

        observer,

        target_id
    )

    model["observations"].append({

        "text":
            text,

        "emotional_weight":
            emotional_weight
    })

    model["observations"] = (

        model["observations"][-50:]
    )


# =========================================================
# APPLY REFLECTION RESULT
# =========================================================

def apply_reflection_result(

    observer,

    target_id,

    result
):

    if not result:
        return

    model = ensure_social_model(

        observer,

        target_id
    )

    summary = result.get(
        "summary"
    )

    if summary:

        model["summary"] = (
            summary
        )

    model["trust"] = clamp_social(

        model["trust"]

        +

        result.get(
            "trust_shift",
            0
        )
    )

    model["respect"] = clamp_social(

        model["respect"]

        +

        result.get(
            "respect_shift",
            0
        )
    )

    model["fear"] = clamp_social(

        model["fear"]

        +

        result.get(
            "fear_shift",
            0
        )
    )

    model["attraction"] = clamp_social(

        model["attraction"]

        +

        result.get(
            "attraction_shift",
            0
        )
    )

    traits = result.get(
        "perceived_traits",
        []
    )

    if traits:

        model[
            "perceived_traits"
        ] = list(set(

            model[
                "perceived_traits"
            ]

            + traits
        ))

    model["confidence"] = min(

        1.0,

        model.get(
            "confidence",
            0.1
        )

        + 0.05
    )


# =========================================================
# STORE SOCIAL MEMORY
# =========================================================

def store_social_memory(

    observer,

    target,

    text,

    tick
):

    store_memory(

        observer,

        text,

        tags=[
            "social",
            "person_model"
        ],

        people=[
            target["id"]
        ],

        emotional_impact=0.4,

        source="social_model",

        tick=tick
    )