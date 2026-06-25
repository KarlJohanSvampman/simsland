import random

from systems.persistent_desires import (
    add_desire
)


# =========================================================
# UPDATE APPLIANCES
# =========================================================

def update_appliance_degradation(world):

    for household in world.get(
        "households",
        {}
    ).values():

        update_household_appliances(

            household,

            world
        )


# =========================================================
# HOUSEHOLD
# =========================================================

def update_household_appliances(

    household,

    world
):

    for obj in household.get(
        "owned_objects",
        []
    ):

        degrade_object(

            obj,

            household,

            world
        )


# =========================================================
# DEGRADE
# =========================================================

def degrade_object(

    obj,

    household,

    world
):

    quality = obj.get(
        "quality",
        0.5
    )

    durability = obj.get(
        "durability",
        quality
    )

    degradation = (
        0.000002
        *
        (1.2 - quality)
    )

    obj["durability"] = max(

        0,

        durability - degradation
    )

    # =====================================================
    # BROKEN
    # =====================================================

    if obj["durability"] <= 0.05:

        if obj.get("broken"):
            return

        obj["broken"] = True

        trigger_appliance_failure(

            obj,

            household,

            world
        )


# =========================================================
# FAILURE
# =========================================================

def trigger_appliance_failure(

    obj,

    household,

    world
):
    from systems.household_monitoring import choose_responsible_member

    object_type = obj.get(
        "object_type"
    )

    raw_members = household.get("members", [])

    # members may be character IDs or objects — normalise to objects
    members = []
    for m in raw_members:
        if isinstance(m, str):
            char = world["characters"].get(m)
            if char:
                members.append(char)
        elif isinstance(m, dict):
            members.append(m)

    if not members:
        return

    responsible = choose_responsible_member(members, world) or members[0]

    add_desire(

        responsible,

        desire_type=
            "replace_appliance",

        target=object_type,

        importance=0.9
    )

    household.setdefault(
        "notifications",
        []
    )

    household[
        "notifications"
    ].append({

        "type":
            "appliance_broken",

        "object_type":
            object_type,

        "tick":
            world["tick"]
    })
