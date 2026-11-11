"""
LLM debugging (VR "LLM log" and "Choices & tags"):
    - the decision reply's TAGS line is read; the tags are checked against the character's own (their traits plus
      what their mood brings out), at most 3 kept, others listed as not theirs; "none" means none
    - every prompt sent for a character is logged with which prompt it was, cache hits and failures included
    - the endpoints return both

Run inside the backend container:   python tests/test_llm_debug.py
"""

import asyncio
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


from brain.llm_brain import _parse_compact_envelope, _to_legacy_decision, _ENVELOPE_FORMAT

check("the reply format asks for the tags that decided it", "TAGS:" in _ENVELOPE_FORMAT and "up to 3" in _ENVELOPE_FORMAT)
env = _parse_compact_envelope("I grab a snack.\nACTION: eat | the fridge\nTHEN: rest\nTAGS: Impulsive, very curious, brave, lazy")
check("the TAGS line is read", env["tags"] == ["Impulsive", "very curious", "brave", "lazy"], str(env.get("tags")))
check("... and doesn't leak into the action", env["action"]["target_description"] == "the fridge")
dec = _to_legacy_decision(env, char_id="x")
check("... and carried on the decision", dec.get("choice_tags") == ["Impulsive", "very curious", "brave", "lazy"])
none = _parse_compact_envelope("ACTION: wait\nTAGS: none")
check("\"none\" -> no tags", none["tags"] == [])
missing = _parse_compact_envelope("ACTION: wait")
check("no TAGS line -> not said", missing["tags"] is None)

from systems.choice_tags import record
c = {"id": "x", "traits": ["impulsive", "curious"], "personality_traits": ["brave", "kind"],
     "mood": {"id": "grumpy"}, "mood_traits": {"grumpy": ["lazy"]}}
w = {"tick": 500}
e = record(c, w, dec, {"action_types": ["eat", "move", "wait"]})
check("recorded: theirs kept (fuzzy: 'very curious' -> curious), at most 3",
      e["significant"] == ["impulsive", "curious", "brave"] and len(e["significant"]) <= 3, str(e))
check("... the tags on the character (mood ones included), what was chosen from what",
      "lazy" in e["tags_on_character"] and e["chosen"]["type"] == "eat" and e["options"] == ["eat", "move", "wait"])
e2 = record(c, w, {"action": {"type": "move"}, "choice_tags": ["sneaky", "kind"]}, {})
check("a tag that isn't theirs is listed as such", e2["significant"] == ["kind"] and e2["not_theirs"] == ["sneaky"], str(e2))
e3 = record(c, w, {"action": {"type": "wait"}}, {})
check("a reply without TAGS: said = False", e3["said"] is False and e3["significant"] == [])
check("kept on the character, newest last", len(c["choice_log"]) == 3 and c["choice_log"][-1] is e3)

# the prompt log
from llm import llm_client


async def fake(messages, timeout=60.0, max_tokens=None):
    if "boom" in messages[-1]["content"]:
        raise RuntimeError("model fell over")
    return "ACTION: wait\nTAGS: none"


class FakeRedis:
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def set(self, k, v, ex=None): self.d[k] = v


llm_client._call_llm = fake
llm_client.r = FakeRedis()
llm_client.clear_prompt_log("x")


async def some_caller():
    return await llm_client.call_llm([{"role": "user", "content": "hello"}], char_id="x")

asyncio.run(some_caller())
asyncio.run(some_caller())                    # cached the second time
try:
    asyncio.run(llm_client.call_llm([{"role": "user", "content": "boom"}], char_id="x", use_cache=False))
except Exception:
    pass
log = llm_client.get_prompt_log("x")
check("every prompt for the character is logged, newest first", len(log) == 3, str([(e.get("cached"), e.get("error")) for e in log]))
check("... with which prompt it was", log[-1]["purpose"].endswith("some_caller"), log[-1]["purpose"])
check("... a cache hit too", log[1]["cached"] is True)
check("... and a failed call, with why", log[0].get("error") and "fell over" in log[0]["error"], str(log[0].get("error")))

import api.llm_debug as ld
out = ld.llm_log("x")
check("GET log: summaries with purpose, sizes, how long", out["entries"][0]["error"] and out["entries"][2]["purpose"].endswith("some_caller")
      and out["entries"][2]["prompt_chars"] == 5, str(out["entries"][2]))
one = ld.llm_log_entry("x", 2)
check("GET one entry: the messages and the reply", one["messages"][0]["content"] == "hello" and "ACTION" in one["response"])
ld.load_world = lambda sim_id="default": {"tick": 510, "characters": {"x": dict(c, name="X")}}
ch = ld.llm_choices("x")
check("GET choices: newest first, with how long ago", ch["choices"][0]["chosen"]["type"] == "wait" and ch["choices"][-1]["ago_s"] == 10
      and "lazy" in ch["tags_now"], str(ch)[:300])

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
