import random

from social.relationship_score import relationship_score


# =========================================================
# CONVERSATION MAX DURATION (ticks)
# =========================================================

CONV_MAX_TICKS      = 1200   # end naturally after this
CONV_SILENCE_TICKS  = 300    # end if neither party speaks for this long


# =========================================================
# GENERATE DIALOGUE TURN
# Returns None if the conversation should end this turn.
# =========================================================

def generate_dialogue_turn(speaker, listener, conv, world):

    # ---- Check if conversation should end ---------------
    tick = world.get("tick", 0)
    started = conv.get("started_at", tick)
    last    = conv.get("last_update", tick)

    if (tick - started) > CONV_MAX_TICKS:
        end_conversation(conv, "natural end")
        return None

    if (tick - last) > CONV_SILENCE_TICKS:
        end_conversation(conv, "silence")
        return None

    emotion = speaker.get("emotion", "neutral")
    topic   = conv.get("topic", "general")
    tone    = conv.get("tone", "neutral")

    rel_score = _get_rel_score(speaker, listener)

    speech_act = choose_speech_act(speaker, listener, conv, rel_score)

    # Build history summary for context
    recent_history = _summarise_history(conv, speaker["id"])

    utterance = build_utterance(
        speaker, listener, speech_act,
        topic, emotion, tone, recent_history
    )

    return {
        "speech_act": speech_act,
        "utterance":  utterance,
        "topic":      topic,
    }


# =========================================================
# END CONVERSATION
# =========================================================

def end_conversation(conv, reason="natural end"):
    conv["active"]   = False
    conv["end_reason"] = reason


# =========================================================
# RELATIONSHIP SCORE HELPER
# =========================================================

def _get_rel_score(speaker, listener):
    try:
        return relationship_score(speaker, listener)
    except Exception:
        return 0


# =========================================================
# HISTORY SUMMARISER
# Returns last 3 utterances NOT by this speaker, for context.
# =========================================================

def _summarise_history(conv, speaker_id):
    history = conv.get("history", [])
    recent  = [
        e for e in history[-10:]
        if e.get("speaker") != speaker_id
    ][-3:]
    return [e.get("utterance", "") for e in recent]


# =========================================================
# CHOOSE SPEECH ACT
# Now relationship-aware: positive rel → warmer acts,
# negative rel → cooler/hostile acts.
# =========================================================

def choose_speech_act(speaker, listener, conv, rel_score=0):

    emotion = speaker.get("emotion", "neutral")
    topic   = conv.get("topic", "general")
    tension = conv.get("tension", 0)
    comfort = conv.get("comfort", 0)

    # High tension overrides everything
    if tension > 0.7:
        if rel_score < -20:
            return random.choice(["insult", "challenge", "dismissive"])
        return random.choice(["challenge", "dismissive", "defensive"])

    # Topic-driven
    if topic == "romance":
        if rel_score > 30:
            return random.choice(["flirt", "vulnerable", "compliment"])
        return random.choice(["compliment", "question", "smalltalk"])

    if topic == "repair":
        return random.choice(["apology", "vulnerable", "supportive"])

    if topic == "conflict":
        if rel_score < -10:
            return random.choice(["challenge", "dismissive", "defensive"])
        return random.choice(["apology", "defensive", "question"])

    # Emotion-driven
    if emotion in ("sad", "depressed"):
        return random.choice(["vulnerable", "confession", "smalltalk"])

    if emotion in ("angry", "frustrated"):
        if rel_score < 0:
            return random.choice(["challenge", "dismissive", "insult"])
        return random.choice(["challenge", "defensive", "question"])

    if emotion in ("happy", "excited"):
        return random.choice(["joke", "compliment", "smalltalk"])

    # Relationship-driven defaults
    if rel_score > 60:
        # Close friends / high attraction
        return random.choice(["joke", "supportive", "compliment",
                               "vulnerable", "question"])

    if rel_score > 20:
        # Friendly acquaintances
        return random.choice(["smalltalk", "question", "joke",
                               "supportive", "compliment"])

    if rel_score < -30:
        # Dislike
        return random.choice(["dismissive", "defensive", "challenge"])

    if rel_score < 0:
        # Mild unease
        return random.choice(["smalltalk", "defensive", "question"])

    # Neutral strangers
    return random.choice(["smalltalk", "question", "joke",
                           "supportive", "compliment"])


# =========================================================
# BUILD UTTERANCE
# Uses listener name, topic, and recent history for context.
# =========================================================

def build_utterance(speaker, listener, speech_act,
                    topic, emotion, tone, recent_history=None):

    sname = speaker.get("name", "I")
    lname = listener.get("name", "you")
    recent_history = recent_history or []

    # If the listener said something recently, optionally react to it.
    last_heard = recent_history[-1] if recent_history else None

    templates = {

        "smalltalk": [
            f"So, {lname}... how's everything going?",
            f"Been up to anything interesting lately?",
            f"It's been kind of a strange day.",
            f"What's been on your mind?",
        ],

        "question": [
            f"What do you think about all this, {lname}?",
            f"How have you been feeling lately?",
            f"Do you ever think about changing things up?",
            f"What would you do differently if you could?",
        ],

        "joke": [
            f"At least things aren't completely falling apart yet, right?",
            f"Honestly, {lname}, this place feels like a reality show sometimes.",
            f"If things get any stranger I'm going to need a manual.",
        ],

        "compliment": [
            f"You actually seem really thoughtful, {lname}.",
            f"I genuinely enjoy talking to you.",
            f"You handle things better than most people I know.",
            f"There's something I really like about how you see things.",
        ],

        "flirt": [
            f"You look really good today, {lname}.",
            f"I kind of missed talking to you.",
            f"You have a really nice smile, you know that?",
            f"I always look forward to seeing you.",
        ],

        "supportive": [
            f"Hey, I'm here if you need anything, {lname}.",
            f"You don't have to deal with everything alone.",
            f"Whatever you're going through — I've got you.",
        ],

        "vulnerable": [
            f"Honestly, {lname}, I don't really know what I'm doing sometimes.",
            f"I've been feeling kind of overwhelmed lately.",
            f"Can I be honest? Things have been harder than I let on.",
        ],

        "dismissive": [
            f"Whatever.",
            f"It's not really a big deal, {lname}.",
            f"You always overthink things.",
            f"I'd rather not get into it.",
        ],

        "challenge": [
            f"I don't think you're being completely honest, {lname}.",
            f"That doesn't really add up.",
            f"I'm not sure I buy that.",
        ],

        "defensive": [
            f"That's not what I meant at all.",
            f"You're reading into it too much.",
            f"I didn't say anything wrong.",
        ],

        "confession": [
            f"I think I've been avoiding how I really feel, {lname}.",
            f"I haven't told anyone this before, but...",
            f"There's something I've been meaning to say.",
        ],

        "apology": [
            f"I'm sorry about earlier, {lname}.",
            f"I didn't mean to make things worse.",
            f"That wasn't fair of me.",
        ],

        "insult": [
            f"Honestly, {lname}, you can be really frustrating.",
            f"I don't know why I bother sometimes.",
            f"You never think about anyone but yourself.",
        ],

        "gossip": [
            f"Did you hear what happened the other day?",
            f"I probably shouldn't say this, but...",
            f"Something's been going on that I think you should know.",
        ],

        "brag": [
            f"Not to get into it, but things have actually been going really well for me.",
            f"I've been doing pretty well lately, honestly.",
        ],

        "comfort": [
            f"Hey, it's going to be okay, {lname}.",
            f"You're stronger than you think.",
            f"Take it one step at a time.",
        ],

        "awkward_silence": [
            f"...",
            f"So, uh...",
            f"I was just thinking about...",
        ],
    }

    choices = templates.get(speech_act, ["..."])

    # If there's recent history, occasionally echo/acknowledge it
    if last_heard and speech_act in ("supportive", "question", "smalltalk") \
            and random.random() < 0.35:
        echo = last_heard.rstrip(".!?")
        prefixes = [
            f"When you said \"{echo[:40]}{'...' if len(echo)>40 else ''}\" — I get that.",
            f"I heard what you said. I feel the same way.",
            f"Yeah, I was thinking about that too.",
        ]
        return random.choice(prefixes)

    return random.choice(choices)
