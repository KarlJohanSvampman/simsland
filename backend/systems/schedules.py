# =========================================================
# SCHEDULE ACTIVITY
# =========================================================

def get_scheduled_activity(

    world,

    character
):

    hour = (

        world["calendar"]
        ["hour"]
    )

    schedule = character.get(
        "schedule",
        {}
    )

    return schedule.get(
        str(hour)
    )