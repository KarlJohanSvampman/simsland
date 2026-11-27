"""
llm/provider.py -- which model service the simulation talks to, and how.

Every model call goes through llm_client._call_llm, which hands the request to the provider chosen here:

    LLM_PROVIDER=ollama   (default) an Ollama server: POST {OLLAMA_BASE_URL}/api/chat, model OLLAMA_MODEL
    LLM_PROVIDER=openai   anything speaking the OpenAI chat-completions API: POST {LLM_BASE_URL}/chat/completions

The OpenAI form covers ChatGPT and most hosted services, which offer the same API:

    service          LLM_BASE_URL                                              LLM_MODEL (examples)
    OpenAI           https://api.openai.com/v1 (the default)                   gpt-4o-mini, gpt-4.1-mini
    Google Gemini    https://generativelanguage.googleapis.com/v1beta/openai   gemini-3.5-flash-lite
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

SEVERAL AT ONCE -- profiles (backend/llm_profiles.json, or LLM_PROFILES_FILE; see llm_profiles.example.json)

    {"default": "local", "background": "local",
     "profiles": {"local": {"provider": "ollama", "base_url": "http://192.168.10.176:11434", "model": "llama3.1:latest",
                            "max_concurrency": 2},
                  "gpt":   {"provider": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY",
                            "max_concurrency": 8}},
     "assign": {"characters": {"Kathleen Okafor": "gpt"}, "surnames": {"Okafor": "gpt"}}}

Each character's calls go to its profile: the character's own `llm_profile` field (set in the inspector's Persona tab),
else an `assign` entry for it (character id or full name, then surname), else `default`. Calls made for no character
(narration of the world, background summaries) use `background` (else `default`). Keys never go in the file: a profile
names the environment variable holding its key (api_key_env; an openai profile without one reads LLM_API_KEY /
OPENAI_API_KEY). Every llm_gate lane is per profile, with the profile's own max_concurrency, so a slow local server
never holds up characters on a hosted API. The file is re-read when it changes.

No file: a single profile, "env", built from the LLM_* / OLLAMA_* variables above -- exactly the old behaviour.
"""

import contextvars
import json
import os
import threading
import time

import httpx

ENV_PROFILE = "env"
_PROVIDERS = ("ollama", "openai")


# ── profiles ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _profiles_path():
    return os.getenv("LLM_PROFILES_FILE") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                          "llm_profiles.json")


_cfg = {"path": None, "mtime": None, "data": None, "checked": 0.0}
_cfg_lock = threading.Lock()


def config():
    """The parsed profiles file, or None when there isn't one (or it can't be read -- said once in the log)."""
    path = _profiles_path()
    now = time.monotonic()
    with _cfg_lock:
        if _cfg["path"] == path and now - _cfg["checked"] < 2.0:
            return _cfg["data"]
        _cfg["checked"] = now
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            _cfg.update(path=path, mtime=None, data=None)
            return None
        if _cfg["path"] == path and _cfg["mtime"] == mtime:
            return _cfg["data"]
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict) or not data["profiles"]:
                raise ValueError('needs a non-empty "profiles" object')
        except Exception as exc:                                    # noqa: BLE001 -- a bad file must not stop the sim
            print(f"[llm] {path} ignored: {exc}")
            data = None
        _cfg.update(path=path, mtime=mtime, data=data)
        return data


def profile_names():
    cfg = config()
    return list(cfg["profiles"]) if cfg else [ENV_PROFILE]


def default_name():
    cfg = config()
    if not cfg:
        return ENV_PROFILE
    d = cfg.get("default")
    return d if d in cfg["profiles"] else next(iter(cfg["profiles"]))


def background_name():
    cfg = config()
    if cfg and cfg.get("background") in cfg["profiles"]:
        return cfg["background"]
    return default_name()


def _known(profile_name):
    return profile_name in profile_names()


def settings(profile_name=None):
    """Everything one call needs, for a profile name (None: the default). Read fresh each time -- env and file both."""
    cfg = config()
    pname = profile_name if profile_name and _known(profile_name) else default_name()
    if not cfg:
        prov = (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()
        if prov == "openai":
            base = (os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
            mdl = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "gpt-4o-mini"
        else:
            base = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
            mdl = os.getenv("OLLAMA_MODEL", "llama3")
        return {"name": ENV_PROFILE, "provider": prov, "base_url": base, "model": mdl,
                "api_key": os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
                "max_tokens": (os.getenv("LLM_MAX_TOKENS") or "keep").lower(),
                "reasoning_effort": os.getenv("LLM_REASONING_EFFORT") or None,
                "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
                "max_concurrency": int(os.getenv("LLM_MAX_CONCURRENCY") or os.getenv("OLLAMA_MAX_CONCURRENCY", "2"))}
    p = cfg["profiles"][pname] or {}
    prov = str(p.get("provider") or "ollama").strip().lower()
    if prov not in _PROVIDERS:
        print(f"[llm] profile {pname!r}: unknown provider {prov!r}, using ollama")
        prov = "ollama"
    if prov == "openai":
        base = (p.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        mdl = p.get("model") or "gpt-4o-mini"
        key_env = p.get("api_key_env")
        key = os.getenv(key_env) if key_env else (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    else:
        base = (p.get("base_url") or os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")).rstrip("/")
        mdl = p.get("model") or os.getenv("OLLAMA_MODEL", "llama3")
        key = os.getenv(p["api_key_env"]) if p.get("api_key_env") else None
    return {"name": pname, "provider": prov, "base_url": base, "model": mdl, "api_key": key,
            "max_tokens": str(p.get("max_tokens") or "keep").lower(),
            "reasoning_effort": p.get("reasoning_effort") or None,
            "num_ctx": int(p.get("num_ctx") or os.getenv("OLLAMA_NUM_CTX", "8192")),
            "keep_alive": str(p.get("keep_alive") or os.getenv("OLLAMA_KEEP_ALIVE", "10m")),
            "max_concurrency": max(1, int(p.get("max_concurrency") or 2))}


# ── who uses which profile ───────────────────────────────────────────────────────────────────────────────────────────
# char_id -> profile name, as last worked out for that character (resolve_character, on the simulation core) or handed
# over with a request (load_assignments, on a worker -- workers have no world to look in).

_assign = {}


def resolve_character(c):
    """Which profile this character uses (their own choice, then the file's assign map, then the default); noted for
    their calls. Cheap -- called for every character every tick."""
    if not c or not c.get("id"):
        return default_name()
    pname = c.get("llm_profile")
    if not (pname and _known(pname)):
        pname = None
        cfg = config()
        a = (cfg or {}).get("assign") or {}
        chars = a.get("characters") or {}
        pname = chars.get(c["id"]) or chars.get(c.get("name") or "")
        if not pname:
            surname = (c.get("surname") or (c.get("name") or "").split(" ")[-1] or "").strip()
            pname = (a.get("surnames") or {}).get(surname)
        if not (pname and _known(pname)):
            pname = default_name()
    _assign[c["id"]] = pname
    return pname


def assign(char_id, profile_name):
    if char_id:
        _assign[char_id] = profile_name


def assignments():
    return dict(_assign)


def load_assignments(mapping):
    """On a worker: the core's char -> profile map that came with a request."""
    if isinstance(mapping, dict):
        _assign.update({k: v for k, v in mapping.items() if isinstance(k, str) and isinstance(v, str)})


def profile_for(char_id=None):
    if not char_id:
        return background_name()
    pname = _assign.get(char_id)
    return pname if pname and _known(pname) else default_name()


# ── the old single-provider API, now per profile (no argument: the default profile) ──────────────────────────────────

def name(profile=None):
    return settings(profile)["provider"]


def label(profile=None):
    """How the provider is named to people (the status light, error lines)."""
    s = settings(profile)
    if s["provider"] != "openai":
        return "Ollama"
    for host, nice in (("api.openai.com", "OpenAI"), ("googleapis.com", "Gemini"), ("anthropic.com", "Anthropic"),
                       ("openrouter.ai", "OpenRouter"), ("groq.com", "Groq")):
        if host in s["base_url"]:
            return nice
    return "Model API"


def base_url(profile=None):
    return settings(profile)["base_url"]


def model(profile=None):
    return settings(profile)["model"]


def _headers(s):
    return {"Authorization": f"Bearer {s['api_key']}"} if s.get("api_key") else {}


def chat_request(messages, max_tokens=None, profile=None):
    """(url, json body, headers) for one chat call -- built apart from sending it, so it can be checked."""
    s = settings(profile)
    if s["provider"] == "openai":
        body = {"model": s["model"], "messages": messages}
        if max_tokens and s["max_tokens"] != "off":
            # OpenAI's own API wants max_completion_tokens (newer models refuse max_tokens); the compatible services
            # take max_tokens
            body["max_completion_tokens" if "api.openai.com" in s["base_url"] else "max_tokens"] = int(max_tokens)
        if s["reasoning_effort"]:
            body["reasoning_effort"] = s["reasoning_effort"]
        return f"{s['base_url']}/chat/completions", body, _headers(s)
    # Ollama defaults num_ctx to whatever the model's Modelfile specifies (measured 4096 for the llama3.1 instance this
    # backend talks to -- close to a real character context, risking silent truncation) and keep_alive to 5m, which
    # can cold-reload the model (~20-40s) between ticks on a quiet character. Both are explicit and tunable.
    body = {"model": s["model"], "messages": messages, "stream": False,
            "keep_alive": s["keep_alive"],
            "options": {"num_ctx": s["num_ctx"],
                        # a cap on the reply, when the caller wants one (the decision reply is a few short lines; on a
                        # slow server every token it is left to ramble on for is seconds of waiting)
                        **({"num_predict": int(max_tokens)} if max_tokens else {})}}
    return f"{s['base_url']}/api/chat", body, _headers(s)


def reply_text(data, profile=None):
    """The reply's text out of the provider's response body (either shape)."""
    if "choices" in data or (name(profile) == "openai" and "message" not in data):
        choices = data.get("choices") or []
        content = ((choices[0] if choices else {}).get("message") or {}).get("content")
        if isinstance(content, list):                  # some services return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content or ""
    return (data.get("message") or {}).get("content", "")


# What the service said about the last call in this task -- tokens, model, its own timings -- for the LLM log
# (llm/llm_client.py reads it right after chat() returns; an awaited coroutine shares its caller's context).
last_meta = contextvars.ContextVar("llm_last_meta", default=None)


def usage_meta(data, profile=None, max_tokens=None):
    """Token counts and timings out of a response body (Ollama's or the OpenAI shape), plus the model and profile."""
    s = settings(profile)
    meta = {"model": data.get("model") or s["model"], "profile": s["name"], "provider": s["provider"],
            "max_tokens": max_tokens}
    u = data.get("usage") or {}
    if u:
        meta.update(prompt_tokens=u.get("prompt_tokens"), completion_tokens=u.get("completion_tokens"),
                    total_tokens=u.get("total_tokens"))
    if "prompt_eval_count" in data or "eval_count" in data:       # Ollama
        ns = 1e9
        meta.update(prompt_tokens=data.get("prompt_eval_count"), completion_tokens=data.get("eval_count"),
                    load_s=round((data.get("load_duration") or 0) / ns, 3),
                    prompt_eval_s=round((data.get("prompt_eval_duration") or 0) / ns, 3),
                    eval_s=round((data.get("eval_duration") or 0) / ns, 3),
                    done_reason=data.get("done_reason"))
    choices = data.get("choices") or []
    if choices and choices[0].get("finish_reason"):
        meta["done_reason"] = choices[0]["finish_reason"]
    if s["provider"] != "openai":
        meta["num_ctx"] = s["num_ctx"]
    return meta


async def chat(messages, timeout=60.0, max_tokens=None, profile=None):
    url, body, headers = chat_request(messages, max_tokens, profile)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        try:
            last_meta.set(usage_meta(data, profile, max_tokens))
        except Exception:                                   # noqa: BLE001 -- telemetry never breaks a call
            last_meta.set(None)
        return reply_text(data, profile)


def status(timeout=3.0, profile=None):
    """Is the model service up, and does it have the configured model? For the status light (api/debug.py).
    state: "up" (answered, model available) / "degraded" (answered, model not listed) / "down" (no answer, or refused)."""
    s = settings(profile)
    base, mdl = s["base_url"], s["model"]
    out = {"profile": s["name"], "provider": s["provider"], "provider_label": label(profile), "base_url": base,
           "model": mdl, "checked_at": time.time(), "error": None}
    try:
        started = time.monotonic()
        with httpx.Client(timeout=timeout) as client:
            if s["provider"] == "openai":
                if not _headers(s) and "api.openai.com" in base:
                    out.update(state="down", error="no API key: set LLM_API_KEY (or OPENAI_API_KEY)"
                               if s["name"] == ENV_PROFILE else f"no API key for profile {s['name']!r}")
                    return out
                resp = client.get(f"{base}/models", headers=_headers(s))
                resp.raise_for_status()
                out["latency_ms"] = round((time.monotonic() - started) * 1000)
                listed = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
                # Gemini lists "models/gemini-..."; a service that lists nothing is taken at its word that it serves it
                out["model_available"] = not listed or any(i == mdl or (i or "").endswith("/" + mdl) for i in listed)
                out["loaded"] = None
            else:
                tags = client.get(f"{base}/api/tags", headers=_headers(s))
                tags.raise_for_status()
                out["latency_ms"] = round((time.monotonic() - started) * 1000)
                installed = [m.get("name") or m.get("model") for m in tags.json().get("models", [])]
                try:
                    ps = client.get(f"{base}/api/ps", headers=_headers(s))
                    ps.raise_for_status()
                    out["loaded"] = [m.get("name") or m.get("model") for m in ps.json().get("models", [])]
                except (httpx.HTTPError, ValueError):
                    out["loaded"] = None      # older Ollama without /api/ps -- not a reason to call it down
                wanted = {mdl, mdl if ":" in mdl else f"{mdl}:latest"}   # "llama3" and "llama3:latest" are one model
                out["model_available"] = any(n in wanted for n in installed)
        out["state"] = "up" if out["model_available"] else "degraded"
        if not out["model_available"]:
            out["error"] = f"model '{mdl}' is not available on this {label(profile)} server"
    except httpx.TimeoutException:
        out.update(state="down", error=f"no answer within {timeout:g} s")
    except httpx.HTTPStatusError as exc:
        why = {401: "the API key was refused", 403: "the API key isn't allowed this"}.get(exc.response.status_code)
        out.update(state="down", error=why or f"http {exc.response.status_code}")
    except (httpx.HTTPError, ValueError) as exc:
        out.update(state="down", error=f"{type(exc).__name__}: {exc}"[:200])
    return out


def status_all(timeout=3.0):
    """status() for every profile, plus who is on which."""
    who = {}
    for cid, pname in _assign.items():
        who.setdefault(pname, []).append(cid)
    return {"default": default_name(), "background": background_name(), "from_file": config() is not None,
            "profiles": [{**status(timeout, n), "characters": who.get(n, []),
                          "max_concurrency": settings(n)["max_concurrency"]} for n in profile_names()]}
