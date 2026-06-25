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

def release_anchor(c, world):

    occ = c.get("occupying")
    if not occ:
        return

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