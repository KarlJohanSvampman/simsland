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
_PROMPT_LOG_MAX = 100


def _purpose():
    """Which prompt this is: the first caller outside this module and the LLM gate, as "module.function"
    (e.g. "brain.llm_brain.think", "llm.diary_narration._generate_diary_text") -- for the VR LLM log."""
    import sys
    f = sys._getframe(2)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if mod not in (__name__, "llm.llm_gate", "asyncio.tasks", "asyncio.events") and not mod.startswith("asyncio"):
            return f"{mod}.{f.f_code.co_name}"
        f = f.f_back
    return "?"


def log_prompt_entry(char_id: str, messages: list, response: str, elapsed: float, cached: bool, purpose=None, error=None,
                     profile=None):
    """Store a prompt/response pair for a character. Thread-safe for asyncio."""
    if char_id not in _PROMPT_LOG:
        _PROMPT_LOG[char_id] = deque(maxlen=_PROMPT_LOG_MAX)
    _PROMPT_LOG[char_id].appendleft({
        "ts": time.time(),
        "messages": messages,
        "response": response,
        "elapsed_s": round(elapsed, 3),
        "cached": cached,
        "purpose": purpose or "?",
        **({"profile": profile} if profile else {}),
        **({"error": error} if error else {}),
    })

def add_prompt_entry(char_id: str, entry: dict):
    """Store an entry made elsewhere (a cognition worker's) as-is."""
    if char_id not in _PROMPT_LOG:
        _PROMPT_LOG[char_id] = deque(maxlen=_PROMPT_LOG_MAX)
    _PROMPT_LOG[char_id].appendleft(entry)

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


def _cache_key(messages, char_id=None, profile=None):
    # Confirmed live bug: this cache was keyed ONLY off the prompt's own
    # hash, with no character identity folded in at all -- two DIFFERENT
    # characters whose situations happened to produce the same (or even
    # just similarly-generic) prompt text got served the exact same
    # cached completion, verbatim, for up to 5 minutes. Real player
    # report: multiple characters "thinking exactly that same thing."
    # Namespacing by char_id preserves the cache's actual intent (skip a
    # redundant Ollama call when the SAME character re-asks with an
    # unchanged prompt) without ever sharing one person's completion as
    # another person's inner monologue.
    return (

        f"llm_cache:"
        f"{profile or 'default'}:"          # another model's reply is not this one's (llm/provider.py profiles)
        f"{char_id or 'anon'}:"

        f"{_hash_prompt(messages)}"
    )


# =========================================================
# RAW MODEL CALL (Ollama, or an OpenAI-compatible service: llm/provider.py)
# =========================================================

async def _call_llm(messages, timeout=60.0, max_tokens=None, char_id=None, profile=None):
    """One raw call, to the character's profile (llm/provider.py; no character: the background profile)."""
    from llm import provider
    if profile is None:
        profile = provider.profile_for(char_id)
    return await provider.chat(messages, timeout=timeout, max_tokens=max_tokens, profile=profile)


# =========================================================
# SAFE CALL
# =========================================================

async def call_llm_safe(

    messages,

    session=None,

    char_id=None,

    max_tokens=None,

    use_cache=True
):

    try:

        return await asyncio.wait_for(

            call_llm(

                messages,

                use_cache=use_cache,

                session=session,

                char_id=char_id,

                max_tokens=max_tokens
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

            "error": describe_llm_error(e)
        }


def describe_llm_error(e, call_timeout=120, overall_timeout=150, profile=None):
    """What went wrong with a model call, in words a person can act on. Timeouts
    used to come through as an empty string (str() of a timeout exception is
    usually ""), so a character's "wait" said "The model gave no usable answer ()."
    The text starts with a kind ("timeout:", "unreachable:", "http 500:", ...) that
    brain/llm_brain.py::_why_unusable() turns into the line shown in memory."""
    from llm import provider
    base, who = provider.base_url(profile), provider.label(profile)
    if isinstance(e, asyncio.TimeoutError):
        return f"timeout: no answer from the model within {overall_timeout} s"
    if isinstance(e, httpx.ConnectTimeout):
        return f"unreachable: couldn't connect to {who} at {base} (connection timed out)"
    if isinstance(e, httpx.TimeoutException):
        return f"timeout: {who} at {base} didn't answer within {call_timeout} s"
    if isinstance(e, httpx.ConnectError):
        return f"unreachable: couldn't connect to {who} at {base}"
    if isinstance(e, httpx.HTTPStatusError):
        body = (e.response.text or "").strip().replace("\n", " ")[:120]
        return f"http {e.response.status_code}: {who} refused the request" + (f" -- {body}" if body else "")
    detail = str(e).strip()
    return f"{type(e).__name__}" + (f": {detail}" if detail else "")


# =========================================================
# MAIN CALL
# =========================================================

async def call_llm(

    messages,

    timeout=120.0,

    use_cache=True,

    session=None,

    char_id=None,

    max_tokens=None
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

    from llm import provider as _provider
    profile = _provider.profile_for(char_id)

    key = _cache_key(
        full_messages,
        char_id=char_id,
        profile=profile
    )

    purpose = _purpose() if char_id else None

    if use_cache:

        cached = r.get(key)

        if cached:

            result = json.loads(cached)
            if char_id:                                # a cached reply is still what the character got
                log_prompt_entry(char_id, full_messages, result if isinstance(result, str) else json.dumps(result),
                                 elapsed=0.0, cached=True, purpose=purpose, profile=profile)
            return result

    # =====================================================
    # REAL CALL
    # =====================================================

    _t0 = time.time()

    try:
        result = await _call_llm(

            full_messages,

            timeout,

            max_tokens,

            char_id=char_id,

            profile=profile
        )
    except Exception as e:
        if char_id:                                    # a failed call is logged too, with why
            log_prompt_entry(char_id, full_messages, "", elapsed=time.time() - _t0, cached=False, purpose=purpose,
                             error=describe_llm_error(e, profile=profile), profile=profile)
        raise

    _elapsed = time.time() - _t0

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
            elapsed=_elapsed,
            cached=False,
            purpose=purpose,
            profile=profile,
        )

    return result