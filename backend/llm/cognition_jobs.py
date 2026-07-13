from llm.social_interpretation import (
    generate_social_interpretation
)

from systems.social_models import (
    ensure_social_model
)


# =========================================================
# QUEUE SOCIAL REFLECTION
# =========================================================
# Concurrency is bounded by the caller — see systems/reflection.py's
# handle_reflection(), which submits this whole coroutine through
# llm/llm_gate.py's shared semaphore. This used to go through its own
# single-consumer queue (llm/llm_queue.py); that's retired in favor of one
# shared concurrency budget across every Ollama caller in the codebase.

async def queue_social_reflection(

    observer,

    target,

    context
):

    data = await generate_social_interpretation(

        observer,

        target,

        context
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