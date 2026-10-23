"""
core/cognition_queue.py

The wire between the simulation core and the cognition workers (docs/distributed_architecture_plan.md,
"container split"). Two Redis Streams:

    cognition:req   decision requests, one consumer group (cognition-workers); a worker claims a
                    request, runs the model round-trip, publishes the result and acks. A worker that
                    dies mid-request leaves it pending; another worker takes it over after
                    CLAIM_IDLE_MS.
    cognition:res   results, read by the core's reader thread (brain/cognition_actor.py).

Workers advertise themselves with a short-lived key (cognition:worker:<id>); the core only sends
work over the wire while at least one is alive, and otherwise keeps running decisions in-process,
so a stopped worker container never stalls the simulation.

Payloads are one JSON string in the "p" field. A request carries a wall-clock deadline: a worker
that picks up a request nobody is waiting for any more drops it without calling the model.
"""

import json
import os
import time

from core.cache import r

REQ_STREAM = "cognition:req"
RES_STREAM = "cognition:res"
GROUP = "cognition-workers"
WORKER_KEY_PREFIX = "cognition:worker:"
WORKER_KEY_TTL = 10                       # seconds; workers refresh every few seconds
CLAIM_IDLE_MS = 150_000                   # a request unacked this long belongs to a dead worker
REQ_MAXLEN = 5000
RES_MAXLEN = 2000

_alive_cache = {"t": 0.0, "n": 0}
ALIVE_CACHE_SECONDS = 2.0


def _dumps(obj):
    return json.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# core side
# ---------------------------------------------------------------------------

def workers_alive():
    """Number of workers whose heartbeat is current (cached for a couple of seconds)."""
    now = time.time()
    if now - _alive_cache["t"] < ALIVE_CACHE_SECONDS:
        return _alive_cache["n"]
    try:
        n = sum(1 for _ in r.scan_iter(match=WORKER_KEY_PREFIX + "*", count=100))
    except Exception:
        n = 0
    _alive_cache["t"] = now
    _alive_cache["n"] = n
    return n


def forget_alive_cache():
    _alive_cache["t"] = 0.0


def enqueue(request):
    """Put a decision request on the stream. Raises if Redis is unreachable."""
    ensure_group()
    return r.xadd(REQ_STREAM, {"p": _dumps(request)}, maxlen=REQ_MAXLEN, approximate=True)


def latest_result_id():
    """The id to start reading results from (only results published from now on)."""
    try:
        info = r.xinfo_stream(RES_STREAM)
        return info.get("last-generated-id", "0-0")
    except Exception:
        return "0-0"


def read_results(last_id, block_ms=1000, count=50):
    """Results published after last_id -> (new_last_id, [result dicts])."""
    out = []
    resp = r.xread({RES_STREAM: last_id}, count=count, block=block_ms)
    for _stream, entries in resp or []:
        for entry_id, fields in entries:
            last_id = entry_id
            try:
                out.append(json.loads(fields["p"]))
            except Exception:
                pass
    return last_id, out


# ---------------------------------------------------------------------------
# worker side
# ---------------------------------------------------------------------------

def ensure_group():
    try:
        r.xgroup_create(REQ_STREAM, GROUP, id="$", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def heartbeat(worker_id, info=None):
    r.set(WORKER_KEY_PREFIX + worker_id, _dumps(info or {"t": time.time()}), ex=WORKER_KEY_TTL)


def goodbye(worker_id):
    try:
        r.delete(WORKER_KEY_PREFIX + worker_id)
    except Exception:
        pass


def claim(consumer, block_ms=5000):
    """Next request for this consumer -> (stream_id, request dict) or None.
    Requests abandoned by a dead consumer are taken over first."""
    ensure_group()
    try:
        res = r.xautoclaim(REQ_STREAM, GROUP, consumer, min_idle_time=CLAIM_IDLE_MS, start_id="0-0", count=1)
        entries = res[1] if res else []
        for entry_id, fields in entries:
            if fields:
                return entry_id, json.loads(fields["p"])
            r.xack(REQ_STREAM, GROUP, entry_id)          # deleted entry still in the PEL
    except Exception:
        pass
    resp = r.xreadgroup(GROUP, consumer, {REQ_STREAM: ">"}, count=1, block=block_ms)
    for _stream, entries in resp or []:
        for entry_id, fields in entries:
            return entry_id, json.loads(fields["p"])
    return None


def complete(stream_id, result=None):
    """Publish the result (if any) and retire the request."""
    if result is not None:
        r.xadd(RES_STREAM, {"p": _dumps(result)}, maxlen=RES_MAXLEN, approximate=True)
    r.xack(REQ_STREAM, GROUP, stream_id)
    r.xdel(REQ_STREAM, stream_id)


def new_worker_id():
    return f"{os.getenv('HOSTNAME', 'worker')}-{os.getpid()}"
