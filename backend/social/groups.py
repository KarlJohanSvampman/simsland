from social.relationship_score import (
    relationship_score
)


# =========================================================
# DETECT CLOSE CONNECTIONS
# =========================================================

def close_connections(

    c,

    world,

    threshold=60
):

    results = []

    for other in world.get(
        "characters",
        {}
    ).values():

        if other["id"] == c["id"]:
            continue

        score = relationship_score(

            c,

            other["id"]
        )

        if score >= threshold:

            results.append(other)

    return results


    # =========================================================
# BUILD SOCIAL GROUPS
# =========================================================

def build_social_groups(world):

    groups = []

    visited = set()

    chars = list(

        world.get(
            "characters",
            {}
        ).values()
    )

    for c in chars:

        if c["id"] in visited:
            continue

        connected = close_connections(
            c,
            world
        )

        if not connected:
            continue

        group = {

            "members":
                [c["id"]],

            "type":
                "friend_group"
        }

        visited.add(c["id"])

        for other in connected:

            group["members"].append(
                other["id"]
            )

            visited.add(
                other["id"]
            )

        groups.append(group)

    world["social_groups"] = groups