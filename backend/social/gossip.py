import random


# =========================================================
# SPREAD GOSSIP
# =========================================================

def spread_gossip(

    world,

    source,

    listener,

    topic,

    sentiment
):

    listener.setdefault(
        "heard_rumors",
        []
    )

    listener["heard_rumors"].append({

        "topic":
            topic,

        "sentiment":
            sentiment,

        "source":
            source["id"]
    })

    # memory
    from brain.memory import (
        store_memory
    )

    store_memory(

        listener,

        f"{source['name']} talked "
        f"about {topic}.",

        0.4,

        [

            "gossip",

            topic
        ],

        "gossip",

        world["tick"]
    )