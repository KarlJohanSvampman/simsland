"""
workers/cognition.py -- a cognition worker: `python -m workers.cognition`

Takes decision requests off the Redis stream (core/cognition_queue.py), runs the model round-trip
(brain.llm_brain.think -- prompt building, the LLM call, parsing, the speech follow-up) and publishes
the decision back. It holds no world state and needs no database: the request carries the character's
context and recent turns, the result carries the decision, the prompt-log entries and the prompt size
so the core's debug views keep working.

Scale it with `docker compose up --scale cognition=N`. Each worker runs COGNITION_WORKER_THREADS
concurrent requests; the Ollama concurrency cap (OLLAMA_MAX_CONCURRENCY) applies per worker process.
"""

import os
import threading
import time
import traceback

from core import cognition_queue as q
from workers.common import Runtime

THREADS = int(os.getenv("COGNITION_WORKER_THREADS", "8"))

_local = threading.local()


def _patch_prompt_bytes():
    """think() reports the prompt size to a process-local gauge; capture it per request instead."""
    import brain.cognition_scheduler as cs
    original = cs.record_prompt_bytes

    def capture(n):
        _local.prompt_bytes = getattr(_local, "prompt_bytes", 0) + n
        original(n)
    cs.record_prompt_bytes = capture


def run_request(req):
    """The model round-trip for one request -> result dict. Never raises."""
    from brain.llm_brain import think
    from llm import llm_client
    _local.prompt_bytes = 0
    started = time.time()
    decision, error = None, None
    try:
        decision = think(req["context"], char_id=req["char_id"], session=req.get("session"),
                         priority=req.get("priority"))
    except Exception as exc:
        error = repr(exc)
        traceback.print_exc()
    log = [e for e in llm_client.get_prompt_log(req["char_id"]) if e.get("ts", 0) >= started]
    return {
        "req_id": req["req_id"], "char_id": req["char_id"], "tick": req.get("tick"),
        "decision": decision, "error": error, "prompt_bytes": getattr(_local, "prompt_bytes", 0),
        "prompt_log": log, "elapsed": round(time.time() - started, 3), "worker": runtime.worker_id,
    }


runtime = Runtime("cognition-worker", q.queue, run_request, THREADS)


def main():
    _patch_prompt_bytes()
    runtime.main()


if __name__ == "__main__":
    main()
