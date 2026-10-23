"""
workers/bg_llm.py -- a background-LLM worker: `python -m workers.bg_llm`

Runs the one-off model calls the simulation fires and collects later (behaviour theories, child
imagination, account comparisons, household-summary narration, self-assessments -- the functions
listed in systems/bg_llm.py::REMOTE_TASKS). A request names the function and carries its plain
arguments; the result is its plain return value. No world state, no database. Only functions on the
REMOTE_TASKS allow-list can be named.

Scale it with `docker compose up --scale bg_llm=N`.
"""

import importlib
import os
import time
import traceback

from systems.bg_llm import REMOTE_TASKS, queue
from workers.common import Runtime

THREADS = int(os.getenv("BG_LLM_WORKER_THREADS", "4"))


def run_request(req):
    """One background call -> result dict. Never raises."""
    started = time.time()
    value, error, log = None, None, {}
    name = req.get("task")
    try:
        if name not in REMOTE_TASKS:
            raise ValueError(f"task {name!r} is not allowed on a worker")
        module, func = name.split(":")
        args = req.get("args") or []
        value = getattr(importlib.import_module(module), func)(*args)
        char_index = REMOTE_TASKS[name]
        if char_index is not None and len(args) > char_index and args[char_index]:
            from llm import llm_client
            cid = args[char_index]
            entries = [e for e in llm_client.get_prompt_log(cid) if e.get("ts", 0) >= started]
            if entries:
                log[cid] = entries
    except Exception as exc:
        error = repr(exc)
        traceback.print_exc()
    return {"key": req.get("key"), "token": req.get("token"), "value": value, "error": error,
            "prompt_log": log, "elapsed": round(time.time() - started, 3), "worker": runtime.worker_id}


runtime = Runtime("bg-llm-worker", queue, run_request, THREADS)


def main():
    runtime.main()


if __name__ == "__main__":
    main()
