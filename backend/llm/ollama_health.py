"""
llm/ollama_health.py -- is Ollama up, and has it been answering?

Two kinds of evidence:

  passive  every real model call (llm/llm_client.py::_call_llm) records its outcome here: when the last reply came
           back, how long it took, and the last failure. Kept in Redis so the core and the cognition / bg_llm worker
           processes all report into the same place.
  active   probe() asks the server directly (GET /api/tags): is it reachable, how fast, which models it has, and is
           the configured model among them.

Read both with GET /admin/ollama_status (or scripts/check_ollama.sh from the host).
"""

import os
import socket
import time

import httpx

_KEY = "ollama:health"
_PROC = f"{socket.gethostname()}:{os.getpid()}"

# a reply within this many seconds counts as "Ollama has been responding"
RECENT_SECONDS = int(os.getenv("OLLAMA_HEALTH_RECENT_SECONDS", "300"))


def base_url():
    return os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")


def model_name():
    return os.getenv("OLLAMA_MODEL", "llama3")


def _redis():
    from llm.llm_client import r
    return r


def record_success(elapsed):
    """A model call came back. Never raises: health bookkeeping must not break a real call."""
    try:
        now = time.time()
        pipe = _redis().pipeline()
        pipe.hset(_KEY, mapping={"last_ok": now, "last_ok_seconds": round(elapsed, 2), "last_ok_process": _PROC})
        pipe.hincrby(_KEY, "ok_count", 1)
        pipe.hset(_KEY, "consecutive_failures", 0)
        pipe.execute()
    except Exception:
        pass


def record_failure(error, elapsed):
    try:
        now = time.time()
        pipe = _redis().pipeline()
        pipe.hset(_KEY, mapping={"last_error": now, "last_error_seconds": round(elapsed, 2),
                                 "last_error_text": f"{type(error).__name__}: {error}"[:500],
                                 "last_error_process": _PROC})
        pipe.hincrby(_KEY, "error_count", 1)
        pipe.hincrby(_KEY, "consecutive_failures", 1)
        pipe.execute()
    except Exception:
        pass


def recorded():
    """What the model calls have reported (empty when Redis is unreachable or nothing has been called yet)."""
    try:
        raw = _redis().hgetall(_KEY) or {}
    except Exception as e:
        return {"redis_error": str(e)}
    now = time.time()
    out = {}
    for k, v in raw.items():
        try:
            out[k] = float(v) if k not in ("last_error_text", "last_ok_process", "last_error_process") else v
        except ValueError:
            out[k] = v
    for k in ("ok_count", "error_count", "consecutive_failures"):
        if k in out:
            out[k] = int(out[k])
    if out.get("last_ok"):
        out["last_ok_ago_seconds"] = round(now - out["last_ok"], 1)
    if out.get("last_error"):
        out["last_error_ago_seconds"] = round(now - out["last_error"], 1)
    return out


def probe(timeout=5.0):
    """Ask the server itself. Returns {"reachable", "latency_ms", "models", "model_available", "error"?}."""
    url = base_url()
    t0 = time.time()
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=timeout)
        resp.raise_for_status()
        models = [m.get("name") for m in (resp.json().get("models") or [])]
        want = model_name()
        available = want in models or (":" not in want and any(m.split(":")[0] == want for m in models))
        return {"reachable": True, "latency_ms": round((time.time() - t0) * 1000), "models": models,
                "model_available": available}
    except Exception as e:
        return {"reachable": False, "latency_ms": round((time.time() - t0) * 1000),
                "error": f"{type(e).__name__}: {e}"}


def status(do_probe=True):
    """The full picture, with a one-word verdict:
       up        the server answers the probe and has the configured model
       degraded  it answers, but the configured model is missing, or recent calls are failing
       down      the probe cannot reach it
       unknown   not probed and no call has been recorded"""
    rec = recorded()
    out = {"base_url": base_url(), "model": model_name(), "recorded": rec}
    recent_ok = rec.get("last_ok_ago_seconds") is not None and rec["last_ok_ago_seconds"] <= RECENT_SECONDS
    out["responding_recently"] = recent_ok
    failing = rec.get("consecutive_failures", 0) >= 3
    if do_probe:
        p = probe()
        out["probe"] = p
        if not p["reachable"]:
            out["status"] = "down"
        elif not p["model_available"] or failing:
            out["status"] = "degraded"
        else:
            out["status"] = "up"
    else:
        out["status"] = "degraded" if failing else ("up" if recent_ok else "unknown")
    return out
