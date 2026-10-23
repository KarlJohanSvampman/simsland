"""
workers/cognition.py -- a cognition worker: `python -m workers.cognition`

Takes decision requests off the Redis stream (core/cognition_queue.py), runs the model round-trip
(brain.llm_brain.think -- prompt building, the LLM call, parsing, the speech follow-up) and publishes
the decision back. It holds no world state and needs no database: the request carries the character's
context and recent turns, the result carries the decision, the prompt-log entries and the prompt size
so the core's debug views keep working.

Scale it with `docker compose up --scale cognition=N`. Each worker runs WORKER_THREADS concurrent
requests; the Ollama concurrency cap (OLLAMA_MAX_CONCURRENCY) applies per worker process.
"""

import os
import signal
import threading
import time
import traceback

from core import cognition_queue as q

THREADS = int(os.getenv("COGNITION_WORKER_THREADS", "8"))
HEARTBEAT_SECONDS = 3.0

_stop = threading.Event()
_local = threading.local()
_stats = {"done": 0, "dropped": 0, "failed": 0, "busy": 0}
_stats_lock = threading.Lock()


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
        "prompt_log": log, "elapsed": round(time.time() - started, 3), "worker": WORKER_ID,
    }


def _loop():
    while not _stop.is_set():
        try:
            got = q.claim(WORKER_ID, block_ms=2000)
        except Exception as exc:
            print(f"[cognition-worker] queue error: {exc!r}")
            _stop.wait(2.0)
            continue
        if not got:
            continue
        stream_id, req = got
        if req.get("deadline") and time.time() > req["deadline"]:
            with _stats_lock:
                _stats["dropped"] += 1
            q.complete(stream_id)                 # nobody is waiting for this any more
            continue
        with _stats_lock:
            _stats["busy"] += 1
        try:
            result = run_request(req)
        finally:
            with _stats_lock:
                _stats["busy"] -= 1
        with _stats_lock:
            _stats["failed" if result["error"] else "done"] += 1
        try:
            q.complete(stream_id, result)
        except Exception as exc:
            print(f"[cognition-worker] could not publish {req.get('req_id')}: {exc!r}")


def _heartbeat():
    while not _stop.is_set():
        try:
            with _stats_lock:
                info = dict(_stats, threads=THREADS, t=time.time())
            q.heartbeat(WORKER_ID, info)
        except Exception as exc:
            print(f"[cognition-worker] heartbeat failed: {exc!r}")
        _stop.wait(HEARTBEAT_SECONDS)


WORKER_ID = q.new_worker_id()


def main():
    print(f"[cognition-worker] {WORKER_ID} starting with {THREADS} threads")
    _patch_prompt_bytes()
    q.ensure_group()
    signal.signal(signal.SIGTERM, lambda *a: _stop.set())
    threading.Thread(target=_heartbeat, daemon=True, name="heartbeat").start()
    threads = [threading.Thread(target=_loop, daemon=True, name=f"cognition-{i}") for i in range(THREADS)]
    for t in threads:
        t.start()
    try:
        while not _stop.is_set():
            _stop.wait(1.0)
    except KeyboardInterrupt:
        _stop.set()
    q.goodbye(WORKER_ID)
    # let in-flight requests finish and publish (bounded)
    deadline = time.time() + 60
    for t in threads:
        t.join(timeout=max(0.1, deadline - time.time()))
    print(f"[cognition-worker] {WORKER_ID} stopped")


if __name__ == "__main__":
    main()
