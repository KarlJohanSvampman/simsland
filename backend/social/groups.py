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


# =========================================================
# UPDATE GROUP BELIEFS
# =========================================================

def update_group_beliefs(

    group,

    world
):

    totals = {}
    counts = {}

    for mid in group["members"]:

        c = world[
            "characters"
        ].get(mid)

        if not c:
            continue

        for topic, b in c.get(
            "beliefs",
            {}
        ).items():

            totals[topic] = (
                totals.get(topic, 0)
                + b.get("value", 0)
            )

            counts[topic] = (
                counts.get(topic, 0)
                + 1
            )

    group["beliefs"] = {

        topic:
            totals[topic]
            / counts[topic]

        for topic in totals
    }


    # =========================================================
# UPDATE GROUP BELIEFS
# =========================================================

def update_group_beliefs(

    group,

    world
):

    totals = {}
    counts = {}

    for mid in group["members"]:

        c = world[
            "characters"
        ].get(mid)

        if not c:
            continue

        for topic, b in c.get(
            "beliefs",
            {}
        ).items():

            totals[topic] = (
                totals.get(topic, 0)
                + b.get("value", 0)
            )

            counts[topic] = (
                counts.get(topic, 0)
                + 1
            )

    group["beliefs"] = {

        topic:
            totals[topic]
            / counts[topic]

        for topic in totals
    }

from brain.beliefs import (
    update_belief
)

def apply_group_influence(

    group,

    world
):

    beliefs = group.get(
        "beliefs",
        {}
    )

    for mid in group["members"]:

        c = world[
            "characters"
        ].get(mid)

        if not c:
            continue

        for topic, value in beliefs.items():

            sentiment = (
                "positive"
                if value > 0
                else "negative"
            )

            update_belief(

                c,

                topic,

                sentiment,

                abs(value) * 0.05,

                world["tick"]
            )