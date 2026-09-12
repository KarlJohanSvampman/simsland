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
    being interrupted rather than completing normally."""
    release_anchor(c, world)
    c["activity"] = None


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