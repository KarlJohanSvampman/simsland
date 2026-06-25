from systems.activities import (
    start_activity
)

from brain.conversations import (
    get_or_create_conversation
)


# =========================================================
# EXECUTE SOCIAL INTENTION
# =========================================================

def execute_social_intention(

    c,

    world,

    intention
):

    t = intention.get("type")

    target_id = intention.get(
        "target_id"
    )

    target = world[
        "characters"
    ].get(
        target_id
    )

    if not target:
        return False

    # =====================================================
    # CONTACT
    # =====================================================

    if t == "contact_person":

        return execute_contact(

            c,

            target,

            world
        )

    # =====================================================
    # VISIT
    # =====================================================

    elif t == "visit_person":

        return execute_visit(

            c,

            target,

            world
        )

    # =====================================================
    # FLIRT
    # =====================================================

    elif t == "flirt":

        return execute_flirt(

            c,

            target,

            world
        )

    # =====================================================
    # SEEK COMFORT
    # =====================================================

    elif t == "seek_comfort":

        return execute_seek_comfort(

            c,

            target,

            world
        )

    # =====================================================
    # APOLOGY
    # =====================================================

    elif t == "apologize":

        return execute_apology(

            c,

            target,

            world
        )

    # =====================================================
    # GOSSIP
    # =====================================================

    elif t == "gossip":

        return execute_gossip(

            c,

            target,

            world
        )

    return False


# =========================================================
# CONTACT
# =========================================================

def execute_contact(

    c,

    target,

    world
):

    # simple heuristic:
    # if nearby → conversation
    # else → text/call

    dist = social_distance(
        c,
        target
    )

    if dist <= 6:

        start_social_conversation(

            c,

            target,

            world,

            topic="general"
        )

        return True

    # choose call vs text

    if target.get(
        "is_sleeping"
    ):

        activity = "text_person"

    else:

        activity = "call_person"

    start_activity(

        c,

        world,

        activity
    )

    c["activity"][
        "target_id"
    ] = target["id"]

    return True


# =========================================================
# VISIT
# =========================================================

def execute_visit(

    c,

    target,

    world
):

    start_activity(

        c,

        world,

        "visit_person"
    )

    c["activity"][
        "target_id"
    ] = target["id"]

    c["activity"][
        "destination"
    ] = {

        "building_id":
            target.get(
                "building_id"
            ),

        "x":
            target.get("x"),

        "y":
            target.get("y")
    }

    return True


# =========================================================
# FLIRT
# =========================================================

def execute_flirt(

    c,

    target,

    world
):

    start_social_conversation(

        c,

        target,

        world,

        topic="romance"
    )

    return True


# =========================================================
# SEEK COMFORT
# =========================================================

def execute_seek_comfort(

    c,

    target,

    world
):

    start_social_conversation(

        c,

        target,

        world,

        topic="emotional_support"
    )

    return True


# =========================================================
# APOLOGY
# =========================================================

def execute_apology(

    c,

    target,

    world
):

    start_social_conversation(

        c,

        target,

        world,

        topic="repair"
    )

    return True


# =========================================================
# GOSSIP
# =========================================================

def execute_gossip(

    c,

    target,

    world
):

    start_social_conversation(

        c,

        target,

        world,

        topic="gossip"
    )

    return True


# =========================================================
# START CONVERSATION
# =========================================================

def start_social_conversation(

    a,

    b,

    world,

    topic="general"
):

    conv = get_or_create_conversation(

        world,

        a["id"],

        b["id"],

        topic
    )

    start_activity(

        a,

        world,

        "conversation"
    )

    start_activity(

        b,

        world,

        "conversation"
    )

    a["activity"][
        "conversation_id"
    ] = conv["id"]

    b["activity"][
        "conversation_id"
    ] = conv["id"]

    a["activity"][
        "target_id"
    ] = b["id"]

    b["activity"][
        "target_id"
    ] = a["id"]

    return conv


# =========================================================
# DISTANCE
# =========================================================

def social_distance(

    a,

    b
):

    if (

        a.get("building_id")
        !=
        b.get("building_id")
    ):

        return 999

    dx = a["x"] - b["x"]
    dy = a["y"] - b["y"]

    return (

        dx * dx
        +
        dy * dy
    ) ** 0.5