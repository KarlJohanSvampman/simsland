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
"""

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg_llm")
_lock = threading.Lock()
_inflight = {}   # key -> submitted_at
_done = {}       # key -> result (None if fn raised)

# An in-flight entry this old is assumed lost (hung worker) and may be re-submitted.
INFLIGHT_STALE_SECONDS = 300.0


def submit(key, fn, *args):
    """Queue fn(*args). Returns True if newly queued, False if `key` is already pending or waiting to be taken."""
    now = time.time()
    with _lock:
        started = _inflight.get(key)
        if key in _done or (started is not None and now - started < INFLIGHT_STALE_SECONDS):
            return False
        _inflight[key] = now

    def _run():
        try:
            result = fn(*args)
        except Exception:
            traceback.print_exc()
            result = None
        with _lock:
            _inflight.pop(key, None)
            _done[key] = result

    _pool.submit(_run)
    return True


def take(key):
    """(True, result) once, then the entry is gone; (False, None) if not finished."""
    with _lock:
        if key in _done:
            return True, _done.pop(key)
    return False, None


def is_pending(key):
    with _lock:
        return key in _inflight or key in _done
