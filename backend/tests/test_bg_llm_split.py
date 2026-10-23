"""
Container split, stage 2: background LLM jobs on workers (systems/bg_llm.py, workers/bg_llm.py).

Uses its own stream/key names so a running core or worker is never involved.

Run inside the backend container:   python tests/test_bg_llm_split.py
"""

import os
import sys
import threading
import time

os.environ.setdefault("BG_LLM_MODE", "auto")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from core.cache import r
from systems import bg_llm
import workers.bg_llm as wk
import llm.self_assessment as sa
import llm.behavior_theory as bt
from llm import llm_client

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


q = bg_llm.queue
q.rename("test:bg")
q.alive_cache_seconds = 0.0
for k in (q.req_stream, q.res_stream):
    r.delete(k)
for k in r.scan_iter(match=q.worker_prefix + "*"):
    r.delete(k)


def wait_for(pred, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def take_wait(key, timeout=10.0):
    box = []

    def got():
        ready, v = bg_llm.take(key)
        if ready:
            box.append(v)
        return ready
    return (wait_for(got, timeout), box[0] if box else None)


where = []                                           # "local" / "worker" per call


def fake_assess(name, age, activity, count, minutes, reason, situation):
    where.append(threading.current_thread().name)
    return {"thought": f"{name} reflects", "n": count}


fake_assess.__module__, fake_assess.__name__ = "llm.self_assessment", "assess"
sa.assess = fake_assess


def fake_theory(prompt, force_optimistic, char_id):
    llm_client.log_prompt_entry(char_id, [{"role": "user", "content": prompt}], "theory", 0.1, False)
    return {"text": "a theory"}


fake_theory.__module__, fake_theory.__name__ = "llm.behavior_theory", "theory_from_prompt"
bt.theory_from_prompt = fake_theory

# ---- nobody listening: runs here ----------------------------------------------------------
check("no worker alive", q.workers_alive() == 0)
bg_llm.submit("k1", sa.assess, "Ann", 8, "dust", 3, 2, "tidy", "kitchen")
ok, v = take_wait("k1")
check("with no worker the call runs on this process's pool", ok and v["n"] == 3 and where[-1].startswith("bg_llm"), str(where))
check("the entry is gone after take", not bg_llm.is_pending("k1"))

# ---- a worker in this process --------------------------------------------------------------
wk.runtime.worker_id = "test-bg-worker"
wk.runtime.heartbeat_seconds = 0.5
wk.runtime.threads = 2
wk.runtime.start()
check("the worker's heartbeat is seen", wait_for(lambda: q.workers_alive() == 1))

sent = []
_real_enqueue = q.enqueue
q.enqueue = lambda req: (sent.append(req["key"]), _real_enqueue(req))[1]
where.clear()
check("submit reports newly queued", bg_llm.submit("k2", sa.assess, "Bo", 9, "wipe", 4, 1, None, ""))
check("a second submit of the same key is refused", not bg_llm.submit("k2", sa.assess, "Bo", 9, "wipe", 4, 1, None, ""))
check("the entry went over the wire", sent == ["k2"], str(sent))
ok, v = take_wait("k2")
check("the worker's answer is taken", ok and v == {"thought": "Bo reflects", "n": 4})
check("it ran on a worker thread, not the local pool", where and where[-1].startswith("bg-llm-worker"), str(where))

# several at once
for i in range(10):
    bg_llm.submit(f"m{i}", sa.assess, f"P{i}", 7, "x", i, 1, None, "")
res = [take_wait(f"m{i}", 15) for i in range(10)]
check("ten concurrent calls all come back, each its own", all(ok and v["n"] == i for i, (ok, v) in enumerate(res)))

# prompt log shipped back for the call's character
llm_client._PROMPT_LOG.pop("char9", None)
bg_llm.submit("t1", bt.theory_from_prompt, "why?", False, "char9")
ok, v = take_wait("t1")
check("theory result returns", ok and v == {"text": "a theory"})
check("its prompt-log entry is merged for the character", len(llm_client.get_prompt_log("char9")) >= 1)

# not on the allow-list -> never sent
ran = []
def local_only(x):
    ran.append(threading.current_thread().name)
    return x * 2
bg_llm.submit("l1", local_only, 21)
ok, v = take_wait("l1")
check("a function off the allow-list runs here", ok and v == 42 and ran[0].startswith("bg_llm"))

# arguments that aren't plain JSON -> runs here
bg_llm.submit("o1", sa.assess, "Cy", 5, object(), 1, 1, None, "")
ok, v = take_wait("o1")
check("non-JSON arguments run here", ok and v and where[-1].startswith("bg_llm"), str(where[-1:]))

# a failing function on the worker -> None, like the local path
def boom(*a):
    raise RuntimeError("model down")
boom.__module__, boom.__name__ = "llm.self_assessment", "assess"
sa.assess = boom
bg_llm.submit("e1", boom, "D", 1, "y", 1, 1, None, "")
ok, v = take_wait("e1")
check("a failing call answers None", ok and v is None)
sa.assess = fake_assess

# a name that is not allowed is refused by the worker even if sent
res = wk.run_request({"key": "bad", "token": "t", "task": "os:system", "args": ["echo hi"]})
check("the worker refuses a task off the allow-list", res["error"] and "not allowed" in res["error"] and res["value"] is None)

# expired requests are dropped
q.enqueue({"key": "old", "token": "x", "task": "llm.self_assessment:assess", "args": ["a", 1, "b", 1, 1, None, ""],
           "deadline": time.time() - 5})
n_before = len(where)
time.sleep(2.5)
check("an expired request is dropped without running", len(where) == n_before)

# ---- worker disappears with a call outstanding ---------------------------------------------
wk.runtime.stop.set()
time.sleep(2.5)
r.delete(q.worker_prefix + "test-bg-worker")
q.forget_alive_cache()
check("the stopped worker is no longer alive", q.workers_alive() == 0)

bg_llm.MODE = "remote"                               # force the wire with nobody listening
bg_llm.REMOTE_FALLBACK_SECONDS = 1.0
where.clear()
bg_llm.submit("s1", sa.assess, "Eve", 6, "z", 7, 1, None, "")
check("it was queued remotely", sent[-1] == "s1", str(sent[-3:]))
ok, v = take_wait("s1", 12)
check("with nobody answering it falls back to running here", ok and v and v["n"] == 7 and where and where[-1].startswith("bg_llm"), str(where))

# a late answer from the wire, after the fallback took over, is ignored
bg_llm.submit("s2", sa.assess, "Fay", 6, "z", 8, 1, None, "")
ok, v = take_wait("s2", 12)
check("fallback answered", ok and v["n"] == 8)
bg_llm.submit("s3", sa.assess, "Gus", 6, "z", 9, 1, None, "")      # a new request under the same kind of key
bg_llm._accept_result({"key": "s3", "token": "not-the-current-one", "value": {"n": -1}})
check("a result with a stale token is ignored", "s3" in bg_llm._inflight and "s3" not in bg_llm._done)
ok, v = take_wait("s3", 12)
check("the real answer wins", ok and v["n"] == 9, str(v))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
