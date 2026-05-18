from systems.decision import (

    choose_activity
)

from systems.activity_runtime import (

    start_activity,

    update_character_walking,

    update_character_using
)


# =========================================================
# UPDATE CHARACTER AI
# =========================================================

def update_character_ai(

    world,

    character
):

    state = character.get(
        "activity_state",
        "idle"
    )

    # =====================================
    # IDLE
    # =====================================

    if state == "idle":

        activity = choose_activity(
            character
        )

        if not activity:
            return

        template = (

            world["definitions"]
            ["activity_templates"]
            .get(activity)
        )

        if not template:
            return

        start_activity(

            world,

            character,

            activity,

            template
        )

        return

    # =====================================
    # WALKING
    # =====================================

    if state == "walking":

        update_character_walking(

            world,

            character
        )

        return

    # =====================================
    # USING
    # =====================================

    if state == "using":

        activity = character.get(
            "activity"
        )

        if not activity:
            return

        template = (

            world["definitions"]
            ["activity_templates"]
            .get(activity)
        )

        if not template:
            return

        update_character_using(

            world,

            character,

            template
        )