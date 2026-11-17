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


def run():
    sim = "t" + uuid.uuid4().hex[:8]
    tmp = tempfile.mkdtemp()
    procs, outs = [], []
    for p in range(N):
        out = os.path.join(tmp, f"p{p}.json")
        outs.append(out)
        procs.append(subprocess.Popen([sys.executable, os.path.join(here, "tools", "partition_runner.py"), sim, str(p),
                                       str(N), str(TICKS), out], cwd=here, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, env=dict(os.environ, PYTHONHASHSEED="0")))
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

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
