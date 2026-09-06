
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

        score = (

            rel["friendship"]
            +
            rel["romance"]
            +
            rel["familiarity"]
        )

        if score > strongest_score:

            strongest_score = score
            strongest_target = target_id

    if not strongest_target:
        return

    from brain.intentions import (
        add_intention
    )

    add_intention(c, {

        "type":
            "socialize",

        "category":
            "social",

        "priority":
            int(40 + loneliness * 50),

        "target_id":
            strongest_target,

        "source":
            "loneliness"
    })


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