def record_habit(c, goal, world):

    cal = world.get("calendar", {})
    hour = cal.get("hour", 0)

    key = f"{goal}@{hour}"

    c.setdefault("habits", {})
    c["habits"][key] = c["habits"].get(key, 0) + 1


def apply_habit_bias(c, scores, world):

    hour = world.get("calendar", {}).get("hour", 0)

    for goal in scores:

        key = f"{goal}@{hour}"

        strength = c.get("habits", {}).get(key, 0)

        if strength > 0:
            scores[goal] *= (1 + min(0.5, strength * 0.05))

    return scores

def decay_habits(c):
    for k in list(c.get("habits", {})):
        c["habits"][k] *= 0.999