import random


# =========================================================
# START SHOPPING SESSION
# =========================================================

def start_shopping_session(

    c,

    desire
):

    device = choose_device(c)

    duration = random.randint(

        20,

        120
    )

    session = {

        "target":
            desire.get(
                "target"
            ),

        "desire_type":
            desire["type"],

        "device":
            device,

        "duration_minutes":
            duration,

        "purchase_made":
            False,

        "progress":
            0.0
    }

    c["shopping_session"] = (
        session
    )

    return session


# =========================================================
# DEVICE
# =========================================================

def choose_device(c):

    has_computer = c.get(
        "has_computer",
        True
    )

    if not has_computer:
        return "phone"

    if random.random() < 0.7:
        return "computer"

    return "phone"