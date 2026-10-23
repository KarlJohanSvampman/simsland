"""
systems/bg_llm.py

Fire-and-collect LLM work that must not be lost.

The world is re-read from Redis as fresh JSON every tick, and an agent
thread that overruns sim_loop.AGENT_WAIT_BUDGET_SECONDS keeps running
against a copy that's already been persisted and discarded -- so any state
an LLM call writes from inside a slow agent thread is silently lost. That's
fine for pure flavor, wrong for anything that changes character state.

So: the model call runs on a worker thread that touches NO world state, its
plain-data result goes into a process-local mailbox, and a later tick takes
it and applies it to whatever the current world object is. The caller keeps
the *request* in its own persisted state until the result is applied, so a
restart (mailbox lost) just re-submits it.

    bg_llm.submit(key, fn, *args)   # no-op if key already pending/ready
    ready, value = bg_llm.take(key) # (False, None) until the call finishes

`fn` must be a plain function returning plain data; it must not read or
mutate the world.

WHERE the call runs (BG_LLM_MODE, default COGNITION_MODE, default "auto"): on this process's two
pool threads (local), or -- for the functions in REMOTE_TASKS, whose arguments and results are plain
JSON -- on a bg_llm worker container over a Redis stream (workers/bg_llm.py) while at least one is
alive (remote / auto). Every submission carries a token: a result whose token isn't the current one
(the call was re-submitted, or fell back to running here because no worker answered) is ignored, so
a late duplicate can never be taken as the answer to a newer request.
"""

import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from core.work_queue import WorkQueue

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg_llm")
_lock = threading.Lock()
_inflight = {}   # key -> {"t": submitted_at, "token": str, "remote": bool, "fn": fn, "args": args}
_done = {}       # key -> result (None if fn raised)
_token_seq = 0

# An in-flight entry this old is assumed lost (hung worker) and may be re-submitted.
INFLIGHT_STALE_SECONDS = 300.0

MODE = os.getenv("BG_LLM_MODE", os.getenv("COGNITION_MODE", "auto")).lower()
REMOTE_FALLBACK_SECONDS = 20.0
queue = WorkQueue("bgllm")
_reader = None

# "module:function" -> index of the argument that names the character the call is about (its
# prompt-log entries are shipped back under that id), or None. Only these may run on a worker:
# each is a pure model call -- plain arguments in, plain data out, no world state.
REMOTE_TASKS = {
    "llm.behavior_theory:theory_from_prompt": 2,
    "llm.account_agreement:accounts_agree": None,
    "llm.child_imagination:imagine_explanation": None,
    "llm.household_summary_narration:narrate_blocking": None,
    "llm.self_assessment:assess": None,
}


def task_name(fn):
    return f"{getattr(fn, '__module__', '')}:{getattr(fn, '__name__', '')}"


def _next_token():
    global _token_seq
    _token_seq += 1
    return f"{os.getpid()}-{_token_seq}"


def submit(key, fn, *args):
    """Queue fn(*args). Returns True if newly queued, False if `key` is already pending or waiting to be taken."""
    now = time.time()
    with _lock:
        entry = _inflight.get(key)
        if key in _done or (entry is not None and now - entry["t"] < INFLIGHT_STALE_SECONDS):
            return False
        entry = _inflight[key] = {"t": now, "token": _next_token(), "remote": False, "fn": fn, "args": args}
    if not _send_remote(key, entry):
        _run_local(key, entry)
    return True


def _run_local(key, entry):
    token, fn, args = entry["token"], entry["fn"], entry["args"]

    def _run():
        try:
            result = fn(*args)
        except Exception:
            traceback.print_exc()
            result = None
        _finish(key, token, result)

    _pool.submit(_run)


def _finish(key, token, result):
    with _lock:
        current = _inflight.get(key)
        if current is None or current["token"] != token:
            return                                   # superseded: a newer submission owns this key
        del _inflight[key]
        _done[key] = result


def take(key):
    """(True, result) once, then the entry is gone; (False, None) if not finished."""
    with _lock:
        if key in _done:
            return True, _done.pop(key)
    return False, None


def is_pending(key):
    with _lock:
        return key in _inflight or key in _done


# ---------------------------------------------------------------------------
# remote path
# ---------------------------------------------------------------------------

def _use_remote():
    if MODE == "local":
        return False
    if MODE == "remote":
        return True
    try:
        return queue.workers_alive() > 0
    except Exception:
        return False


def _send_remote(key, entry):
    name = task_name(entry["fn"])
    if name not in REMOTE_TASKS or not _use_remote():
        return False
    try:
        args = list(entry["args"])
        json.dumps(args)                              # plain data only; anything else runs here
        _ensure_reader()                              # listening before the request exists
        entry["remote"] = True
        queue.enqueue({"key": key, "token": entry["token"], "task": name, "args": args,
                       "deadline": time.time() + INFLIGHT_STALE_SECONDS})
        return True
    except Exception as exc:
        entry["remote"] = False
        print(f"[bg_llm] could not queue {key} remotely ({exc!r}); running it here")
        return False


def _ensure_reader():
    global _reader
    with _lock:
        if _reader is not None and _reader.is_alive():
            return
    reader = queue.start_reader(_accept_result, _fallback_stranded, label="bg_llm")
    with _lock:
        _reader = reader


def _accept_result(res):
    value = None if res.get("error") else res.get("value")
    if res.get("error"):
        print(f"[bg_llm] worker {res.get('worker')} failed {res.get('key')}: {res['error']}")
    if res.get("prompt_log"):
        try:
            from llm import llm_client
            for cid, entries in res["prompt_log"].items():
                for e in reversed(entries):
                    llm_client.add_prompt_entry(cid, e)
        except Exception as exc:
            print(f"[bg_llm] could not merge worker prompt log: {exc!r}")
    _finish(res.get("key"), res.get("token"), value)


def _fallback_stranded():
    """A remote call nobody has answered for a while, with no worker alive: run it here instead."""
    now = time.time()
    with _lock:
        old = [(k, e) for k, e in _inflight.items() if e["remote"] and now - e["t"] > REMOTE_FALLBACK_SECONDS]
    if not old:
        return
    queue.forget_alive_cache()
    if queue.workers_alive() > 0:
        return
    for key, e in old:
        with _lock:
            if _inflight.get(key) is not e:
                continue
            e["remote"] = False
            e["token"] = _next_token()                # a late answer from the wire is now stale
        print(f"[bg_llm] no worker answered {key} -- running it here")
        _run_local(key, e)
