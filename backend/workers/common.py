"""
workers/common.py -- the shared loop of a stateless worker: claim a request from a WorkQueue, drop it
if its deadline has passed, run handler(request) -> result dict, publish, repeat; plus the heartbeat
that tells the core this worker is alive.
"""

import signal
import threading
import time

from core.work_queue import new_worker_id


class Runtime:
    def __init__(self, label, queue, handler, threads, heartbeat_seconds=3.0, worker_id=None):
        self.label = label
        self.queue = queue
        self.handler = handler
        self.threads = threads
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_id = worker_id or new_worker_id()
        self.stop = threading.Event()
        self.stats = {"done": 0, "dropped": 0, "failed": 0, "busy": 0}
        self._lock = threading.Lock()
        self._threads = []

    def _count(self, key, delta=1):
        with self._lock:
            self.stats[key] += delta

    def loop(self):
        while not self.stop.is_set():
            try:
                got = self.queue.claim(self.worker_id, block_ms=2000)
            except Exception as exc:
                print(f"[{self.label}] queue error: {exc!r}")
                self.stop.wait(2.0)
                continue
            if not got:
                continue
            stream_id, req = got
            if req.get("deadline") and time.time() > req["deadline"]:
                self._count("dropped")
                self.queue.complete(stream_id)            # nobody is waiting for this any more
                continue
            self._count("busy")
            try:
                result = self.handler(req)
            finally:
                self._count("busy", -1)
            self._count("failed" if (result or {}).get("error") else "done")
            try:
                self.queue.complete(stream_id, result)
            except Exception as exc:
                print(f"[{self.label}] could not publish result: {exc!r}")

    def beat(self):
        while not self.stop.is_set():
            try:
                with self._lock:
                    info = dict(self.stats, threads=self.threads, t=time.time())
                self.queue.heartbeat(self.worker_id, info)
            except Exception as exc:
                print(f"[{self.label}] heartbeat failed: {exc!r}")
            self.stop.wait(self.heartbeat_seconds)

    def start(self):
        self.queue.ensure_group()
        threading.Thread(target=self.beat, daemon=True, name="heartbeat").start()
        self._threads = [threading.Thread(target=self.loop, daemon=True, name=f"{self.label}-{i}")
                         for i in range(self.threads)]
        for t in self._threads:
            t.start()

    def main(self):
        print(f"[{self.label}] {self.worker_id} starting with {self.threads} threads")
        signal.signal(signal.SIGTERM, lambda *a: self.stop.set())
        self.start()
        try:
            while not self.stop.is_set():
                self.stop.wait(1.0)
        except KeyboardInterrupt:
            self.stop.set()
        self.queue.goodbye(self.worker_id)
        deadline = time.time() + 60                     # let in-flight requests finish and publish
        for t in self._threads:
            t.join(timeout=max(0.1, deadline - time.time()))
        print(f"[{self.label}] {self.worker_id} stopped")
