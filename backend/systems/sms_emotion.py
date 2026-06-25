from brain.emotion import apply_emotion_inertia

def analyze_sms_tone(text):
    t = text.lower()

    if any(w in t for w in ["hate", "angry", "stupid", "idiot"]):
        return "negative"

    if any(w in t for w in ["love", "thanks", "great", "nice"]):
        return "positive"

    return "neutral"


def apply_sms_emotion(receiver, sender, text):

    tone = analyze_sms_tone(text)

    rel = receiver.get("relationships", {}).get(sender["id"], {})
    chemistry = rel.get("chemistry", 0)

    # -----------------------
    # determine emotional shift
    # -----------------------
    if tone == "positive":
        emotion = "warm" if chemistry > 3 else "curious"

    elif tone == "negative":
        emotion = "annoyed" if chemistry > 3 else "angry"

    else:
        emotion = "curious"

    # -----------------------
    # apply via existing system
    # -----------------------
    apply_emotion_inertia(receiver, emotion)