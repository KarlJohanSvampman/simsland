from systems.scheduling import get_current_activity
from systems.commitment import is_committed
from brain.intentions import (
    select_primary_intention
)
import random

# =========================
# CONFIG
# =========================
NEED_THRESHOLDS = {
    "eat": 0.6,
    "sleep": 0.7,
    "toilet": 0.8,
    "drink": 0.6,
    "hygiene": 0.6
}

ACTIVITY_PRIORITY = {
    "work": 3,
    "appointment": 3,
    "sleep": 2,
    "eat": 2,
    "toilet": 2,
    "drink": 2,
    "hygiene": 2,
    "pickup_food": 2,
    "phone": 1,
    "relax": 1,
    "socialize": 1,
    "idle": 0
}


# =========================
# MAIN
# =========================
def select_goal(c, world):

    # =========================
    # 🗓️ SCHEDULE (HARD OVERRIDES)
    # =========================
    scheduled = get_current_activity(c, world)

    if scheduled == "work" and c.get("employed"):
        return "work"

    if scheduled in ["sleep", "eat", "relax"]:
        return scheduled


    if is_committed(c):
        return c["commitment"]["goal"]
    # =========================
    # 🚨 DELIVERY / DOORBELL
    # =========================
    if any(n.get("type") == "doorbell" for n in c.get("phone", {}).get("notifications", [])):
        return "pickup_food"

    # =========================
    # 📱 PHONE REACTION
    # =========================
    if c.get("phone", {}).get("inbox"):
        return "phone"

    primary = select_primary_intention(c)

    if primary:

        typ = primary["type"]

        if typ == "career":
            return "work"

        if typ == "romance":
            return "socialize"

        if typ == "friendship":
            return "socialize"

        if typ == "wealth":
            return "earn_money"
    # =========================
    # 🚨 EXTREME NEED OVERRIDES
    # =========================
    needs = c.get("needs", {})

    if needs.get("hunger", 0) > 0.9:
        return "eat"

    if needs.get("energy", 1) < 0.1:
        return "sleep"

    if needs.get("bladder", 0) > 0.95:
        return "toilet"

    # =========================
    # 🧠 BASE SCORING
    # =========================
    scores = {}

    # hunger
    hunger = needs.get("hunger", 0)
    scores["eat"] = hunger if hunger > NEED_THRESHOLDS["eat"] else 0.05

    # sleep
    energy = needs.get("energy", 1)
    scores["sleep"] = (1 - energy) if (1 - energy) > NEED_THRESHOLDS["sleep"] else 0.05

    # toilet
    bladder = needs.get("bladder", 0)
    scores["toilet"] = bladder if bladder > NEED_THRESHOLDS["toilet"] else 0.05

    # thirst
    thirst = needs.get("thirst", 0)
    scores["drink"] = thirst if thirst > NEED_THRESHOLDS["drink"] else 0.05

    # hygiene
    hygiene = needs.get("hygiene", 0)
    scores["hygiene"] = hygiene if hygiene > NEED_THRESHOLDS["hygiene"] else 0.05

    # baseline behaviors
    scores["relax"] = 0.2
    scores["socialize"] = 0.3
    scores["work"] = 0.4 if c.get("employed") else 0.1

    # =========================
    # ❤️ EMOTION BIAS
    # =========================
    scores = apply_emotion_bias(c, scores)

    scores = apply_habit_bias(c, scores, world)
    # =========================
    # 🔥 EMOTIONAL TEMPERATURE EFFECT
    # =========================
    temp = c.get("emotional_temperature", 20)

    if temp > 70:
        scores["relax"] *= 1.4

    # =========================
    # 🎲 RANDOMNESS
    # =========================
    for k in scores:
        scores[k] += random.uniform(0, 0.05)

    # =========================
    # 🎯 SELECT BEST
    # =========================
    new_goal = max(scores.items(), key=lambda x: x[1])[0]

    # =========================
    # 🧱 ACTIVITY PRIORITY (INTERRUPTION CONTROL)
    # =========================
    current = c.get("plan", {}).get("goal")

    if current:
        current_priority = ACTIVITY_PRIORITY.get(current, 0)
        new_priority = ACTIVITY_PRIORITY.get(new_goal, 0)

        # only switch if strictly higher OR urgent need
        if new_priority <= current_priority:
            return current

    return new_goal

def heuristic_plan(goal):
    if not goal: return []
    return {"employment":["review_jobs","apply_job","attend_interview"],"wealth":["work_shift","save_money"],"social":["find_person","start_conversation"],"health":["seek_care","rest"]}.get(goal.get("type"),["wait"])
# =========================
# BASE GOAL SCORING
# =========================
def base_goal_scores(c):

    needs = c.get("needs", {})
    hunger = c.get("needs", {}).get("hunger", 0)

    if hunger > NEED_THRESHOLDS["eat"]:
        eat_score = hunger
    else:
        eat_score = 0.05  # low background desire
    return {
        "sleep": 1 - needs.get("energy", 1),
        "eat": eat_score,
        "toilet": needs.get("bladder", 0),
        "socialize": 0.3,
        "relax": 0.2,
        "work": 0.4
    }

def apply_emotion_bias(c, scores):

    emotion = c.get("emotion", "calm")

    bias = EMOTION_GOAL_BIAS.get(emotion, {})

    for goal, mult in bias.items():
        if goal in scores:
            scores[goal] *= mult
    temp = c.get("emotional_temperature", 20)

    if temp > 70:
        scores["relax"] *= 1.4
    return scores