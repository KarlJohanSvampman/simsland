# =========================================================
# CONVERSATION ANALYSIS
# =========================================================

import random

from systems.social_models import (
    add_social_observation
)

from systems.social_models import (
    ensure_social_model
)

from systems.social_models import (
    apply_reflection_result
)

from systems.social import (
    modify_relationship
)

from brain.memory import (
    store_memory
)


# =========================================================
# ANALYZE MESSAGE
# =========================================================

def analyze_message(

    world,

    conv,

    speaker,

    listener,

    utterance,

    speech_act
):

    result = {

        "observations": [],

        "emotional_effects": {},

        "relationship_effects": {},

        "self_image_effects": [],

        "conversation_effects": {}
    }

    # =====================================================
    # SPEECH ACT ANALYSIS
    # =====================================================

    apply_speech_act_analysis(

        result,

        speaker,

        listener,

        utterance,

        speech_act,

        world
    )

    # =====================================================
    # TONE ANALYSIS
    # =====================================================

    apply_tone_analysis(

        result,

        conv,

        speech_act
    )

    # =====================================================
    # STORE OBSERVATIONS
    # =====================================================

    for obs in result[
        "observations"
    ]:

        add_social_observation(

            listener,

            speaker["id"],

            obs["text"],

            obs.get(
                "weight",
                0.3
            )
        )

    # =====================================================
    # APPLY RELATIONSHIP EFFECTS
    # =====================================================

    apply_relationship_effects(

        speaker,

        listener,

        result
    )

    # =====================================================
    # APPLY CONVERSATION EFFECTS
    # =====================================================

    apply_conversation_effects(

        conv,

        result
    )

    # =====================================================
    # MEMORY
    # =====================================================

    store_conversation_memory(

        listener,

        speaker,

        result,

        world
    )

    return result


# =========================================================
# SPEECH ACT ANALYSIS
# =========================================================

def apply_speech_act_analysis(

    result,

    speaker,

    listener,

    utterance,

    speech_act,

    world=None
):

    name = speaker["name"]

    # =====================================================
    # COMPLIMENT
    # =====================================================

    if speech_act == "compliment":

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed supportive and validating.",

            "weight":
                0.5
        })

        result[
            "relationship_effects"
        ] = {

            "trust": 5,

            "friendship": 4
        }

        result[
            "emotional_effects"
        ] = {

            "comfort": 0.2
        }

    # =====================================================
    # FLIRT
    # =====================================================

    elif speech_act == "flirt":

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed flirtatious.",

            "weight":
                0.7
        })

        result[
            "relationship_effects"
        ] = {

            "attraction": 8,

            "friendship": 2
        }

        result[
            "conversation_effects"
        ] = {

            "emotional_charge": 0.25
        }

    # =====================================================
    # INSULT
    # =====================================================

    elif speech_act == "insult":

        result[
            "observations"
        ].append({

            "text":
                f"{name} came across as hostile and disrespectful.",

            "weight":
                0.9
        })

        result[
            "relationship_effects"
        ] = {

            "trust": -8,

            "friendship": -10,

            "hostility": 10
        }

        result[
            "conversation_effects"
        ] = {

            "tension": 0.3,

            "awkwardness": 0.2
        }

    # =====================================================
    # VULNERABILITY
    # =====================================================

    elif speech_act in [

        "vulnerable",

        "confession"
    ]:

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed emotionally vulnerable.",

            "weight":
                0.8
        })

        result[
            "relationship_effects"
        ] = {

            "trust": 7,

            "friendship": 5
        }

        result[
            "conversation_effects"
        ] = {

            "emotional_charge": 0.35
        }

    # =====================================================
    # DEFENSIVE
    # =====================================================

    elif speech_act == "defensive":

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed insecure or defensive.",

            "weight":
                0.5
        })

    # =====================================================
    # DISMISSIVE
    # =====================================================

    elif speech_act == "dismissive":

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed dismissive and emotionally distant.",

            "weight":
                0.7
        })

        result[
            "relationship_effects"
        ] = {

            "trust": -5,

            "friendship": -4
        }

        result[
            "conversation_effects"
        ] = {

            "awkwardness": 0.25,

            "tension": 0.15
        }

    # =====================================================
    # COMFORT
    # =====================================================

    elif speech_act in [

        "comfort",

        "supportive"
    ]:

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed emotionally supportive.",

            "weight":
                0.7
        })

        result[
            "relationship_effects"
        ] = {

            "trust": 10,

            "friendship": 6
        }

        result[
            "emotional_effects"
        ] = {

            "comfort": 0.4
        }

    # =====================================================
    # BRAGGING
    # =====================================================

    elif speech_act == "brag":

        result[
            "observations"
        ].append({

            "text":
                f"{name} seemed attention-seeking.",

            "weight":
                0.4
        })

    # =====================================================
    # GOSSIP
    # =====================================================

    elif speech_act == "gossip":

        result[
            "observations"
        ].append({

            "text":
                f"{name} was gossiping about other people.",

            "weight":
                0.6
        })

        # Curiosity-scaled secret transfer (see systems/secrets.py's
        # dormant reveal_secret) -- a curious teller is more willing to
        # share what they've heard, a curious listener is more likely
        # to actually get it out of them. Only ever relays a secret the
        # speaker genuinely already knows; never fabricates one.
        if world is not None:

            speaker_curiosity = speaker.get("curiosity", 50) / 100.0
            listener_curiosity = listener.get("curiosity", 50) / 100.0

            candidates = []
            for keeper in world.get("characters", {}).values():
                for secret in keeper.get("secrets", []):
                    known_by = secret.get("known_by", [])
                    speaker_knows = speaker["id"] == keeper["id"] or speaker["id"] in known_by
                    listener_knows = listener["id"] == keeper["id"] or listener["id"] in known_by
                    if not speaker_knows or listener_knows:
                        continue
                    if listener["id"] in secret.get("subject_ids", []):
                        continue
                    candidates.append(secret)

            if candidates:
                juiciest = max(candidates, key=lambda s: s.get("severity", 0))
                chance = 0.15 + 0.35 * speaker_curiosity + 0.25 * listener_curiosity
                if random.random() < chance:
                    from systems.secrets import reveal_secret
                    reveal_secret(juiciest, listener["id"], world, method="told")

                    result[
                        "observations"
                    ].append({

                        "text":
                            f"{name} let slip something you didn't know before.",

                        "weight":
                            0.5
                    })

    # =====================================================
    # QUESTION -- curious characters lean personal/prying (family,
    # background, "where are you from"); see systems/curiosity.py and
    # the matching narrative nudge in context_builder.py's
    # _build_curiosity_context. Bias via a mild social nuance rather
    # than parsing the literal utterance for topic -- the LLM decides
    # what to actually ask, this just reflects the tone landing.
    # =====================================================

    elif speech_act == "question":

        result[
            "observations"
        ].append({

            "text":
                f"{name} asked you something.",

            "weight":
                0.2
        })

        if speaker.get("curiosity", 50) >= 70:

            result[
                "observations"
            ].append({

                "text":
                    f"{name} seemed genuinely curious about your life -- "
                    "a bit personal, but not unkind.",

                "weight":
                    0.3
            })

            result[
                "relationship_effects"
            ] = {

                "friendship": 1
            }

    # =====================================================
    # AWKWARD
    # =====================================================

    elif speech_act == "awkward_silence":

        result[
            "observations"
        ].append({

            "text":
                "The interaction became awkward.",

            "weight":
                0.4
        })

        result[
            "conversation_effects"
        ] = {

            "awkwardness": 0.3
        }

    # =====================================================
    # URGENT REPORT — secondhand witness alert. Relays the speaker's own
    # witnessed_offenses (systems/excuses.py::
    # check_witnessed_hostility_for_observer, systems/hostile_actions.py's
    # recent_hostile_acts tagging) onto the listener, who was never
    # actually near the scene. Because witnessed_offenses already drives
    # confront/call_911 availability and the narrative witnessed-offense
    # line (context_builder.py), this is the entire secondhand mechanism
    # — no separate belief/pursuit system needed. Only relays a real
    # witnessed tag; there's no fabrication path.
    # =====================================================

    elif speech_act == "urgent_report":

        speaker_witnessed = speaker.get("witnessed_offenses", {})
        if speaker_witnessed and world is not None:
            offender_id, _tick = max(speaker_witnessed.items(), key=lambda kv: kv[1])
            listener.setdefault("witnessed_offenses", {})[offender_id] = world.get("tick", 0)

            result[
                "observations"
            ].append({

                "text":
                    f"{name} warned about something dangerous.",

                "weight":
                    0.7
            })

            result[
                "emotional_effects"
            ] = {

                "fear": 0.2
            }


# =========================================================
# TONE ANALYSIS
# =========================================================

def apply_tone_analysis(

    result,

    conv,

    speech_act
):

    tension = conv.get(
        "tension",
        0
    )

    awkwardness = conv.get(
        "awkwardness",
        0
    )

    emotional_charge = conv.get(
        "emotional_charge",
        0
    )

    if tension > 0.6:

        result[
            "observations"
        ].append({

            "text":
                "The conversation felt tense.",

            "weight":
                0.5
        })

    if awkwardness > 0.5:

        result[
            "observations"
        ].append({

            "text":
                "The interaction felt awkward.",

            "weight":
                0.4
        })

    if emotional_charge > 0.7:

        result[
            "observations"
        ].append({

            "text":
                "The conversation felt emotionally intense.",

            "weight":
                0.6
        })


# =========================================================
# APPLY RELATIONSHIP EFFECTS
# =========================================================

def apply_relationship_effects(

    speaker,

    listener,

    result
):

    effects = result.get(
        "relationship_effects",
        {}
    )

    for stat, amount in effects.items():

        modify_relationship(

            listener,

            speaker["id"],

            stat,

            amount
        )


# =========================================================
# APPLY CONVERSATION EFFECTS
# =========================================================

def apply_conversation_effects(

    conv,

    result
):

    effects = result.get(
        "conversation_effects",
        {}
    )

    for k, v in effects.items():

        conv[k] = max(

            0,

            min(

                1.0,

                conv.get(k, 0)
                + v
            )
        )


# =========================================================
# MEMORY STORAGE
# =========================================================

def store_conversation_memory(

    listener,

    speaker,

    result,

    world
):

    observations = result.get(
        "observations",
        []
    )

    if not observations:
        return

    strongest = max(

        observations,

        key=lambda x: x.get(
            "weight",
            0
        )
    )

    text = strongest["text"]

    store_memory(

        listener,

        text,

        tags=[

            "conversation",

            "social"
        ],

        people=[
            speaker["id"]
        ],

        emotional_impact=
            strongest.get(
                "weight",
                0.4
            ),

        source="conversation_analysis",

        tick=world["tick"]
    )


# =========================================================
# BUILD SOCIAL AFTEREFFECTS
# =========================================================

def build_social_aftereffects(

    result
):

    effects = []

    rel = result.get(
        "relationship_effects",
        {}
    )

    if rel.get(
        "hostility",
        0
    ) > 5:

        effects.append(
            "lingering_tension"
        )

    if rel.get(
        "trust",
        0
    ) > 5:

        effects.append(
            "increased_closeness"
        )

    if rel.get(
        "attraction",
        0
    ) > 5:

        effects.append(
            "romantic_interest"
        )

    return effects


# =========================================================
# SHOULD SCHEDULE REFLECTION
# =========================================================

def should_schedule_reflection(

    result
):

    rel = result.get(
        "relationship_effects",
        {}
    )

    total = sum(

        abs(v)

        for v in rel.values()
    )

    return total >= 8