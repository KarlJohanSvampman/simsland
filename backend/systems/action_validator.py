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

    "respond_touch",

    # Hostile intentions / emergency pipeline (see systems/conflict_pipeline.py
    # and systems/emergency.py) — confront wires directly into the existing
    # trait/dice-driven conflict state machine, previously only reachable via
    # the automatic confrontation_desired event; call_911 wires into the
    # existing (already event-wired) 911/dispatch/resolve chain, previously
    # only reachable via rare automatic dice rolls.
    "confront",

    "call_911",

    # Hostile actions (see systems/hostile_actions.py) — reads the
    # already-authored (previously never-consumed) interaction_templates
    # entries: punch/kick/shove resolve directly, grab_offensive/hold map
    # onto catch_and_hold/hold_down. dodge/block/turn_and_run are the
    # target's own defensive/flight response actions.
    "grab_offensive",

    "hold",

    "punch",

    "kick",

    "shove",

    "threaten",

    "dodge",

    "block",

    "turn_and_run",

    # Multi-round grapple (see systems/grapple.py) — wrestle attempts the
    # initial grab (via hostile_actions.resolve_hostile_action against
    # catch_and_hold) then, on success, starts a repeatable hold;
    # release_hold is the holder's own free exit at any point.
    "wrestle",

    "release_hold",

    # Weapon-gated strikes (see systems/hostile_actions.py's stab/knock
    # branch + systems/health.py's apply_blade_injury/apply_blunt_trauma,
    # both fully built but previously never called) — wield_item is the
    # new generic equip action neither of these had a path to before.
    "stab",

    "knock",

    "wield_item",

    # Recovery from a hostile-action knockdown (see systems/posture.py) —
    # _route_stand_up already existed and was fully wired but, like the
    # rest of the posture-action family, was never in VALID_ACTIONS —
    # unreachable until now, same class of gap found repeatedly this
    # session. Only registering the one needed for knockdown recovery;
    # sit_down/lie_down/lean_against_wall have the identical gap but are
    # out of scope here.
    "stand_up",

    # Child care (see systems/child_care.py's tick_child_needs) — parent-
    # initiated response to a child's hunger (can't cook for themselves) or
    # a reminder nudge for a need the child can handle once prompted
    # (toilet/sleep).
    "feed_child",

    "remind_child",

    # Discipline system (see systems/conditioning.py) — apply_discipline/
    # apply_reward/negotiate_contract are fully built and already dispatched
    # in action_router.py's elif chain, but were never registered here —
    # same class of gap as stand_up above. Also blocked until now by
    # conditioning.py reading world["defs"] (always empty; the live world
    # only ever populates world["definitions"]).
    "apply_discipline",

    "apply_reward",

    "negotiate_contract",

    # Adult witness to a child's hostile act calling the child's parent(s)
    # instead of 911 (see systems/hostile_actions.py's offender_is_minor/
    # victim_injured incident tagging, action_router.py's _route_call_parent).
    "call_parent",

    # Prop destruction/disposal (see activities.py's trash/destroy
    # completion handler, which already genuinely removes the prop --
    # fully built but, like everything else in this class of gap, never
    # registered here. "destroy" additionally reports a real
    # property_damage incident (systems/emergency.py); "trash" is
    # legitimate garbage disposal and reports nothing.
    "trash",

    "destroy",
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

    # =====================================
    # INCIDENT TARGET (call_911)
    # =====================================

    for inc in world.get("incidents", []):
        if inc["id"] == target:
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