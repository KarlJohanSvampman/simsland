# =========================================================
# QUEUE ACTIVITY
# =========================================================

def queue_activity(

    character,

    activity_id
):

    q = character.setdefault(
        "activity_queue",
        []
    )

    q.append(activity_id)


# =========================================================
# NEXT ACTIVITY
# =========================================================

def pop_next_activity(
    character
):

    q = character.get(
        "activity_queue",
        []
    )

    if not q:
        return None

    return q.pop(0)