"""
Memory debugging (systems/memory_trace.py): stores, recalls (short- and long-term, who asked), commits to long-term,
aggregations and forgetting are each noted on the character, and /admin/memtrace returns them.

Run inside the backend container:   python tests/test_memory_trace.py
"""
import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from brain.memory import store_memory, recall, recall_relevant, recall_with_filters, prune_memories
import systems.memory_consolidation as mc

c = {"id": "x", "name": "X", "memories": [], "long_term_memory": []}
w = {"tick": 10000, "characters": {"x": c}}


def a_caller():
    return store_memory(c, "Had coffee with Ann at the cafe", importance=0.6, tick=9000)

a_caller()
for i in range(4):
    store_memory(c, f"Routine thing {i} at home", importance=0.2, tick=9100 + i)
kinds = [e["kind"] for e in c["memory_trace"]]
check("each store is noted as a short-term write, with who stored it", kinds == ["stm_write"] * 5
      and c["memory_trace"][0]["by"].endswith("a_caller") and c["memory_trace"][0]["tick"] == 9000, str(c["memory_trace"][0]))
got = recall_relevant(c, "coffee Ann", 3, world=w)
e = c["memory_trace"][-1]
check("a recall is ONE short-term read (recall_relevant -> recall), with what came back and the query",
      e["kind"] == "stm_read" and e["n"] == len(got) and e["query"] == "coffee Ann" and [x["kind"] for x in c["memory_trace"]].count("stm_read") == 1, str(e))

c["long_term_memory"].append({"id": "ltm_1", "text": "A day at the beach with Ann", "tick": 100, "tags": ["highlights"]})
recall_with_filters(c, w, location="beach", limit=6)        # only long-term has it
ks = [x["kind"] for x in c["memory_trace"][-2:]]
check("recalling long-term memories is noted as a long-term read", "ltm_read" in ks, str(ks))

# consolidation
c["_last_memory_consolidation_tick"] = w["tick"] - mc.CONSOLIDATION_INTERVAL_TICKS - 1
w["tick"] = 9100 + 3600
mc._summarize = lambda c_, mems: "A quiet hour at home and coffee with Ann."
before = len(c["memory_trace"])
mc.maybe_consolidate_memories(c, w)
new = c["memory_trace"][before:]
check("an aggregation is noted (how many folded, the summary) and the commit to long-term",
      any(x["kind"] == "aggregation" and "folded" in x.get("detail", "") and x.get("summary") for x in new)
      and any(x["kind"] == "ltm_commit" for x in new), str([(x["kind"], x.get("detail")) for x in new]))

mc._summarize = lambda c_, mems: None
for i in range(3):
    store_memory(c, f"Another thing {i}", importance=0.2, tick=w["tick"] + 10 + i)
c["_last_memory_consolidation_tick"] = w["tick"] - mc.CONSOLIDATION_INTERVAL_TICKS - 1
w["tick"] += 100
mc.maybe_consolidate_memories(c, w)
check("an aggregation that failed is noted as failed", c["memory_trace"][-1]["kind"] == "aggregation" and c["memory_trace"][-1].get("failed"))

# forgetting
for m in c["memories"]:
    m["drop_probability"] = 100
    m["tick"] = 0
c["_last_memory_forget_tick"] = 0
w["tick"] = 100000
mc.maybe_forget_short_term(c, w)
check("random forgetting is noted, with what was forgotten", c["memory_trace"][-1]["kind"] == "forget"
      and c["memory_trace"][-1]["why"] == "random forgetting" and c["memory_trace"][-1]["n"] > 0)
for i in range(12):
    store_memory(c, f"Filler {i}", importance=0.1, tick=w["tick"] + i)
prune_memories(c, max_memories=5)
check("pruning over the cap is noted as forgetting", any(x["kind"] == "forget" and "cap" in x.get("why", "") for x in c["memory_trace"][-3:]))

import api.memory_trace as mt
mt.load_world = lambda sim_id="default": w
out = mt.memtrace("x")
check("GET memtrace: events oldest first, sizes, kind names", out["events"][0]["kind"] == "stm_write" and out["short_term"] == len(c["memories"])
      and "ltm_commit" in out["kinds"])
check("... ?since only newer", all(e["tick"] > 99999 for e in mt.memtrace("x", since=99999)["events"]))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
