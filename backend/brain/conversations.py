import uuid


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
            world["tick"]
    }

    world["conversations"][cid] = conv

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
    conv["history"].append({

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
    })

    conv["history"] = (
        conv["history"][-20:]
    )

    conv["last_update"] = tick

    # swap turn
    for p in conv["participants"]:

        if p != speaker_id:

            conv["turn_owner"] = p

            break

# =========================================================
# UPDATE TONE
# =========================================================

def update_conversation_tone(

    conv,

    speech_act
):

    positive = {

        "comfort",

        "joke",

        "flirt",

        "apologize"
    }

    negative = {

        "accuse",

        "insult",

        "threat"
    }

    if speech_act in positive:

        conv["tone"] = "warm"

    elif speech_act in negative:

        conv["tone"] = "tense"