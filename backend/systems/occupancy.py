def find_free_anchor(prop, interaction):

    for a in prop.get("anchors", []):
        if a.get("interaction") == interaction and not a.get("occupied_by"):
            return a

    return None


def reserve_anchor(c, prop, anchor):

    anchor["occupied_by"] = c["id"]
    anchor.setdefault("queue", [])
    c["occupying"] = {
        "prop_id": prop["id"],
        "anchor_name": anchor["name"]
    }


def enqueue_anchor(c, prop, anchor):
    anchor.setdefault("queue", [])
    if c["id"] not in anchor["queue"]:
        anchor["queue"].append(c["id"])

def interrupt_activity(c, world):
    """Confirmed live bug: at least a dozen call sites across this
    codebase clear a character's activity directly (`c["activity"] =
    None`) to interrupt it -- a conversation starting, curiosity
    pulling them away, claustrophobia, psychosis, travel departing,
    etc. -- without releasing whatever prop anchor that activity had
    reserved (systems/interactions.py::begin_interaction() reserves one
    for every interaction-based activity: use_toilet, take_shower,
    wash_hands, ...). complete_activity()'s own release_anchor() call
    only fires on a NATURAL finish, so an interrupted use_toilet left
    the toilet permanently "occupied_by" someone who'd since wandered
    off elsewhere entirely, silently blocking everyone else forever
    (confirmed live: a queued character never got their turn because
    the anchor they were waiting on was never actually freed). Use this
    instead of a bare `c["activity"] = None` anywhere an activity is
    being interrupted rather than completing normally.

    Second confirmed live bug, same root cause: this never reset
    c["posture"] either -- a character interrupted mid-sleep (posture
    "lying") and sent off on a trip (travel.py:93-94 calls this right
    before departure) kept showing "lying" the whole time they were
    walking to/waiting for the bus, since travel's own frozen
    travel_state states skip update_internal_state's normal posture
    processing entirely (see interrupt_travel_for_incapacitation's own
    docstring). Reset here, once, at the moment of interruption --
    exactly mirrors activities.py's use_toilet-completion posture fix."""
    # Confirmed live bug (player report: a character gave up mid-"drink
    # water", still 0% hydrated, with zero trace of it -- no debug
    # bubble, no memory, the intention never marked as anything other
    # than pending): this shared interrupt path -- used by well over a
    # dozen call sites (a conversation starting, curiosity, travel
    # departing, work priority, ...) -- never logged the interruption at
    # all. debug_log.py's activity_started/completed events already
    # exist for the other two lifecycle points; this is the missing
    # third one.
    act = c.get("activity") or {}
    act_type = act.get("type")
    if act_type:
        from systems.debug_log import log_activity
        log_activity(c, world, act_type, "interrupted")
        from core.event_bus import emit
        emit("activity_interrupted", {
            "character_id": c["id"], "activity_type": act_type,
            "target_id": act.get("target_id"), "anchor_name": act.get("anchor_name"),
            "x": c.get("x"), "y": c.get("y"), "building_id": c.get("building_id"),
        })

    release_anchor(c, world)
    c["activity"] = None
    from systems.posture import set_posture
    set_posture(c, world, "standing")


def release_anchor(c, world):

    occ = c.get("occupying")
    if not occ:
        return

    c["occupying"] = None

    prop_id = occ["prop_id"]
    anchor_name = occ["anchor_name"]

    for p in world.get("props", []):
        if p["id"] != prop_id:
            continue

        for a in p.get("anchors", []):
            if a["name"] != anchor_name:
                continue

            if a.get("occupied_by") == c["id"]:
                a["occupied_by"] = None

                # 🔥 wake next in queue
                queue = a.get("queue", [])
                if queue:
                    next_id = queue.pop(0)

                    for c2 in world["characters"].values():
                        if c2["id"] == next_id:
                            c2["activity"] = None  # force replan


def reserve_anchor_for(c, anchor, world, timeout=10):
    if anchor.get("occupied_by"):
        return False

    if anchor.get("reserved_by") and anchor["reserved_by"] != c["id"]:
        return False

    anchor["reserved_by"] = c["id"]
    anchor["reserved_until"] = world["tick"] + timeout

    return True


def release_reservation(c, world):
    for p in world.get("props", []):
        for a in p.get("anchors", []):
            if a.get("reserved_by") == c["id"]:
                a["reserved_by"] = None
                a["reserved_until"] = None