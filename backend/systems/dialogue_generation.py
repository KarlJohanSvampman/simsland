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
                               "vulnerable", "qu