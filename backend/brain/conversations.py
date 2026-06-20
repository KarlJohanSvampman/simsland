import uuid
import asyncio
import random

from brain.memory import (
    store_memory
)

from systems.social_models import (
    add_social_observation
)

from llm.cognition_jobs import (
    queue_social_reflection
)

from social.relationship_score import (
    relationship_score
)


# =========================================================
# SPEECH ACTS
# =========================================================

SPEECH_ACTS = [

    "question",

    "smalltalk",

    "joke",

    "compliment",

    "flirt",

    "comfort",

    "insult",

    "challenge",

    "defensive",

    "vulnerable",

    "brag",

    "gossip",

    "confession",

    "apology",

    "lie",

    "dismissive",

    "supportive",

    "awkward_silence"
]


# =========================================================
# ENSURE STORAGE
# =========================================================

def ensure_conversations(world):

    world.setdefault(
        "conversations",
        {}
    )


# =========================================================
# CREATE
# =========================================================

def create_conversation(

    world,

    a_id,

    b_id,

    topic="general",

    tone="neutral"
):

    ensure_conversations(world)

    cid = (
        f"conv_{uuid.uuid4().hex[:8]}"
    )

    conv = {

        "id": cid,

        "participants": [

            a_id,

            b_id
        ],

        "topic": topic,

        "tone": tone,

        "history": [],

        "turn_owner": a_id,

        "active": True,

        "started_at":
            world["tick"],

        "last_update":
            world["tick"],

        # =================================================
        # EMOTIONAL CONVERSATION STATE
        # =================================================

        "tension": 0.0,

        "comfort": 0.0,

        "awkwardness": 0.0,

        "emotional_charge": 0.0,

        "dominance_balance": {},

        "attachment_signals": {},

        "unresolved_topics": []
    }

    world[
        "conversations"
    ][cid] = conv

    return conv


# =========================================================
# FIND
# =========================================================

def find_conversation(

    world,

    a_id,

    b_id
):

    ensure_conversations(world)

    for conv in world[
        "conversations"
    ].values():

        if not conv.get("active"):
            continue

        participants = set(
            conv["participants"]
        )

        if participants == {

            a_id,

            b_id
        }:

            return conv

    return None


# =========================================================
# GET OR CREATE
# =========================================================

def get_or_create_conversation(

    world,

    a_id,

    b_id,

    topic="general"
):

    conv = find_conversation(

        world,

        a_id,

        b_id
    )

    if conv:
        return conv

    return create_conversation(

        world,

        a_id,

        b_id,

        topic
    )


# =========================================================
# ADD MESSAGE
# =========================================================

def add_message(

    world,

    conv,

    speaker_id,

    utterance,

    speech_act,

    topic,

    tick
):

    update_conversation_tone(

        conv,

        speech_act
    )

    apply_conversation_dynamics(

        conv,

        speech_act
    )

    entry = {

        "speaker":
            speaker_id,

        "utterance":
            utterance,

        "speech_act":
            speech_act,

        "topic":
            topic,

        "tick":
            tick
    }

    conv["history"].append(
        entry
    )

    conv["history"] = (
        conv["history"][-30:]
    )

    conv["last_update"] = tick

    # =====================================================
    # SWAP TURN
    # =====================================================

    for p in conv["participants"]:

        if p != speaker_id:

            conv["turn_owner"] = p
            break

    # =====================================================
    # MEMORY STORAGE
    # =====================================================

    speaker = world[
        "characters"
    ].get(
        speaker_id
    )

    if speaker:

        emotional_impact = (
            estimate_emotional_impact(
                speech_act
            )
        )

        store_memory(

            speaker,

            compress_conversation_memory(

                speech_act,

                topic,

                utterance
            ),

            tags=[

                "conversation",

                topic,

                speech_act
            ],

            people=[

                p for p in conv[
                    "participants"
                ]

                if p != speaker_id
            ],

            emotional_impact=
                emotional_impact,

            source="conversation",

            tick=tick
        )

    # =====================================================
    # OBSERVATION GENERATION
    # =====================================================

    generate_conversation_observations(

        world,

        conv,

        speaker_id,

        utterance,

        speech_act
    )

    # NOTE: reflection scheduling is handled by conversation_runtime.py
    # after each turn so it is not duplicated here.


# =========================================================
# UPDATE TONE
# =========================================================

def update_conversation_tone(conv, speech_act):
    """Blend tone toward warm/tense/emotional based on recent act.
    Reads the tracked tension/comfort floats so the drift is gradual
    rather than an instant overwrite."""

    positive   = {"comfort", "joke", "flirt", "apology", "supportive", "compliment"}
    negative   = {"accuse", "insult", "threat", "dismissive", "challenge"}
    vulnerable = {"confession", "vulnerable"}

    tension = conv.get("tension", 0)
    comfort = conv.get("comfort", 0)

    if speech_act in positive:
        if comfort > 0.5:
            conv["tone"] = "warm"
        elif tension < 0.3:
            conv["tone"] = "warm"
        # else leave current tone — one kind act doesn't fix a tense room
    elif speech_act in negative:
        if tension > 0.4:
            conv["tone"] = "tense"
        elif conv.get("tone") == "warm":
            conv["tone"] = "neutral"
        else:
            conv["tone"] = "tense"
    elif speech_act in vulnerable:
        conv["tone"] = "emotional"


# =========================================================
# APPLY DYNAMICS
# =========================================================

def apply_conversation_dynamics(

    conv,

    speech_act
):

    if speech_act in [

        "insult",

        "challenge",

        "dismissive"
    ]:

        conv["tension"] += 0.15

        conv["comfort"] -= 0.05

        conv["emotional_charge"] += 0.10

    elif speech_act in [

        "comfort",

        "supportive",

        "apology"
    ]:

        conv["comfort"] += 0.15

        conv["tension"] -= 0.05

    elif speech_act in [

        "flirt",

        "vulnerable",

        "confession"
    ]:

        conv["emotional_charge"] += 0.20

    elif speech_act == "awkward_silence":

        conv["awkwardness"] += 0.20

    # clamp

    conv["tension"] = clamp01(
        conv["tension"]
    )

    conv["comfort"] = clamp01(
        conv["comfort"]
    )

    conv["awkwardness"] = clamp01(
        conv["awkwardness"]
    )

    conv["emotional_charge"] = clamp01(
        conv["emotional_charge"]
    )


# =========================================================
# OBSERVATIONS
# =========================================================

def generate_conversation_observations(

    world,

    conv,

    speaker_id,

    utterance,

    speech_act
):

    speaker = world[
        "characters"
    ].get(
        speaker_id
    )

    if not speaker:
        return

    for pid in conv[
        "participants"
    ]:

        if pid == speaker_id:
            continue

        observer = world[
            "characters"
        ].get(pid)

        if not observer:
            continue

        observation = interpret_message_as_observation(

            speaker,

            utterance,

            speech_act
        )

        if not observation:
            continue

        add_social_observation(

            observer,

            speaker_id,

            observation,

            emotional_weight=
                estimate_emotional_impact(
                    speech_act
                )
        )


# =========================================================
# INTERPRET MESSAGE
# =========================================================

def interpret_message_as_observation(

    speaker,

    utterance,

    speech_act
):

    name = speaker["name"]

    mappings = {

        "compliment":
            f"{name} seemed supportive.",

        "flirt":
            f"{name} seemed flirtatious.",

        "insult":
            f"{name} came across as hostile.",

        "challenge":
            f"{name} seemed confrontational.",

        "vulnerable":
            f"{name} opened up emotionally.",

        "defensive":
            f"{name} seemed insecure.",

        "brag":
            f"{name} was trying to impress people.",

        "dismissive":
            f"{name} seemed dismissive.",

        "joke":
            f"{name} was playful.",

        "awkward_silence":
            f"The interaction became awkward."
    }

    return mappings.get(
        speech_act
    )


# =========================================================
# SHOULD REFLECT
# =========================================================

def should_trigger_reflection(

    speech_act,

    conv
):

    if speech_act in [

        "insult",

        "flirt",

        "confession",

        "vulnerable",

        "dismissive",

        "challenge",

        "supportive",

        "comfort"
    ]:

        return True

    if conv[
        "emotional_charge"
    ] > 0.6:

        return True

    return False


# =========================================================
# SCHEDULE REFLECTION
# =========================================================

def schedule_conversation_reflection(

    world,

    conv,

    speaker_id,

    utterance,

    speech_act,

    tick
):

    speaker = world[
        "characters"
    ].get(
        speaker_id
    )

    if not speaker:
        return

    for pid in conv[
        "participants"
    ]:

        if pid == speaker_id:
            continue

        observer = world[
            "characters"
        ].get(pid)

        if not observer:
            continue

        observer.setdefault(

            "pending_reflections",

            []
        )

        observer[
            "pending_reflections"
        ].append({

            "type":
                "conversation",

            "target_id":
                speaker_id,

            "reason":
                speech_act,

            "scheduled_tick":

                tick

                +

                random.randint(
                    30,
                    300
                ),

            "emotional_weight":
                estimate_emotional_impact(
                    speech_act
                ),

            "times_revisited":
                0,

            "observations": [

                {
                    "text":

                        interpret_message_as_observation(

                            speaker,

                            utterance,

                            speech_act
                        ),

                    "emotional_weight":

                        estimate_emotional_impact(
                            speech_act
                        )
                }
            ]
        })


# =========================================================
# COMPRESS MEMORY
# =========================================================

def compress_conversation_memory(

    speech_act,

    topic,

    utterance
):

    summaries = {

        "insult":
            f"Had a tense conversation about {topic}.",

        "flirt":
            f"Had a flirtatious interaction about {topic}.",

        "comfort":
            f"Had an emotionally supportive conversation.",

        "confession":
            f"Someone opened up emotionally.",

        "dismissive":
            f"Had an awkward dismissive interaction.",

        "supportive":
            f"Felt emotionally supported."
    }

    return summaries.get(

        speech_act,

        f"Talked about {topic}."
    )


# =========================================================
# IMPACT
# =========================================================

def estimate_emotional_impact(

    speech_act
):

    strong = {

        "insult",

        "flirt",

        "confession",

        "threat",

        "comfort"
    }

    medium = {

        "challenge",

        "dismissive",

        "supportive",

        "vulnerable"
    }

    if speech_act in strong:
        return 0.8

    if speech_act in medium:
        return 0.5

    return 0.2


# =========================================================
# CONVERSATION SCORE
# =========================================================

def conversation_score(

    c,

    other
):

    return relationship_score(

        c,

        other["id"]
    )


# =========================================================
# END INACTIVE
# =========================================================

def cleanup_conversations(

    world,

    timeout=600
):

    now = world["tick"]

    for conv in world.get(
        "conversations",
        {}
    ).values():

        if not conv.get("active"):
            continue

        if (

            now

            -

            conv["last_update"]

            >

            timeout
        ):

            conv["active"] = False


# =========================================================
# CLAMP
# ==========================================