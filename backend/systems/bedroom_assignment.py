"""
systems/bedroom_assignment.py

Persistent bedroom *ownership* by age, distinct from systems/room_assignment.py
(which tracks which room a character is currently standing in, a live
positional lookup called every time someone moves). This module answers a
different question: which room is this character's own, long-term.

Policy:
  primary (adult/elderly) -- a spouse/partner pair shares one room as a
                              unit; an unpartnered adult gets their own.
  teen    (age >= 14)      -- private room while rooms remain.
  child   (age < 14)       -- paired up 2-per-room.
If bedrooms run out, the lowest-priority remaining group doubles up into
whatever room is left rather than leaving anyone unassigned.
"""

CHILD_PRIVATE_AGE = 14


def _get_building_for_home(home, world):
    if not home:
        return None
    home_id = home.get("id")
    for building in world.get("buildings", []):
        if building.get("id") == home_id:
            return building
    return None


def _is_partner(a, b):
    rel = a.get("relationships", {}).get(b["id"], {})
    return any(l in rel.get("labels", []) for l in ("spouse", "partner"))


def _group_household_members(members):
    """Split into (primary_units, teens, child_pairs) where primary_units
    is a list of 1-2-element lists (partner pairs kept together) and
    child_pairs is a list of 1-2-element lists (children paired in order)."""
    adults = [m for m in members if m.get("age_group") in ("adult", "elderly")]
    teens  = [m for m in members if m.get("age", 0) >= CHILD_PRIVATE_AGE
              and m.get("age_group") not in ("adult", "elderly")]
    children = [m for m in members if m.get("age", 0) < CHILD_PRIVATE_AGE
                and m.get("age_group") not in ("adult", "elderly")]

    primary_units = []
    used = set()
    for a in adults:
        if a["id"] in used:
            continue
        partner = next((b for b in adults if b["id"] != a["id"]
                         and b["id"] not in used and _is_partner(a, b)), None)
        if partner:
            primary_units.append([a, partner])
            used.add(a["id"])
            used.add(partner["id"])
        else:
            primary_units.append([a])
            used.add(a["id"])

    child_pairs = [children[i:i + 2] for i in range(0, len(children), 2)]

    return primary_units, teens, child_pairs


def assign_bedrooms_for_household(household, world):
    from systems.housing import get_household_home

    home = get_household_home(household, world)
    building = _get_building_for_home(home, world)
    if not building:
        return

    bedrooms = [r for r in building.get("rooms", []) if r.get("type") == "bedroom"]
    if not bedrooms:
        return

    chars = world.get("characters", {})
    members = [chars[mid] for mid in household.get("members", []) if mid in chars]
    if not members:
        return

    primary_units, teens, child_pairs = _group_household_members(members)

    # Priority order: primary units, then teens (solo), then child pairs.
    groups = list(primary_units) + [[t] for t in teens] + list(child_pairs)

    room_idx = 0
    for room in bedrooms:
        room["assigned_to"] = []

    for group in groups:
        if room_idx < len(bedrooms):
            room = bedrooms[room_idx]
            room_idx += 1
        else:
            # Out of rooms -- double up into the last room rather than
            # leaving anyone unassigned.
            room = bedrooms[-1]
        room["assigned_to"].extend(m["id"] for m in group)
        for m in group:
            m["bedroom_id"] = room["id"]


def tick_bedroom_assignments(world):
    """Cadence-driven sweep (see CADENCE["bedroom_assignment"]). The
    grouping/allocation in assign_bedrooms_for_household is deterministic
    given the same household composition and ages, so simply recomputing
    every sweep is idempotent (no thrash on an unchanged household) and
    automatically picks up new members or an age crossing the private-room
    threshold -- no separate dirty-tracking needed, household sizes here
    are small enough that this is cheap."""
    for household in world.get("households", {}).values():
        assign_bedrooms_for_household(household, world)
