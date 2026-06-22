# =========================================================
# SEATING PLANNER
# For activities where the character should sit (computer work,
# desk tasks, etc.) this module decides whether a nearby seat
# can be used directly or whether one needs to be carried over.
#
# Entry point:
#   plan_seating(c, world, target_prop, queue_task_fn) -> bool
#       Prepends seat setup tasks to the activity queue.
#       Returns True if seating was planned, False if no seat
#       exists in the room at all (character will stand).
#
# Task types added:
#   carry_seat  — carry a chair to a computed spot near the target
#   use_seat    — walk to a seat and sit (sets c["seat_prop_id"])
# =========================================================

# ──────────────────────────────────────────────────────────
# Activities that strongly prefer a seat. If the resolved
# activity is in this set, plan_seating() is called before
# the rest of the queue is built.
# ──────────────────────────────────────────────────────────
SEATING_PREFERRED = {
    "use_computer",
    "work",
    "pay_bills",
    "browse_phone",   # desk browsing
    "fill_form",
    "respond_to_mail",
    "sort_mail",
    "study",
    "write",
}

# Tags that identify a prop as something you can sit on
_SEAT_TAGS = {"chair", "stool", "seatable", "office_chair", "bar_stool", "bench"}

# How many tiles away a seat can be and still count as "nearby"
# (Manhattan distance from the TARGET PROP, not the character)
NEARBY_THRESHOLD = 3

# Where to place a carried chair relative to the target prop
# (one tile in front, facing the prop)
_CARRY_OFFSET = 1


# =========================================================
# FIND FREE SEATS
# =========================================================

def _prop_tags(world, prop):
    from systems.props import get_prop_tags
    return set(get_prop_tags(world, prop))


def _seat_is_free(prop):
    """True if no sit anchor is occupied and no character is being carried on it."""
    if prop.get("carried_by"):
        return False
    for anchor in prop.get("anchors", []):
        if anchor.get("interactionName") == "sit" and anchor.get("occupied_by"):
            return False
    return True


def _dist_between_props(a, b):
    return abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])


def find_free_seats(world, near_prop=None):
    """
    Return all free seat props sorted by distance to near_prop (or globally).
    """
    props = world.get("props", {})
    prop_list = list(props.values()) if isinstance(props, dict) else props

    seats = [
        p for p in prop_list
        if _prop_tags(world, p) & _SEAT_TAGS and _seat_is_free(p)
    ]

    if near_prop:
        seats.sort(key=lambda s: _dist_between_props(s, near_prop))

    return seats


# =========================================================
# COMPUTE DESTINATION IN FRONT OF TARGET PROP
# =========================================================

def _seat_dest_for_prop(target_prop):
    """
    Return (x, y) for where a carried chair should be placed —
    one tile in front of the target prop (south face by default;
    respects prop rotation in the future).
    """
    rot = target_prop.get("rotation", 0)
    import math
    # Unit vector pointing "away" from the prop face the character will use
    dx = round(math.sin(math.radians(rot)))
    dy = round(math.cos(math.radians(rot)))
    return (
        target_prop["x"] + dx * _CARRY_OFFSET,
        target_prop["y"] + dy * _CARRY_OFFSET,
    )


# =========================================================
# MAIN ENTRY
# =========================================================

def plan_seating(c, world, target_prop):
    """
    Build seat-prep tasks and return (seat_task_ids, seat_prop_id).

    seat_task_ids — list of task IDs to include in depends_on for
                    later tasks that need the character to be seated.
    seat_prop_id  — the prop ID of the chosen seat (for the frontend).

    Returns ([], None) if no seat is available (character will stand).
    """
    from systems.activity_queue import queue_task

    target_prop_id = target_prop["id"]

    all_seats = find_free_seats(world, near_prop=target_prop)
    if not all_seats:
        return [], None

    closest = all_seats[0]
    dist    = _dist_between_props(closest, target_prop)

    if dist <= NEARBY_THRESHOLD:
        # ── Seat is already close enough — just walk and sit ──
        sit_id = queue_task(c, "use_seat", {
            "seat_prop_id":    closest["id"],
            "target_prop_id":  target_prop_id,
        })
        return [sit_id], closest["id"]

    else:
        # ── Carry the nearest seat to a spot in front of the target prop ──
        dest_x, dest_y = _seat_dest_for_prop(target_prop)

        carry_id = queue_task(c, "carry_seat", {
            "seat_prop_id":   closest["id"],
            "dest_x":         dest_x,
            "dest_y":         dest_y,
            "target_prop_id": target_prop_id,
        })

        sit_id = queue_task(c, "use_seat", {
            "seat_prop_id":   closest["id"],
            "target_prop_id": target_prop_id,
        }, depends_on=[carry_id])

        return [carry_id, sit_id], closest["id"]
