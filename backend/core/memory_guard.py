"""
Memory guard: a watchdog thread on this process's resident memory.

The container has a hard memory limit and a restart policy (docker-compose.yml),
but the kernel OOM-kill is a blunt instrument that can take the whole Docker VM
down with it. This gets in first:

  soft limit -> log loudly + force a GC pass (cheap, often enough)
  hard limit -> exit(1); Docker restarts the backend and the world reloads from
               Postgres. A clean restart in seconds beats a frozen host.

Limits are env-tunable (MEMORY_SOFT_MB / MEMORY_HARD_MB, MEMORY_GUARD_INTERVAL).
"""

import gc
import os
import threading
import time

SOFT_MB = float(os.getenv("MEMORY_SOFT_MB", "1500"))
HARD_MB = float(os.getenv("MEMORY_HARD_MB", "2600"))
INTERVAL = float(os.getenv("MEMORY_GUARD_INTERVAL", "10"))


def rss_mb():
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except Exception:
        return 0.0     # not Linux: guard becomes a no-op


def _loop():
    last_soft = 0.0
    while True:
        time.sleep(INTERVAL)
        mb = rss_mb()
        if mb >= HARD_MB:
            print(f"[memory_guard] RSS {mb:.0f}MB >= hard limit {HARD_MB:.0f}MB -- exiting so Docker restarts the backend", flush=True)
            os._exit(1)
        if mb >= SOFT_MB and time.monotonic() - last_soft > 60:
            last_soft = time.monotonic()
            print(f"[memory_guard] RSS {mb:.0f}MB >= soft limit {SOFT_MB:.0f}MB -- forcing GC", flush=True)
            gc.collect()


def start():
    if rss_mb() > 0:
        threading.Thread(target=_loop, name="memory-guard", daemon=True).start()
