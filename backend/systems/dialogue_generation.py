import random


# =========================================================
# GENERATE DIALOGUE TURN
# =========================================================

def generate_dialogue_turn(

    speaker,

    listener,

    conv,

    world
):

    emotion = speaker.get(
        "emotion",
        "neutral"
    )

    topic = conv.get(
        "topic",
        "general"
    )

    tone = conv.get(
        "tone",
        "neutral"
    )

    speech_act = choose_speech_act(

        speaker,

        listener,

        conv
    )

    utterance = build_utterance(

        speaker,

        listener,

        speech_act,

        topic,

        emotion,

        tone
    )

    return {

        "speech_act":
            speech_act,

        "utterance":
            utterance,

        "topic":
            topic
    }


# =========================================================
# CHOOSE SPEECH ACT
# =========================================================

def choose_speech_act(

    speaker,

    listener,

    conv
):

    emotion = speaker.get(
        "emotion",
        "neutral"
    )

    topic = conv.get(
        "topic",
        "general"
    )

    tension = conv.get(
        "tension",
        0
    )

    if tension > 0.7:

        return random.choice([

            "challenge",

            "dismissive",

            "defensive"
        ])

    if topic == "romance":

        return random.choice([

            "flirt",

            "vulnerable",

            "compliment"
        ])

    if topic == "repair":

        return random.choice([

            "apology",

            "vulnerable",

            "supportive"
        ])

    if emotion in [

        "sad",

        "depressed"
    ]:

        return random.choice([

            "vulnerable",

            "confession",

            "smalltalk"
        ])

    return random.choice([

        "smalltalk",

        "question",

        "joke",

        "supportive",

        "compliment"
    ])


# =========================================================
# BUILD UTTERANCE
# =========================================================

def build_utterance(

    speaker,

    listener,

    speech_act,

    topic,

    emotion,

    tone
):

    name = listener["name"]

    templates = {

        "smalltalk": [

            f"So... how's your day going?",

            f"Been doing anything interesting lately?",

            f"It's been kind of a weird day."
        ],

        "question": [

            f"What do you think about all this?",

            f"How have you been feeling lately?",

            f"Do you ever think about changing things?"
        ],

        "joke": [

            f"At least things aren't completely falling apart yet.",

            f"Honestly this neighborhood feels like a reality show sometimes."
        ],

        "compliment": [

            f"You actually seem really thoughtful.",

            f"I like talking to you.",

            f"You handle things better than most people."
        ],

        "flirt": [

            f"You look good today.",

            f"I kind of missed talking to you.",

            f"You have a really nice smile."
        ],

        "supportive": [

            f"I'm here if you need anything.",

            f"You don't have to deal with everything alone."
        ],

        "vulnerable": [

            f"I don't really know what I'm doing sometimes.",

            f"I've been feeling kind of overwhelmed lately."
        ],

        "dismissive": [

            f"Whatever.",

            f"It's not really a big deal.",

            f"You always overthink things."
        ],

        "challenge": [

            f"I don't think you're being honest.",

            f"That doesn't really make sense."
        ],

        "confession": [

            f"I think I've been avoiding how I really feel.",

            f"I haven't told anyone this before."
        ],

        "apology": [

            f"I'm sorry about earlier.",

            f"I didn't mean to make things worse."
        ]
    }

    choices = templates.get(

        speech_act,

        ["..."]
    )

    return random.choice(
        choices
    )