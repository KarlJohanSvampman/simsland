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

    "socialize",

    # Item stack actions (see systems/item_stack.py)
    "add_to_stack",

    "put_down_stack",

    "search_stack",

    "take_from_stack",

    "pocket_item",

    # Movable prop actions (see systems/prop_movement.py)
    "drag_prop",

    "push_prop",

    "let_go_prop",

    # Chore proposal/negotiation actions (see systems/proposals.py) —
    # registered here deliberately, unlike the pre-existing touch-proposal
    # actions (hug/kiss/respond_touch/...), which were found this session
    # to be missing from VALID_ACTIONS and therefore silently unreachable
    # from the live agent loop despite having correct router code.
    "propose_chore",

    "respond_chore",

    "advance_chore_round",

    "propose_recurring",

    # Individual wait activity (see systems/activities.py,
    # sim_loop.py's character_wait cadence block)
    "start_microwave",

    "take_out_of_microwave",

    # Laundry chore hand-off (see systems/task_process.py) — pre-existed
    # since last round but was unreachable from the live agent loop until
    # now, same class of gap as the touch-proposal system.
    "do_laundry_fill",

    # Lie/excuse engine (see systems/excuses.py) — the decision tree and
    # router code (_route_give_excuse/_route_leave_note in
    # action_router.py) were fully built but these were never registered,
    # same class of gap as the touch-proposal system: silently unreachable
    # from the live agent loop despite correct router code.
    "give_excuse",

    "leave_note",

    # Social negotiation (see systems/proposals.py's "social_ask" kind) —
    # the conversation-level counterpart to propose_chore, no
    # household/building gate.
    "propose_social",

    "respond_social",

    "advance_social_round",

    # Touch proposals (see systems/intimacy.py) — the router code
    # (_route_propose_touch/_route_respond_touch in action_router.py) was
    # fully built but these were never registered, the exact gap
    # systems/proposals.py's docstring was written against.
    "hug",

    "kiss",

    "kiss_peck",

    "kiss_deep",

    "cuddle",

    "hold_hands",

    "handshake",

    "high_five",

    "respond_touch"
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

    action,

    c=None
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

    # =====================================
    # ITEM TARGET (inventory, held stack, placed)
    # =====================================

    if c is not None:

        if any(i.get("id") == target for i in c.get("inventory", [])):
            return True

        if any(i.get("id") == target for i in c.get("held_stack", [])):
            return True

    if target in world.get("placed_items", {}):
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

        action,

        c
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