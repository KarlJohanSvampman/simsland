"""
llm/llm_gate.py

Bounds how many LLM requests are ever in flight to Ollama at once, regardless
of which thread they originate from.

Before this existed, character decisions went straight from sim_loop.py's
8-worker agent ThreadPoolExecutor to asyncio.run(call_llm_safe(...)) inside
each worker thread — up to 8 independent, uncoordinated HTTP calls to the
same remote Ollama instance every tick. A separate single-consumer queue
(llm_queue.py) existed and would have serialized calls, but it was only ever
wired into the social-interpretation path (llm/cognition_jobs.py), not the
main per-tick think() loop.

This module runs one dedicated background thread with its own asyncio event
loop and a single asyncio.Semaphore. Every caller — regardless of which
thread it's on — submits its coroutine here and blocks until the coroutine
completes, but the semaphore ensures only OLLAMA_MAX_CONCURRENCY of them are
actually executing (i.e. actually holding an open HTTP request to Ollama) at
once. This deliberately replaces llm_queue.py's queue-of-one for the
character decision loop and consolidates all Ollama callers onto one shared
budget, rather than having two independent concurrency mechanisms in the
same codebase.

OLLAMA_MAX_CONCURRENCY defaults conservatively (2). The right value depends
on what the remote Ollama box can actually run in parallel (GPU memory,
OLLAMA_NUM_PARALLEL on the server side) — that's host-side configuration
this repo can't see or control, so it's exposed as an env var to tune from
outside rather than guessed further here.
"""

import asyncio
import os
import threading

OLLAMA_MAX_CONCURRENCY = int(os.getenv("OLLAMA_MAX_CONCURRENCY", "2"))

_loop = asyncio.new_event_loop()
_sem = asyncio.Semaphore(OLLAMA_MAX_CONCURRENCY)


def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


_thread = threading.Thread(target=_run_loop, name="llm-gate", daemon=True)
_thread.start()


async def _bounded(coro):
    async with _sem:
        return await coro


def run_llm_call(coro):
    """Submit an awaitable (e.g. call_llm_safe(...)) to the gate's event
    loop and block the calling thread until it completes, bounded by
    OLLAMA_MAX_CONCURRENCY concurrent in-flight calls across all callers."""
    future = asyncio.run_coroutine_threadsafe(_bounded(coro), _loop)
    return future.result()


async def run_llm_call_async(coro):
    """Async equivalent of run_llm_call, for callers already inside an
    event loop (e.g. cognition_jobs.py) — schedules onto the gate's loop
    and awaits the result without blocking the caller's own loop thread."""
    future = asyncio.run_coroutine_threadsafe(_bounded(coro), _loop)
    return await asyncio.wrap_future(future)
