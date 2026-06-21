import random

from brain.conversations import (
    add_message
)

from systems.conversation_analysis import (
    analyze_message,
    should_schedule_reflection
)

from brain.relationships import (
    apply_interaction
)

from systems.dialogue_generation import (
    generate_dialogue_turn
)

from systems.reactions import (
    push_conversation_reaction
)


# =========================================================
# UPDATE CONVERSATION ACTIVITY
# =========================================================

def update_conversation_activity(

    c,

    world,

    activity
):

    conv_id = activity.get(
        "conversation_id"
    )

    if not conv_id:
        return False

    conv = world[
        "conversations"
    ].get(
        conv_id
    )

    if not conv:
        return False

    if not conv.get("active"):
        return False

    # =====================================================
    # TURN TIMER
    # =====================================================

    activity.setdefault(
        "next_turn_tick",
        world["tick"]
    )

    if world["tick"] < activity[
        "next_turn_tick"
    ]:
        return True

    # =====================================================
    # TURN OWNER
    # =====================================================

    if conv.get(
        "turn_owner"
    ) != c["id"]:

        return True

    # =====================================================
    # FIND LISTENER
    # =====================================================

    listener = None

    for pid in conv[
        "participants"
    ]:

        if pid != c["id"]:

            listener = world[
                "characters"
            ].get(pid)

            break

    if not listener:
        return False

    # =====================================================
    # GENERATE TURN
    # Returns None when the conversation should end.
    # =====================================================

    turn = generate_dialogue_turn(c, listener, conv, world)

    if turn is None:
        # Conversation ended (timeout or silence) — clean up activity
        return False

    if not turn:
        return True

    utterance = turn.get(
        "utterance",
        "..."
    )

    speech_act = turn.get(
        "speech_act",
        "smalltalk"
    )

    topic = turn.get(
        "topic",
        conv.get(
            "topic",
            "general"
        )
    )

    # =====================================================
    # STORE MESSAGE
    # =====================================================

    add_message(

        world,

        conv,

        c["id"],

        utterance,

        speech_act,

        topic,

        world["tick"]
    )

    # =====================================================
    # LISTENER REACTION
    # Push a physical reaction animation on the listener
    # based on what speech act they just heard.
    # =====================================================

    push_conversation_reaction(
        listener,
        speech_act,
        world["tick"]
    )

    # =====================================================
    # RELATIONSHIP EFFECTS
    # =====================================================

    apply_interaction(

        c,

        listener,

        speech_act
    )

    # =====================================================
    # ANALYSIS
    # =====================================================

    result = analyze_message(

        world,

        conv,

        c,

        listener,

        utterance,

        speech_act
    )

    # =====================================================
    # REFLECTIONS
    # =====================================================

    if should_schedule_reflection(
        result
    ):

        listener.setdefault(

            "pending_reflections",

            []
        )

        listener[
            "pending_reflections"
        ].append({

            "type":
                "conversation",

            "target_id":
                c["id"],

            "reason":
                speech_act,

            "scheduled_tick":

                world["tick"]

                +

                random.randint(
                    50,
                    300
                ),

            "observations":

                result.get(
                    "observations",
                    []
                )
        })

    # =====================================================
    # NEXT TURN DELAY
    # =====================================================

    activity[
        "next_turn_tick"
    ] = (

        world["tick"]

        +

        random.randint(
            20,
            80
        )
    )

    return True