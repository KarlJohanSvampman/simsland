import asyncio

from llm.llm_queue import (
    enqueue
)

from llm.social_interpretation import (
    generate_social_interpretation
)

from systems.social_models import (
    ensure_social_model
)


# =========================================================
# QUEUE SOCIAL REFLECTION
# =========================================================

async def queue_social_reflection(

    observer,

    target,

    context
):

    async def job():

        return await generate_social_interpretation(

            observer,

            target,

            context
        )

    result = await enqueue(job)

    data = result.get(
        "text"
    )

    if not data:
        return None

    if isinstance(data, str):
        return None

    model = ensure_social_model(

        observer,

        target["id"]
    )

    # =====================================================
    # APPLY RESULTS
    # =====================================================

    summary = data.get(
        "summary"
    )

    if summary:

        model["summary"] = (
            summary
        )

    model["trust"] += data.get(
        "trust_shift",
        0
    )

    model["respect"] += data.get(
        "respect_shift",
        0
    )

    model["fear"] += data.get(
        "fear_shift",
        0
    )

    model["attraction"] += data.get(
        "attraction_shift",
        0
    )

    traits = data.get(
        "perceived_traits",
        []
    )

    if traits:

        model[
            "perceived_traits"
        ] = list(set(

            model[
                "perceived_traits"
            ]

            + traits
        ))

    model["confidence"] = min(

        1.0,

        model.get(
            "confidence",
            0.1
        )

        + 0.05
    )

    model[
        "last_reflection"
    ] = context.get(
        "tick"
    )

    return model    