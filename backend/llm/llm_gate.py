"""
llm/llm_gate.py

Bounds how many LLM requests are ever in flight to Ollama at once, regardless
of which thread they originate from -- AND, since OLLAMA_MAX_CONCURRENCY
dropped from 2 to 1 (strict single-flight), makes sure an urgent character
decision never has to sit behind a slow, unimportant background call.

Before this existed, character decisions went straight from sim_loop.py's
8-worker agent ThreadPoolExecutor to asyncio.run(call_llm_safe(...)) inside
each worker thread -- up to 8 independent, uncoordinated HTTP calls to the
same remote Ollama instance every tick. A separate single-consumer queue
(llm_queue.py) existed and would have serialized calls, but it was only ever
wired into the social-interpretation path (llm/cognition_jobs.py), not the
main per-tick think() loop.

This module runs one dedicated background thread with its own asyncio event
loop and a heapq-backed PRIORITY queue (previously a plain asyncio.Semaphore
-- fine when several calls could run at once, but with OLLAMA_MAX_CONCURRENCY
now 1, a FIFO-only queue meant a submitted-first background call could block
an urgent one for its whole duration). Every caller -- regardless of which
thread it's on -- submits its coroutine here with a priority and blocks until
it completes. Higher-priority arrivals jump ahead of lower-priority ones
still WAITING; if something already RUNNING is strictly less urgent than a
brand-new arrival, it gets cancelled outright to let the urgent one through
immediately rather than finish out its turn.

An aborted call never raises to its caller -- it resolves with the exact
same {"error": ...} shape call_llm_safe() already returns for a timeout or
network failure, which every existing caller already falls back on
gracefully. This is what makes preemption safe to add with zero changes to
any of the ~15+ existing call sites that don't explicitly pass a priority
(they default to PRIORITY_NORMAL and behave exactly as before).

OLLAMA_MAX_CONCURRENCY defaults conservatively (2, though this deployment
currently runs it at 1 -- see docker-compose.yml). The right value depends
on what the remote Ollama box can actually run in parallel (GPU memory,
OLLAMA_NUM_PARALLEL on the server side) -- that's host-side configuration
this repo can't see or control, so it's exposed as an env var to tune from
outside rather than guessed further here. Raising it back above 1 still
works with this dispatcher unchanged -- it just runs that many tasks
concurrently instead of one.
"""

import asyncio
import heapq
import itertools
import os
import threading

OLLAMA_MAX_CONCURRENCY = int(os.getenv("OLLAMA_MAX_CONCURRENCY", "2"))

# Discrete tiers, not a continuous score -- avoids two similarly-important
# calls constantly preempting each other over marginal differences. Only a
# STRICTLY more urgent tier preempts; same-tier arrivals just queue FIFO.
PRIORITY_URGENT     = 0   # a character in a survival/health situation, or mid-conversation
PRIORITY_NORMAL     = 1   # the default -- routine character decisions, anything unclassified
PRIORITY_BACKGROUND = 2   # one-off flavor/content generation (diary entries, item content, ...)

_ABORTED_ERROR = {"error": "aborted: preempted by a higher-priority request"}

_loop = asyncio.new_event_loop()
_counter = itertools.count()
_heap: list = []             # [(priority, seq, coro, future), ...] -- a min-heap
_running: list = []          # [(priority, task), ...] -- currently executing, len <= OLLAMA_MAX_CONCURRENCY
_wakeup: asyncio.Event | None = None  # created on _loop's own thread, see _run_loop


async def _dispatcher():
    """One of OLLAMA_MAX_CONCURRENCY identical workers -- pops the single
    highest-priority queued entry, runs it as a cancellable task, and
    resolves that entry's future on completion, failure, or cancellation.
    Never lets a CancelledError escape to the caller (see _ABORTED_ERROR)."""
    while True:
        if not _heap:
            await _wakeup.wait()
            _wakeup.clear()
            continue

        priority, _seq, coro, fut = heapq.heappop(_heap)
        if fut.done():
            continue  # caller already gave up (e.g. its own timeout fired first)

        task = asyncio.ensure_future(coro)
        slot = (priority, task)
        _running.append(slot)
        try:
            result = await task
            if not fut.done():
                fut.set_result(result)
        except asyncio.CancelledError:
            if not fut.done():
                fut.set_result(_ABORTED_ERROR)
        except Exception as e:
            if not fut.done():
                fut.set_result({"error": str(e)})
        finally:
            _running.remove(slot)


def _enqueue(coro, priority):
    """Runs on _loop's own thread (called from within a coroutine already
    scheduled there via run_coroutine_threadsafe) -- heapq/list mutations
    here need no separate lock."""
    fut = _loop.create_future()
    heapq.heappush(_heap, (priority, next(_counter), coro, fut))

    # Preempt the single least-urgent running task if it's strictly less
    # urgent than this new arrival -- e.g. a background item-content call
    # already in flight gets cancelled the moment a survival-critical
    # character decision shows up, rather than making it wait its turn.
    if _running:
        worst_priority, worst_task = max(_running, key=lambda s: s[0])
        if priority < worst_priority:
            worst_task.cancel()

    _wakeup.set()
    return fut


async def _submit_and_await(coro, priority):
    fut = _enqueue(coro, priority)
    return await fut


def _run_loop():
    global _wakeup
    asyncio.set_event_loop(_loop)
    _wakeup = asyncio.Event()
    for _ in range(OLLAMA_MAX_CONCURRENCY):
        _loop.create_task(_dispatcher())
    _loop.run_forever()


_thread = threading.Thread(target=_run_loop, name="llm-gate", daemon=True)
_thread.start()


def run_llm_call(coro, priority=PRIORITY_NORMAL):
    """Submit an awaitable (e.g. call_llm_safe(...)) to the gate's event
    loop and block the calling thread until it completes (or is aborted
    for a higher-priority arrival -- see module docstring), bounded by
    OLLAMA_MAX_CONCURRENCY concurrent in-flight calls across all callers."""
    future = asyncio.run_coroutine_threadsafe(_submit_and_await(coro, priority), _loop)
    return future.result()


async def run_llm_call_async(coro, priority=PRIORITY_NORMAL):
    """Async equivalent of run_llm_call, for callers already inside an
    event loop (e.g. cognition_jobs.py) -- schedules onto the gate's loop
    and awaits the result without blocking the caller's own loop thread."""
    future = asyncio.run_coroutine_threadsafe(_submit_and_await(coro, priority), _loop)
    return await asyncio.wrap_future(future)
