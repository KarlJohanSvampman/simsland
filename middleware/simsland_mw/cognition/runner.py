"""
Background wake-up loop. Phase 1: poll Simsland's /mw/due (characters flagged
external_brain whose think tick has arrived) and run a decision for each.
Phase 3 replaces the polling with event-driven wakes from Simsland's own
cognition scheduler; the engine underneath does not change.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Set

from .engine import CognitionEngine

log = logging.getLogger(__name__)
FAILURE_BACKOFF_SECONDS = 15.0


class Runner:
    def __init__(self, engine: CognitionEngine, poll_interval: float = 2.0, max_concurrency: int = 2):
        self.engine = engine
        self.poll_interval = poll_interval
        self._sem = asyncio.Semaphore(max_concurrency)
        self._task: Optional[asyncio.Task] = None
        self._inflight: Set[str] = set()
        self._cooldown: Dict[str, float] = {}
        self.history: Deque[Dict[str, Any]] = deque(maxlen=100)
        self.last_error: Optional[str] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop(), name="mw-runner")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # Simsland down, etc. Keep the loop alive.
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("runner poll failed: %s", self.last_error)
            await asyncio.sleep(self.poll_interval)

    async def tick(self) -> None:
        due = (await self.engine.sim.due()).get("due", [])
        now = time.monotonic()
        for d in due:
            cid = d["id"]
            if cid in self._inflight or self._cooldown.get(cid, 0) > now:
                continue
            self._inflight.add(cid)
            asyncio.create_task(self._run_one(cid, d.get("wake_reason")))

    async def _run_one(self, char_id: str, wake_reason: Optional[str]) -> None:
        try:
            async with self._sem:
                rec = await self.engine.decide(char_id, wake_reason)
            self.history.append(rec.to_dict())
            self.last_error = None
        except Exception as e:
            self.last_error = f"{char_id}: {type(e).__name__}: {e}"
            log.warning("decision failed for %s: %s", char_id, e)
            self._cooldown[char_id] = time.monotonic() + FAILURE_BACKOFF_SECONDS
        finally:
            self._inflight.discard(char_id)
