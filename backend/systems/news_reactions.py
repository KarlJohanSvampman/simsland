from brain.beliefs import (
    update_belief
)


# =========================================================
# PROCESS NEWS
# =========================================================

def process_news_reaction(

    c,

    news,

    tick
):

    topic = news.get("topic")

    sentiment = news.get(
        "sentiment",
        "neutral"
    )

    intensity = news.get(
        "intensity",
        0.5
    )

    if not topic:
        return

    update_belief(

        c,

        topic,

        sentiment,

        intensity,

        tick
    )