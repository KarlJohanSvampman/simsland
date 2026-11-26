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
import concurrent.futures
import heapq
import itertools
import os
import threading
import time

OLLAMA_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY") or os.getenv("OLLAMA_MAX_CONCURRENCY", "2"))

# Discrete tiers, not a continuous score -- avoids two similarly-important
# calls constantly preempting each other over marginal differences. Only a
# STRICTLY more urgent tier preempts; same-tier arrivals just queue FIFO.
PRIORITY_URGENT     = 0   # a character in a survival/health situation, or mid-conversation
PRIORITY_NORMAL     = 1   # the default -- routine character decisions, anything unclassified
PRIORITY_BACKGROUND = 2   # one-off flavor/content generation (diary entries, item content, ...)

_ABORTED_ERROR = {"error": "aborted: preempted by a higher-priority request"}
_TIMEOUT_ERROR = {"error": "timeout: gave up waiting for the model (queued behind other calls, or it never answered)"}

# Hard ceiling on how long ANY caller thread may block in run_llm_call (queue
# wait + the call itself). Without one, a slow/unreachable Ollama leaves the
# calling thread parked forever -- for a character decision that thread holds a
# whole world copy, and abandoned decisions piled up until the container ran
# out of memory. On expiry the call is cancelled (dropped from the queue, or
# the running request cancelled) and the caller gets the usual {"error": ...}.
# a character's decision on a modest server takes a minute or more (reading ~1.5k tokens, then writing the reply at a few tokens
# a second): 90 seconds abandoned most of them, and an abandoned decision is simply asked for again
LLM_CALL_MAX_WAIT_SECONDS = float(os.getenv("LLM_CALL_MAX_WAIT_SECONDS", "170"))

_loop = asyncio.new_event_loop()
_counter = itertools.count()
_wakeup_ready = threading.Event()


# One lane per model profile (llm/provider.py): its own queue, its own running set and its own number of dispatchers
# (the profile's max_concurrency), so a slow local server never holds up characters on a hosted API. Preemption is
# within a lane. Lanes are made on first use; with no profiles file there is one, "env", sized OLLAMA_MAX_CONCURRENCY.
class _Lane:
    def __init__(self, name, size):
        self.name, self.size = name, size
        self.heap = []           # [(priority, seq, coro, future), ...] -- a min-heap
        self.running = []        # [(priority, task), ...] -- currently executing, len <= size
        self.wakeup = asyncio.Event()
        for _ in range(size):
            _loop.create_task(_dispatcher(self))


_lanes = {}


def _lane(name):
    """On _loop's thread only."""
    lane = _lanes.get(name)
    if lane is None:
        try:
            from llm import provider
            size = provider.settings(name)["max_concurrency"]
        except Exception:                                 # noqa: BLE001
            size = OLLAMA_MAX_CONCURRENCY
        lane = _lanes[name] = _Lane(name, size)
    return lane


def __getattr__(attr):
    # api/admin.py::llm_gate_state reads _heap / _running: all lanes together
    if attr == "_heap":
        return [e for lane in list(_lanes.values()) for e in lane.heap]
    if attr == "_running":
        return [e for lane in list(_lanes.values()) for e in lane.running]
    raise AttributeError(attr)


def lanes_state():
    return {n: {"queued": len(l.heap), "running": len(l.running), "max_concurrency": l.size,
                "queued_priorities": [p for p, *_ in l.heap]} for n, l in list(_lanes.items())}


async def _dispatcher(lane):
    """One of the lane's identical workers -- pops its highest-priority queued entry, runs it as a cancellable task,
    and resolves that entry's future on completion, failure, or cancellation. Never lets a CancelledError escape to
    the caller (see _ABORTED_ERROR)."""
    while True:
        if not lane.heap:
            await lane.wakeup.wait()
            lane.wakeup.clear()
            continue

        priority, _seq, coro, fut = heapq.heappop(lane.heap)
        if fut.done():
            coro.close()
            continue  # caller already gave up (e.g. its own timeout fired first)

        task = asyncio.ensure_future(coro)
        # If the caller gives up (hard timeout), stop the in-flight request too.
        fut.add_done_callback(lambda f, t=task: t.cancel() if f.cancelled() else None)
        slot = (priority, task)
        lane.running.append(slot)
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
            lane.running.remove(slot)


def _enqueue(coro, priority, profile):
    """Runs on _loop's own thread (called from within a coroutine already
    scheduled there via run_coroutine_threadsafe) -- heapq/list mutations
    here need no separate lock."""
    lane = _lane(profile)
    fut = _loop.create_future()
    heapq.heappush(lane.heap, (priority, next(_counter), coro, fut))

    # Preempt the single least-urgent running task in this lane if it's strictly less
    # urgent than this new arrival -- e.g. a background item-content call
    # already in flight gets cancelled the moment a survival-critical
    # character decision shows up, rather than making it wait its turn.
    if lane.running:
        worst_priority, worst_task = max(lane.running, key=lambda s: s[0])
        if priority < worst_priority:
            worst_task.cancel()

    lane.wakeup.set()
    return fut


async def _submit_and_await(coro, priority, profile):
    fut = _enqueue(coro, priority, profile)
    return await fut


def _profile_of(coro, profile=None):
    """Which lane a call belongs in: the profile asked for, else that of the character the coroutine is for (its
    char_id argument -- call_llm_safe(..., char_id=...) and most callers), else the background profile."""
    try:
        from llm import provider
        if profile:
            return profile
        frame = getattr(coro, "cr_frame", None)
        args = frame.f_locals if frame is not None else {}
        cid = args.get("char_id")
        if cid is None:
            c = args.get("c") or args.get("char") or args.get("character")
            cid = c.get("id") if isinstance(c, dict) else None
        return provider.profile_for(cid if isinstance(cid, str) else None)
    except Exception:                                     # noqa: BLE001
        return "env"


def _tagged(coro):
    """The call, carrying what it's for (llm/llm_client.py::CALL_TAGS) onto this loop: who asked (taken here, while
    the asker is still on the stack) and the asking thread's tags (cognition: the wake reason)."""
    try:
        from llm import llm_client
        tags = dict(llm_client.thread_call_tags(), purpose=llm_client.caller_purpose(3))
    except Exception:                                     # noqa: BLE001
        return coro

    async def run():
        llm_client.CALL_TAGS.set(tags)
        return await coro
    return run()


def _run_loop():
    asyncio.set_event_loop(_loop)
    _wakeup_ready.set()
    _loop.run_forever()


_thread = threading.Thread(target=_run_loop, name="llm-gate", daemon=True)
_thread.start()


def run_llm_call(coro, priority=PRIORITY_NORMAL, timeout=None, profile=None):
    """Submit an awaitable (e.g. call_llm_safe(...)) to the gate's event
    loop and block the calling thread until it completes (or is aborted
    for a higher-priority arrival -- see module docstring), bounded by
    OLLAMA_MAX_CONCURRENCY concurrent in-flight calls across all callers."""
    from core import tick_state
    on_tick = tick_state.in_tick_thread()
    if on_tick:
        # The tick holds the world lock for its whole run, so a model call made from
        # the tick thread stalls the simulation and every API route behind that lock
        # for as long as the call takes (up to the 90s gate timeout). Bound it: a short
        # per-call cap and a per-tick budget; callers fall back on a failed call.
        remaining = tick_state.remaining_budget()
        if remaining <= 0:
            coro.close()
            return dict(_TIMEOUT_ERROR)
        timeout = min(timeout if timeout is not None else tick_state.TICK_LLM_CALL_MAX_SECONDS,
                      tick_state.TICK_LLM_CALL_MAX_SECONDS, remaining)
    lane_profile = _profile_of(coro, profile)            # read from the call's own arguments, before it is wrapped
    future = asyncio.run_coroutine_threadsafe(_submit_and_await(_tagged(coro), priority, lane_profile), _loop)
    t0 = time.perf_counter()
    try:
        return future.result(timeout=timeout if timeout is not None else LLM_CALL_MAX_WAIT_SECONDS)
    except concurrent.futures.TimeoutError:
        future.cancel()
        print(f"[llm_gate] call abandoned after {timeout or LLM_CALL_MAX_WAIT_SECONDS}s"
              + (" (on the tick thread)" if on_tick else ""))
        return dict(_TIMEOUT_ERROR)
    finally:
        if on_tick:
            took = time.perf_counter() - t0
            tick_state.spend(took)
            import traceback
            caller = " <- ".join(f"{f.name}({f.filename.rsplit('/', 1)[-1]}:{f.lineno})"
                                  for f in reversed(traceback.extract_stack(limit=7)[:-1]))
            print(f"[llm_gate] LLM call on the TICK THREAD took {took:.1f}s (move it to bg_llm): {caller}", flush=True)


def gate_failed(result):
    """True when `result` is the {"error": ...} dict run_llm_call hands back on
    a timeout, a preemption, or a dispatcher exception -- as opposed to the
    coroutine's own return value.

    Callers are written against the coroutine's contract (a valid payload, or
    None on failure) and guard with a bare `if not result:` -- but that dict is
    truthy, so it sailed past the fallback and was then used as if it were a
    real narration/opinion/beat list. Confirmed live: three household daily
    summaries had {"error": "timeout: ..."} stored as their text.
    """
    return isinstance(result, dict) and set(result) == {"error"}


async def run_llm_call_async(coro, priority=PRIORITY_NORMAL, timeout=None, profile=None):
    """Async equivalent of run_llm_call, for callers already inside an
    event loop (e.g. cognition_jobs.py) -- schedules onto the gate's loop
    and awaits the result without blocking the caller's own loop thread."""
    lane_profile = _profile_of(coro, profile)
    future = asyncio.run_coroutine_threadsafe(_submit_and_await(_tagged(coro), priority, lane_profile), _loop)
    try:
        return await asyncio.wait_for(asyncio.wrap_future(future),
                                      timeout if timeout is not None else LLM_CALL_MAX_WAIT_SECONDS)
    except asyncio.TimeoutError:
        future.cancel()
        return dict(_TIMEOUT_ERROR)
