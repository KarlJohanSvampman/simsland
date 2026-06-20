# =========================================================
# VALID ACTION TYPES
# =========================================================

VALID_ACTIONS = {

    "move",

    "speak",

    "interact",

    "wait",

    "call",

    "text",

    "eat",

    "sleep",

    "work",

    "socialize"
}


# =========================================================
# BASIC STRUCTURE
# =========================================================

def validate_structure(action):

    if not isinstance(
        action,
        dict
    ):

        return False

    if "type" not in action:

        return False

    return True


# =========================================================
# VALID ACTION TYPE
# =========================================================

def validate_type(action):

    return (

        action["type"]
        in VALID_ACTIONS
    )


# =========================================================
# VALID TARGET
# =========================================================

def validate_target(

    world,

    action
):

    target = action.get(
        "target"
    )

    if not target:
        return True

    # =====================================
    # CHARACTER TARGET
    # =====================================

    if target in world.get(
        "characters",
        {}
    ):

        return True

    # =====================================
    # PROP TARGET
    # =====================================

    for p in world.get(
        "props",
        []
    ):

        if p["id"] == target:
            return True

    # =====================================
    # BUILDING TARGET
    # =====================================

    for b in world.get(
        "buildings",
        []
    ):

        if b["id"] == target:
            return True

    return False


# =========================================================
# VALID SPEECH
# =========================================================

def validate_speech(

    action
):

    if action["type"] != "speak":

        return True

    utterance = action.get(
        "utterance"
    )

    if not utterance:

        return False

    if len(utterance) > 300:

        return False

    return True


# =========================================================
# MAIN VALIDATION
# =========================================================

def validate_action(

    c,

    world,

    action
):

    # =====================================
    # STRUCTURE
    # =====================================

    if not validate_structure(
        action
    ):

        return False

    # =====================================
    # TYPE
    # =====================================

    if not validate_type(
        action
    ):

        return False

    # =====================================
    # TARGET
    # =====================================

    if not validate_target(

        world,

        action
    ):

        return False

    # =====================================
    # SPEECH
    # =====================================

    if not validate_speech(
        action
    ):

        return False

    return True