import hashlib
import json
import redis
import os
import asyncio
import httpx


# =========================================================
# REDIS
# =========================================================

REDIS_HOST = os.getenv(
    "REDIS_HOST",
    "redis"
)

r = redis.Redis(

    host=REDIS_HOST,

    port=6379,

    decode_responses=True
)


# =========================================================
# CACHE
# =========================================================

def _hash_prompt(messages):

    return hashlib.sha256(

        json.dumps(

            messages,

            sort_keys=True

        ).encode()

    ).hexdigest()


def _cache_key(messages):

    return (

        f"llm_cache:"

        f"{_hash_prompt(messages)}"
    )


# =========================================================
# RAW OLLAMA CALL
# =========================================================

async def _call_llm(

    messages,

    timeout=60.0
):

    base = os.getenv(

        "OLLAMA_BASE_URL",

        "http://ollama:11434"
    ).rstrip("/")

    model = os.getenv(

        "OLLAMA_MODEL",

        "llama3"
    )

    async with httpx.AsyncClient(

        timeout=timeout

    ) as client:

        response = await client.post(

            f"{base}/api/chat",

            json={

                "model": model,

                "messages": messages,

                "stream": False
            }
        )

        response.raise_for_status()

        data = response.json()

        return data.get(

            "message",

            {}
        ).get(

            "content",

            ""
        )


# =========================================================
# SAFE CALL
# =========================================================

async def call_llm_safe(

    messages,

    session=None
):

    try:

        return await asyncio.wait_for(

            call_llm(

                messages,

                session=session
            ),

            timeout=15
        )

    except Exception as e:

        return {

            "error": str(e)
        }


# =========================================================
# MAIN CALL
# =========================================================

async def call_llm(

    messages,

    timeout=60.0,

    use_cache=True,

    session=None
):

    # =====================================================
    # BUILD FULL MESSAGE STREAM
    # =====================================================

    full_messages = []

    # -----------------------------------------------------
    # SESSION HISTORY
    # -----------------------------------------------------

    if session is not None:

        session.setdefault(
            "history",
            []
        )

        history = session[
            "history"
        ]

        # only recent rolling context

        full_messages.extend(

            history[-12:]
        )

    # -----------------------------------------------------
    # CURRENT PROMPT
    # -----------------------------------------------------

    full_messages.extend(
        messages
    )

    # =====================================================
    # CACHE
    # =====================================================

    key = _cache_key(
        full_messages
    )

    if use_cache:

        cached = r.get(key)

        if cached:

            return json.loads(
                cached
            )

    # =====================================================
    # REAL CALL
    # =====================================================

    result = await _call_llm(

        full_messages,

        timeout
    )

    # =====================================================
    # UPDATE SESSION
    # =====================================================

    if session is not None:

        session["history"].extend([

            *messages,

            {
                "role": "assistant",

                "content": result
            }
        ])

        # rolling memory only

        session["history"] = (

            session["history"][-20:]
        )

        session[
            "last_used"
        ] = asyncio.get_event_loop().time()

    # =====================================================
    # CACHE STORE
    # =====================================================

    if use_cache:

        r.set(

            key,

            json.dumps(result),

            ex=300
        )

    return result