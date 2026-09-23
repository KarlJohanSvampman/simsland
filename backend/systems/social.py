
# =========================================================
# SOCIAL SYSTEM
# =========================================================

from collections import defaultdict

SOCIAL_ACTIONS = [

    "send_text",

    "call",

    "visit",

    "invite_over",

    "reply_text",

    "ignore",

    "gossip",

    "argue"
]
# =========================================================
# ENSURE SOCIAL STATE
# =========================================================

def ensure_social_state(c):

    c.setdefault(
        "relationships",
        {}
    )

    c.setdefault(
        "social",
        {}
    )

    c["social"].setdefault(
        "messages",
        []
    )

    c["social"].setdefault(
        "missed_calls",
        []
    )


# =========================================================
# GET RELATIONSHIP
# =========================================================

def get_relationship(

    c,

    target_id
):

    # Delegates to brain.relationships.ensure_relationship() for the real,
    # full relationship shape (20+ fields: hostility/fear/rivalry/
    # jealousy/designation/labels/...) instead of this function's own,
    # much smaller 7-key dict -- the two used to independently build the
    # SAME c["relationships"][target_id] entry with incompatible shapes,
    # and whichever ran first for a given pair "won," leaving the other
    # shape's fields permanently missing (a real, live crash: e.g.
    # sim_loop.py::_update_nearby_relationships reading rel["familiarity"]
    # / rel["friendship"] unconditionally on a dict this function created
    # first). "romance"/"last_contact" are this module's own extra
    # legacy field names (kept, defaulted here) distinct from
    # ensure_relationship's "romantic_interest"/"last_interaction".
    ensure_social_state(c)

    from brain.relationships import ensure_relationship
    rel = ensure_relationship(c, target_id)
    rel.setdefault("romance", rel.get("romantic_interest", 0))
    rel.setdefault("last_contact", None)
    return rel


# =========================================================
# MODIFY RELATIONSHIP
# =========================================================

def modify_relationship(

    c,

    target_id,

    stat,

    amount
):

    rel = get_relationship(
        c,
        target_id
    )

    rel[stat] = max(

        -100,

        min(
            100,

            rel.get(stat, 0)
            + amount
        )
    )


# =========================================================
# SEND MESSAGE
# =========================================================

def send_message(

    sender,

    target,

    text,

    world
):

    ensure_social_state(sender)
    ensure_social_state(target)

    msg = {

        "id": f"msg_{world['tick']}",

        "from_id":
            sender["id"],

        "to_id":
            target["id"],

        "text":
            text,

        "timestamp":
            world["tick"],

        "read":
            False
    }

    world.setdefault(
        "messages",
        []
    )

    world["messages"].append(
        msg
    )

    target["social"][
        "messages"
    ].append(msg["id"])

    rel = get_relationship(

        sender,

        target["id"]
    )

    rel["last_contact"] = (
        world["tick"]
    )

    return msg


# =========================================================
# GET CHARACTER BY ID
# =========================================================

def get_character_by_id(world, char_id):
    return world.get("characters", {}).get(char_id)


# =========================================================
# GET RECENT MESSAGES
# =========================================================

def get_recent_messages(

    c,

    world,

    limit=10
):

    ensure_social_state(c)

    ids = c["social"].get(
        "messages",
        []
    )

    msgs = []

    for m in world.get(
        "messages",
        []
    ):

        if m["id"] in ids:
            msgs.append(m)

    msgs.sort(
        key=lambda x: x["timestamp"],
        reverse=True
    )

    return msgs[:limit]


# =========================================================
# MARK MESSAGE READ
# =========================================================

def mark_message_read(

    c,

    msg_id,

    world
):

    for msg in world.get(
        "messages",
        []
    ):

        if msg["id"] == msg_id:

            msg["read"] = True
            return


# =========================================================
# SOCIAL NEED
# =========================================================

def social_need_score(c):

    # Social drive = frustration of the "socialize" long-term need (0-1)
    frustration = c.get("lt_needs", {}).get("socialize", {}).get("frustration", 0.0)
    return frustration


# =========================================================
# GENERATE SOCIAL INTENTIONS
# =========================================================

def generate_social_intentions(

    c,

    world
):

    ensure_social_state(c)

    loneliness = social_need_score(c)

    if loneliness < 0.4:
        return

    strongest_target = None
    strongest_score = -999

    for target_id, rel in c[
        "relationships"
    ].items():

        # This function had no caller anywhere until now (see sim_loop.py),
        # so its assumption that every relationship dict already carries
        # friendship/romance/familiarity was never actually exercised --
        # some relationships (e.g. built via older/partial code paths)
        # don't, which crashed the whole tick loop the first time this
        # ran for real. .get(..., 0) treats a missing dimension as neutral
        # rather than requiring a broader relationship-schema migration.
        score = (

            rel.get("friendship", 0)
            +
            rel.get("romance", 0)
            +
            rel.get("familiarity", 0)
        )

        if score > strongest_score:

            strongest_score = score
            strongest_target = target_id

    if not strongest_target:
        return

    from brain.intentions import (
        add_intention
    )

    target_char = world.get("characters", {}).get(strongest_target)
    target_name = target_char.get("name") if target_char else None

    add_intention(c, {

        "type":
            "socialize",

        "category":
            "social",

        "priority":
            int(40 + loneliness * 50),

        "target_id":
            strongest_target,

        "reason":
            f"You've been craving more social contact -- {target_name} comes to mind."
            if target_name else "You've been craving more social contact lately.",

        "source":
            "loneliness"
    })


# =========================================================
# INTERRUPT SOCIALIZING WITH AN UNAVAILABLE TARGET
# =========================================================
# Player report: a sim was shown "socialize (Kimberly Jackson)" while
# Kimberly herself was asleep in bed. Confirmed real, two-part gap:
# (1) action_router.py's socialize dispatch never checked the target's
# own availability before scaffolding the activity -- fixed there
# directly (see its own "target_unavailable" check) for anyone who tries
# to START socializing with someone already asleep/off-grid; (2) nothing
# ever re-checked an ALREADY-RUNNING socialize activity once its target
# became unavailable partway through (the far more likely real sequence
# here: Dennis started chatting with Kimberly while she was still awake,
# she went to bed for the night, and his own 900-tick activity just kept
# running against a target who was no longer there to talk to). This
# sweep is the fix for that second half.

def interrupt_socializing_with_unavailable_targets(world):
    """Called on a moderate cadence (see CADENCE["social_availability"],
    sim_loop.py). For every character mid-"socialize", checks whether
    their target has since fallen asleep or gone off-grid, and if so
    interrupts the activity for real (systems/occupancy.py::
    interrupt_activity -- releases anchors/posture properly, not a bare
    c["activity"] = None)."""
    from systems.occupancy import interrupt_activity

    chars = world.get("characters", {})
    for c in chars.values():
        act = c.get("activity") or {}
        if act.get("type") != "socialize":
            continue
        target = chars.get(act.get("target_id"))
        if not target:
            continue
        if (target.get("activity") or {}).get("type") == "sleep" or target.get("off_grid"):
            interrupt_activity(c, world)


# =========================================================
# BUILD RELATIONSHIP CONTEXT
# =========================================================

def build_relationship_context(

    c,

    world,

    limit=8
):

    ensure_social_state(c)

    results = []

    for target_id, rel in c[
        "relationships"
    ].items():

        target = get_character_by_id(
            world,
            target_id
        )

        if not target:
            continue

        results.append({

            "name":
                target["name"],

            "id":
                target["id"],

            "friendship":
                rel["friendship"],

            "romance":
                rel["romance"],

            "trust":
                rel["trust"],

            "resentment":
                rel["resentment"],

            "familiarity":
                rel["familiarity"],

            "last_contact":
                rel["last_contact"]
        })

    results.sort(

        key=lambda x: (

            x["friendship"]
            +
            x["romance"]
            +
            x["familiarity"]
        ),

        reverse=True
    )

    return results[:limit]


# =========================================================
# BUILD MESSAGE CONTEXT
# =========================================================

def build_message_context(

    c,

    world,

    limit=10
):

    msgs = get_recent_messages(

        c,

        world,

        limit
    )

    results = []

    for m in msgs:

        sender = get_character_by_id(
            world,
            m["from_id"]
        )

        if not sender:
            continue

        results.append({

            "from":
                sender["name"],

            "text":
                m["text"],

            "read":
                m["read"],

            "timestamp":
                m["timestamp"]
        })

    return results