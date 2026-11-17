"""
llm/provider.py -- which model service the simulation talks to, and how.

Every model call goes through llm_client._call_llm, which hands the request to the provider chosen here:

    LLM_PROVIDER=ollama   (default) an Ollama server: POST {OLLAMA_BASE_URL}/api/chat, model OLLAMA_MODEL
    LLM_PROVIDER=openai   anything speaking the OpenAI chat-completions API: POST {LLM_BASE_URL}/chat/completions

The OpenAI form covers ChatGPT and most hosted services, which offer the same API:

    service          LLM_BASE_URL                                              LLM_MODEL (examples)
    OpenAI           https://api.openai.com/v1 (the default)                   gpt-4o-mini, gpt-4.1-mini
    Google Gemini    https://generativelanguage.googleapis.com/v1beta/openai   gemini-2.5-flash
    Anthropic        https://api.anthropic.com/v1                              (a Claude model id)
    OpenRouter       https://openrouter.ai/api/v1                              any model it lists
    Groq             https://api.groq.com/openai/v1                            llama-3.1-8b-instant
    local servers    LM Studio http://host:1234/v1, vLLM / llama.cpp http://host:8000/v1, Ollama http://host:11434/v1

    LLM_API_KEY        the key (OPENAI_API_KEY is read too); sent as "Authorization: Bearer <key>"
    LLM_MODEL          the model (falls back to OLLAMA_MODEL)
    LLM_MAX_TOKENS     "keep" (default): pass the caller's reply cap on; "off": never cap. Reasoning models (OpenAI's
                       o-series and gpt-5) count their hidden reasoning against the cap, so a short cap can leave them
                       with an empty answer -- use "off" for those.
    LLM_REASONING_EFFORT   optional, passed on as reasoning_effort (minimal / low / medium / high) for models that take it

How many calls run at once is still OLLAMA_MAX_CONCURRENCY (llm/llm_gate.py); a hosted service usually takes more than
a local server, so raise it there (LLM_MAX_CONCURRENCY is read as the same setting).
"""

import os

import httpx


def name():
    return (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()


def label():
    """How the provider is named to people (the status light, error lines)."""
    if name() != "openai":
        return "Ollama"
    base = base_url()
    for host, nice in (("api.openai.com", "OpenAI"), ("googleapis.com", "Gemini"), ("anthropic.com", "Anthropic"),
                       ("openrouter.ai", "OpenRouter"), ("groq.com", "Groq")):
        if host in base:
            return nice
    return "Model API"


def base_url():
    if name() == "openai":
        return (os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    return os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")


def model():
    if name() == "openai":
        return os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "gpt-4o-mini"
    return os.getenv("OLLAMA_MODEL", "llama3")


def _headers():
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def chat_request(messages, max_tokens=None):
    """(url, json body, headers) for one chat call -- built apart from sending it, so it can be checked."""
    if name() == "openai":
        body = {"model": model(), "messages": messages}
        if max_tokens and (os.getenv("LLM_MAX_TOKENS") or "keep").lower() != "off":
            # OpenAI's own API wants max_completion_tokens (newer models refuse max_tokens); the compatible services
            # take max_tokens
            body["max_completion_tokens" if "api.openai.com" in base_url() else "max_tokens"] = int(max_tokens)
        if os.getenv("LLM_REASONING_EFFORT"):
            body["reasoning_effort"] = os.getenv("LLM_REASONING_EFFORT")
        return f"{base_url()}/chat/completions", body, _headers()
    # Ollama defaults num_ctx to whatever the model's Modelfile specifies (measured 4096 for the llama3.1 instance this
    # backend talks to -- close to a real character context, risking silent truncation) and keep_alive to 5m, which
    # can cold-reload the model (~20-40s) between ticks on a quiet character. Both are explicit and tunable.
    body = {"model": model(), "messages": messages, "stream": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
            "options": {"num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
                        # a cap on the reply, when the caller wants one (the decision reply is a few short lines; on a
                        # slow server every token it is left to ramble on for is seconds of waiting)
                        **({"num_predict": int(max_tokens)} if max_tokens else {})}}
    return f"{base_url()}/api/chat", body, {}


def reply_text(data):
    """The reply's text out of the provider's response body."""
    if name() == "openai":
        choices = data.get("choices") or []
        content = ((choices[0] if choices else {}).get("message") or {}).get("content")
        if isinstance(content, list):                  # some services return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content or ""
    return (data.get("message") or {}).get("content", "")


async def chat(messages, timeout=60.0, max_tokens=None):
    url, body, headers = chat_request(messages, max_tokens)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return reply_text(response.json())


def status(timeout=3.0):
    """Is the model service up, and does it have the configured model? For the status light (api/debug.py).
    state: "up" (answered, model available) / "degraded" (answered, model not listed) / "down" (no answer, or refused)."""
    import time
    base, mdl = base_url(), model()
    out = {"provider": name(), "provider_label": label(), "base_url": base, "model": mdl, "checked_at": time.time(),
           "error": None}
    try:
        started = time.monotonic()
        with httpx.Client(timeout=timeout) as client:
            if name() == "openai":
                if not _headers() and "api.openai.com" in base:
                    out.update(state="down", error="no API key: set LLM_API_KEY (or OPENAI_API_KEY)")
                    return out
                resp = client.get(f"{base}/models", headers=_headers())
                resp.raise_for_status()
                out["latency_ms"] = round((time.monotonic() - started) * 1000)
                listed = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
                # Gemini lists "models/gemini-..."; a service that lists nothing is taken at its word that it serves it
                out["model_available"] = not listed or any(i == mdl or (i or "").endswith("/" + mdl) for i in listed)
                out["loaded"] = None
            else:
                tags = client.get(f"{base}/api/tags")
                tags.raise_for_status()
                out["latency_ms"] = round((time.monotonic() - started) * 1000)
                installed = [m.get("name") or m.get("model") for m in tags.json().get("models", [])]
                try:
                    ps = client.get(f"{base}/api/ps")
                    ps.raise_for_status()
                    out["loaded"] = [m.get("name") or m.get("model") for m in ps.json().get("models", [])]
                except (httpx.HTTPError, ValueError):
                    out["loaded"] = None      # older Ollama without /api/ps -- not a reason to call it down
                wanted = {mdl, mdl if ":" in mdl else f"{mdl}:latest"}   # "llama3" and "llama3:latest" are one model
                out["model_available"] = any(n in wanted for n in installed)
        out["state"] = "up" if out["model_available"] else "degraded"
        if not out["model_available"]:
            out["error"] = f"model '{mdl}' is not available on this {label()} server"
    except httpx.TimeoutException:
        out.update(state="down", error=f"no answer within {timeout:g} s")
    except httpx.HTTPStatusError as exc:
        why = {401: "the API key was refused", 403: "the API key isn't allowed this"}.get(exc.response.status_code)
        out.update(state="down", error=why or f"http {exc.response.status_code}")
    except (httpx.HTTPError, ValueError) as exc:
        out.update(state="down", error=f"{type(exc).__name__}: {exc}"[:200])
    return out
