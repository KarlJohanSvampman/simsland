"""
Step 5b, slice 3 (docs/step5b_plan.md): partitions as separate processes -- three of tools/partition_runner.py, each
with its own memory, exchanging patches and frames over Redis streams, in lockstep.

  * all three run without errors;
  * once the last messages are in, all three hold the same copy of every shared entity (they converge);
  * patches travelled between them and landed; every character kept running in its own partition;
  * the same run again gives the same world (lockstep + messages applied in a fixed order: reproducible).

Run inside the backend container (needs Redis):   python tests/test_partition_processes.py
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


N, TICKS = 3, int(os.getenv("PART_TICKS", "600"))
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(free=False, move_at=0):
    sim = "t" + uuid.uuid4().hex[:8]
    tmp = tempfile.mkdtemp()
    procs, outs = [], []
    for p in range(N):
        out = os.path.join(tmp, f"p{p}.json")
        outs.append(out)
        procs.append(subprocess.Popen([sys.executable, os.path.join(here, "tools", "partition_runner.py"), sim, str(p),
                                       str(N), str(TICKS), out], cwd=here, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE,
                                      env=dict(os.environ, PYTHONHASHSEED="0", PART_FREE="1" if free else "0",
                                               PART_MOVE_AT=str(move_at))))
    codes = []
    for pr in procs:
        _o, err = pr.communicate(timeout=1800)
        codes.append((pr.returncode, err.decode()[-600:] if pr.returncode else ""))
    from core.partitions import RedisTransport
    RedisTransport(N, sim).clear()
    return codes, [json.load(open(o)) for o in outs if os.path.exists(o)]


codes, res = run()
check("three partition processes ran to the end", all(c == 0 for c, _ in codes) and len(res) == N, codes)
if len(res) == N:
    check("... without errors", not any(r["errors"] for r in res), [r["errors"] for r in res])
    keys = set().union(*(r["entities"] for r in res))
    differ = [k for k in keys if len({r["entities"].get(k) for r in res}) > 1]
    check("once the last messages are in, all three hold the same copy of every shared entity", not differ, differ[:8])
    st = {k: sum(r["stats"][k] for r in res) for k in res[0]["stats"]}
    print(f"   stats: {st}")
    check("patches travelled between the processes, and landed", st["patches_in"] > 0 and st["ops_landed"] > 0)
    owners = res[0]["owners"]["characters"]
    stalled = [cid for cid, part in owners.items()
               if (res[part]["last_run"].get(cid) or 0) < (res[part]["sim_time"] or 0) - 120]
    check("every character kept running in its own partition's process", not stalled, (stalled, owners))
    codes2, res2 = run()
    same = len(res2) == N and all(res2[i]["entities"] == res[i]["entities"] for i in range(N))
    check("the same run again gives the same world (reproducible)", same,
          [k for k in keys if len(res2) == N and res2[0]["entities"].get(k) != res[0]["entities"].get(k)][:5])

codes3, res3 = run(free=True)
if len(res3) == N:
    keys3 = set().union(*(r["entities"] for r in res3))
    differ3 = [k for k in keys3 if len({r["entities"].get(k) for r in res3}) > 1]
    check("free-running (as the server runs: no barrier per step), they still converge once the last messages are in",
          all(c == 0 for c, _ in codes3) and not any(r["errors"] for r in res3) and not differ3, (codes3, differ3[:5]))
else:
    check("free-running partitions ran to the end", False, codes3)

codes4, res4 = run(free=True, move_at=TICKS // 2)
if len(res4) == N:
    keys4 = set().union(*(r["entities"] for r in res4))
    differ4 = [k for k in keys4 if len({r["entities"].get(k) for r in res4}) > 1]
    moved = [h for h, q in res4[0]["owners"]["households"].items() if q == 1 and res[0]["owners"]["households"][h] == N - 1]
    check("a household moved between processes mid-run: the map says so everywhere, copies agree, no errors",
          moved and not differ4 and not any(r["errors"] for r in res4)
          and all(r["owners"] == res4[0]["owners"] for r in res4), (moved, differ4[:5]))
    owners4 = res4[0]["owners"]["characters"]
    stalled4 = [cid for cid, part in owners4.items()
                if (res4[part]["last_run"].get(cid) or 0) < (res4[part]["sim_time"] or 0) - 120]
    check("... and its members kept running in their new process", not stalled4, (stalled4, owners4))
else:
    check("the moving run ran to the end", False, codes4)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
