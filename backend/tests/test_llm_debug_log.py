"""
The LLM debug page's data (frontend/llm_debug.html, api/llm_debug.py):

A. The service's numbers (tokens, model, timings) are read out of an Ollama and an OpenAI-shaped response.
B. Every call is logged with an id and sizes -- background calls (no character) too; found again by id.
C. A worker's entries merged in keep their id; the same one shipped twice is kept once.
D. /admin/llm/all lists all of them newest first, with filters and totals; /admin/llm/entry/{id} returns one in full.

Run inside the backend container:   python tests/test_llm_debug_log.py
"""
import os, sys, time
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from llm import provider, llm_client as L

# A
m = provider.usage_meta({"model": "llama3.1", "prompt_eval_count": 2400, "eval_count": 120, "load_duration": 5e8,
                         "prompt_eval_duration": 2e9, "eval_duration": 3e9, "done_reason": "stop"})
check("A: Ollama: tokens, timings, why it stopped", m["prompt_tokens"] == 2400 and m["completion_tokens"] == 120
      and m["prompt_eval_s"] == 2.0 and m["eval_s"] == 3.0 and m["done_reason"] == "stop", m)
m = provider.usage_meta({"model": "gpt-4o-mini", "usage": {"prompt_tokens": 900, "completion_tokens": 50, "total_tokens": 950},
                         "choices": [{"finish_reason": "length", "message": {"content": "x"}}]})
check("A: OpenAI shape: tokens, finish reason", m["prompt_tokens"] == 900 and m["completion_tokens"] == 50
      and m["done_reason"] == "length" and m["model"] == "gpt-4o-mini", m)

# B
L._PROMPT_LOG.clear()
msgs = [{"role": "system", "content": "You are Anthony."}, {"role": "user", "content": "What now?"}]
L.log_prompt_entry("ant", msgs, '{"action":"eat"}', elapsed=2.5, cached=False, purpose="brain.llm_brain.think",
                   meta={"prompt_tokens": 30, "completion_tokens": 6, "model": "llama3.1"})
time.sleep(0.01)
L.log_prompt_entry(None, [{"role": "user", "content": "Summarise the hour."}], "A quiet hour.", elapsed=1.0,
                   cached=False, purpose="llm.household_summary_narration.generate_hourly_summary")
allc = L.all_prompt_entries()
check("B: both logged, newest first, the background one under no character",
      len(allc) == 2 and allc[0]["char_id"] is None and allc[1]["char_id"] == "ant", allc)
e = allc[1]
check("B: id and sizes", e["id"] and e["prompt_chars"] == len("You are Anthony.") + len("What now?")
      and e["response_chars"] == len('{"action":"eat"}'), e)
check("B: found again by id", L.find_prompt_entry(e["id"]) is e and L.find_prompt_entry("nope") is None)

# C
w = {"ts": time.time(), "messages": msgs, "response": "ok", "elapsed_s": 1, "cached": False, "purpose": "x",
     "id": "abc123", "wake_reason": "heard_speech", "tick": 5}
L.add_prompt_entry("ant", dict(w)); L.add_prompt_entry("ant", dict(w))
check("C: a worker's entry keeps its id, once", sum(1 for x in L.get_prompt_log("ant") if x.get("id") == "abc123") == 1)
L.add_prompt_entry(L.BACKGROUND_KEY, {"ts": time.time(), "messages": [], "response": "", "purpose": "y"})
check("C: an entry without an id gets one", all(x.get("id") for x in L.all_prompt_entries()))

# D
import types
if "db" not in sys.modules:                         # no database here: the endpoints only need a load_world
    sys.modules["db"] = types.SimpleNamespace(load_world=lambda sim_id="default": {"characters": {}})
import api.llm_debug as D
D._names = lambda: {"ant": "Anthony Carter"}
fn_all = getattr(D.llm_all, "__wrapped__", D.llm_all)
fn_one = getattr(D.llm_entry, "__wrapped__", D.llm_entry)
out = fn_all()
check("D: all calls listed, named, with totals", out["count"] == 4 and out["entries"][0]["ts"] >= out["entries"][-1]["ts"]
      and any(r["name"] == "Anthony Carter" for r in out["entries"]) and any(r["name"] == "(background)" for r in out["entries"])
      and out["by_character"]["Anthony Carter"]["calls"] == 2, out)
check("D: filter by character / background / prompt",
      fn_all(char="ant")["count"] == 2 and fn_all(char="_background")["count"] == 2 and fn_all(purpose="think")["count"] == 1)
think = fn_all(purpose="think")["entries"][0]
check("D: tokens and wake reason in the row", think["prompt_tokens"] == 30 and think["completion_tokens"] == 6)
full = fn_one(think["id"])
check("D: one entry in full: messages with sizes, the reply, the meta",
      len(full["messages"]) == 2 and full["messages"][0]["chars"] == 16 and full["response"] == '{"action":"eat"}'
      and full["meta"]["model"] == "llama3.1", full)
check("D: by-id finds a worker's entry with its wake reason", fn_all(char="ant")["entries"][0]["wake_reason"] == "heard_speech")

# E: through the gate (a shared event-loop thread): the call still knows who asked and why
from llm import llm_gate
seen = {}
async def fake_call(char_id=None):
    seen.update(L.CALL_TAGS.get() or {})
    return "ok"
def think_like():
    L.set_call_tags(wake_reason="heard_speech", tick=42)
    try:
        return llm_gate.run_llm_call(fake_call(char_id="ant"), timeout=10)
    finally:
        L.set_call_tags()
r = think_like()
check("E: the call ran and carried its purpose and wake reason across",
      r == "ok" and seen.get("purpose", "").endswith(".think_like") and seen.get("wake_reason") == "heard_speech"
      and seen.get("tick") == 42, seen)
check("E: the thread's tags are cleared afterwards", L.thread_call_tags() == {})

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
