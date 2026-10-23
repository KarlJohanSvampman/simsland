"""
The seeded simulation is deterministic: two runs in fresh processes end in the same world and
agree at every checkpoint. This is the foundation for differential tests -- run the sim with and
without some change (a gate, a refactor, a new persistence mode) and diff the worlds; if the
harness itself weren't deterministic, every diff would be noise.

Also usable as a regression check: the first run's result is the reference for a change made
between invocations (run tests/run_det.py --out before and after).

Needs /tmp/backup_world.json (a populated snapshot from backups/). Run in the backend container:
    python tests/test_determinism.py [ticks]
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from tests.determinism import diff

TICKS = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
failures = []


def check(name, cond, detail=""):
    print(("ok   " + name) if cond else f"FAIL {name}  {detail}")
    if not cond:
        failures.append(name)


def run(start, tag):
    out = f"/tmp/det_{tag}.json"
    r = subprocess.run([sys.executable, "tests/run_det.py", "--ticks", str(TICKS), "--start", start, "--out", out],
                       capture_output=True, text=True, cwd="/app", env={**os.environ, "PYTHONHASHSEED": "0"})
    if r.returncode != 0:
        print(r.stderr[-800:])
    return json.load(open(out))


for label, start in (("across midnight and a week boundary", "2026-11-01T23:50:00"), ("an ordinary afternoon", "2026-11-04T13:00:00")):
    a, b = run(start, "a"), run(start, "b")
    check(f"no exceptions ({label})", not a["errors"] and not b["errors"], f"{a['errors']} / {b['errors']}")
    check(f"checkpoints identical ({label})", a["checkpoints"] == b["checkpoints"])
    d = diff(a["world"], b["world"])
    check(f"final worlds identical ({label})", not d, str(d[:4]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
