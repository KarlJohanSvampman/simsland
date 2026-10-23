"""
core/work_queue.py

A request/result queue between the simulation core and a fleet of stateless workers, on Redis
Streams (docs/distributed_architecture_plan.md, "container split"). One WorkQueue per kind of work
(cognition decisions, background LLM jobs); each has

    <name>:req            requests, one consumer group (<name>-workers): a worker claims a request,
                          does it, publishes the result and acks. A worker that dies mid-request
                          leaves it unacked and another takes it over after claim_idle_ms.
    <name>:res            results, read by the core's ResultReader thread
    <name>:worker:<id>    a worker's short-lived heartbeat key; the core only sends work over the
                          wire while at least one is alive, so a stopped worker container never
                          stalls the simulation.

Payloads are one JSON string in the "p" field. Requests should carry a wall-clock "deadline"; a
worker that picks up a request nobody is waiting for any more drops it without doing the work.
"""

import json
import os
import threading
import time

from core.cache import r

WORKER_KEY_TTL = 10                       # seconds; workers refresh every few seconds


def _dumps(obj):
    return json.dumps(obj, default=str)


class WorkQueue:
    def __init__(self, name, claim_idle_ms=150_000, req_maxlen=5000, res_maxlen=2000, alive_cache_seconds=2.0):
        self.claim_idle_ms = claim_idle_ms
        self.req_maxlen = req_maxlen
        self.res_maxlen = res_maxlen
        self.alive_cache_seconds = alive_cache_seconds
        self._alive = {"t": 0.0, "n": 0}
        self.rename(name)

    def rename(self, name):
        """Point at different stream/key names (tests use their own, so nothing live is touched)."""
        self.name = name
        self.req_stream = f"{name}:req"
        self.res_stream = f"{name}:res"
        self.group = f"{name}-workers"
        self.worker_prefix = f"{name}:worker:"
        self.forget_alive_cache()

    # ---- core side ---------------------------------------------------------------------

    def workers_alive(self):
        """Number of workers whose heartbeat is current (cached for a couple of seconds)."""
        now = time.time()
        if now - self._alive["t"] < self.alive_cache_seconds:
            return self._alive["n"]
        try:
            n = sum(1 for _ in r.scan_iter(match=self.worker_prefix + "*", count=100))
        except Exception:
            n = 0
        self._alive["t"] = now
        self._alive["n"] = n
        return n

    def forget_alive_cache(self):
        self._alive["t"] = 0.0

    def enqueue(self, request):
        """Put a request on the stream. Raises if Redis is unreachable."""
        self.ensure_group()
        return r.xadd(self.req_stream, {"p": _dumps(request)}, maxlen=self.req_maxlen, approximate=True)

    def latest_result_id(self):
        """The id to start reading results from (only results published from now on)."""
        try:
            return r.xinfo_stream(self.res_stream).get("last-generated-id", "0-0")
        except Exception:
            return "0-0"

    def read_results(self, last_id, block_ms=1000, count=50):
        """Results published after last_id -> (new_last_id, [result dicts])."""
        out = []
        resp = r.xread({self.res_stream: last_id}, count=count, block=block_ms)
        for _stream, entries in resp or []:
            for entry_id, fields in entries:
                last_id = entry_id
                try:
                    out.append(json.loads(fields["p"]))
                except Exception:
                    pass
        return last_id, out

    def start_reader(self, on_result, on_idle=None, label=None):
        """A daemon thread feeding every published result to on_result(dict), and calling
        on_idle() after each read (about once a second) -- for fallbacks and housekeeping.
        The starting id is taken NOW, so call this before the first request is enqueued."""
        label = label or self.name
        start = self.latest_result_id()

        def loop():
            last_id = start
            while True:
                results = []
                try:
                    last_id, results = self.read_results(last_id, block_ms=1000)
                except Exception as exc:
                    print(f"[{label}] result stream error: {exc!r}")
                    time.sleep(2.0)
                for res in results:
                    try:
                        on_result(res)
                    except Exception as exc:
                        print(f"[{label}] result handler error: {exc!r}")
                if on_idle:
                    try:
                        on_idle()
                    except Exception as exc:
                        print(f"[{label}] idle handler error: {exc!r}")

        t = threading.Thread(target=loop, daemon=True, name=f"{label}-results")
        t.start()
        return t

    # ---- worker side -------------------------------------------------------------------

    def ensure_group(self):
        try:
            r.xgroup_create(self.req_stream, self.group, id="$", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def heartbeat(self, worker_id, info=None):
        r.set(self.worker_prefix + worker_id, _dumps(info or {"t": time.time()}), ex=WORKER_KEY_TTL)

    def goodbye(self, worker_id):
        try:
            r.delete(self.worker_prefix + worker_id)
        except Exception:
            pass

    def claim(self, consumer, block_ms=5000):
        """Next request for this consumer -> (stream_id, request dict) or None.
        Requests abandoned by a dead consumer are taken over first."""
        self.ensure_group()
        try:
            res = r.xautoclaim(self.req_stream, self.group, consumer, min_idle_time=self.claim_idle_ms,
                               start_id="0-0", count=1)
            for entry_id, fields in (res[1] if res else []):
                if fields:
                    return entry_id, json.loads(fields["p"])
                r.xack(self.req_stream, self.group, entry_id)      # deleted entry still in the PEL
        except Exception:
            pass
        resp = r.xreadgroup(self.group, consumer, {self.req_stream: ">"}, count=1, block=block_ms)
        for _stream, entries in resp or []:
            for entry_id, fields in entries:
                return entry_id, json.loads(fields["p"])
        return None

    def complete(self, stream_id, result=None):
        """Publish the result (if any) and retire the request."""
        if result is not None:
            r.xadd(self.res_stream, {"p": _dumps(result)}, maxlen=self.res_maxlen, approximate=True)
        r.xack(self.req_stream, self.group, stream_id)
        r.xdel(self.req_stream, stream_id)


def new_worker_id():
    return f"{os.getenv('HOSTNAME', 'worker')}-{os.getpid()}"
