# =========================================================
# GET HOUSEHOLD
# =========================================================

def get_household(

    world,

    household_id
):

    for h in world.get(
        "households",
        []
    ):

        if h["id"] == household_id:
            return h

    return None