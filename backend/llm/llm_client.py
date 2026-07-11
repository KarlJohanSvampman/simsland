import hashlib
import json
import redis
import os
import asyncio
import httpx
import time
from collections import deque

# ---------------------------------------------------------------------------
# Per-character prompt log (in-memory ring buffer, max 50 entries per char)
# ---------------------------------------------------------------------------
_PROMPT_LOG: dict[str, deque] = {}
_PROMPT_LOG_MAX = 50

def log_prompt_entry(char_id: str, messages: list, response: str, elapsed: float, cached: bool):
    """Store a prompt/response pair for a character. Thread-safe for asyncio."""
    if char_id not in _PROMPT_LOG:
        _PROMPT_LOG[char_id] = deque(maxlen=_PROMPT_LOG_MAX)
    _PROMPT_LOG[char_id].appendleft({
        "ts": time.time(),
        "messages": messages,
        "response": response,
        "elapsed_s": round(elapsed, 3),
        "cached": cached,
    })

def get_prompt_log(char_id: str) -> list:
    """Return prompt history for a character, newest first."""
    return list(_PROMPT_LOG.get(char_id, []))

def clear_prompt_log(char_id: str):
    if char_id in _PROMPT_LOG:
        _PROMPT_LOG[char_id].clear()


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

    session=None,

    char_id=None
):

    try:

        return await asyncio.wait_for(

            call_llm(

                messages,

                session=session,

                char_id=char_id
            ),

            # Ollama cold-starts a model on its first call after being idle
            # (measured ~20-40s just for load_duration on this setup), and a
            # full character-context prompt (~3000 tokens) takes longer still
            # to evaluate — 15s was cutting that off every time, forcing the
            # fallback response. Must stay above call_llm's own httpx timeout
            # (120s) so that one fires first with a clean TimeoutException.
            timeout=150
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

    timeout=120.0,

    use_cache=True,

    session=None,

    char_id=None
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

    # Log prompt/response for debugging (keyed by char_id if provided)
    if char_id:
        log_prompt_entry(
            char_id,
            full_messages,
            result if isinstance(result, str) else json.dumps(result),
            elapsed=0.0,   # caller may patch if needed
            cached=False,
        )

    return result