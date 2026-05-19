# =========================================================
# CURRENT SCHEDULE BLOCK
# =========================================================

def get_current_schedule_block(

    c,

    world_time
):

    schedule = c.get(
        "schedule",
        {}
    )

    day = world_time.get(
        "weekday",
        "monday"
    )

    current_minute = world_time.get(
        "minute_of_day",
        0
    )

    blocks = schedule.get(
        day,
        []
    )

    for block in blocks:

        if (

            block["start"]
            <= current_minute
            <
            block["end"]

        ):

            return block

    return None

    # =========================================================
# UPDATE ACTIVE SCHEDULE
# =========================================================

def update_schedule_runtime(

    c,

    world
):

    current = get_current_schedule_block(

        c,

        world["time"]
    )

    previous = c.get(
        "active_schedule_block"
    )

    if current == previous:
        return

    c[
        "active_schedule_block"
    ] = current

    if not current:
        return

    c["current_intention"] = {

        "type":
            current["type"],

        "source":
            "schedule"
    }