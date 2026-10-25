"""
"I remember you": a line that draws on a memory about the listener is a personal acknowledgement in the ledger
(systems/memory_acknowledgement.py).

Run inside the backend container:   python tests/test_memory_acknowledgement.py
(the last section uses the seeded fixture, see tests/determinism.py)
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from systems import memory_acknowledgement as ma
from systems import relationship_ledger as rl

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def mem(mid, text, people, importance=0.6, tags=(), kind="memory", tick=100):
    return {"id": mid, "text": text, "people": list(people), "importance": importance, "tags": list(tags), "kind": kind, "tick": tick}


def person(cid, memories=(), **extra):
    d = {"id": cid, "name": cid.title(), "age": 35, "traits": [], "memories": list(memories), "relationships": {},
         "active_intentions": [], "alive": True, "x": 1, "y": 1}
    d.update(extra)
    return d


def scene():
    ann = person("ann", [
        mem("mem_aaaaaaa1", "Bo's dog Biscuit had to be put down last spring.", ["bo"], 0.8),
        mem("mem_aaaaaaa2", "Bo was nervous about the interview on Thursday.", ["bo"], 0.5),
        mem("mem_aaaaaaa3", "Bo cheated me out of fifty dollars.", ["bo"], 0.9, tags=["grudge"]),
        mem("mem_aaaaaaa4", "Cy told me Bo is seeing someone.", ["bo", "cy"], 0.7, tags=["gossip", "rumor"]),
        mem("mem_aaaaaaa5", "Bo waved at me once.", ["bo"], 0.1),
        mem("mem_aaaaaaa6", "Cy's birthday is in June.", ["cy"], 0.7),
    ])
    bo = person("bo")
    cy = person("cy")
    w = {"tick": 100000, "characters": {c["id"]: c for c in (ann, bo, cy)}, "definitions": {},
         "conversations": {"c1": {"id": "c1", "participants": ["ann", "bo"], "history": [{}]}}}
    return ann, bo, cy, w


# ---- what is offered -------------------------------------------------------------------------------------------------------------
ann, bo, cy, w = scene()
offered = [m["id"] for m in ma.candidates(ann, "bo")]
check("memories about the listener that are fit to bring up, most important first", offered == ["mem_aaaaaaa1", "mem_aaaaaaa2"], str(offered))
check("not grudges, rumors, trivia, or memories about someone else", not ({"mem_aaaaaaa3", "mem_aaaaaaa4", "mem_aaaaaaa5", "mem_aaaaaaa6"} & set(offered)))
lines = ma.context_lines(ann, w)
check("the prompt lists them with ids", lines and "Bo" in lines[0] and "[mem_aaaaaaa1] Bo's dog Biscuit" in "\n".join(lines) and "USES" in lines[0], str(lines))
check("only while in a conversation", ma.context_lines(ann, dict(w, conversations={})) is None)
check("and only with something to offer", ma.context_lines(cy, w) is None)
w3 = dict(w, conversations={"c": {"participants": ["ann", "bo", "cy"]}})
check("a group conversation offers nothing (no single listener)", ma.context_lines(ann, w3) is None)

# ---- parsing --------------------------------------------------------------------------------------------------------------------------
check("ids are read from a USES line", ma.parse_ids("[mem_aaaaaaa1], mem_aaaaaaa2 and again mem_aaaaaaa1") == ["mem_aaaaaaa1", "mem_aaaaaaa2"])
check("garbage gives none", ma.parse_ids("none") == [] and ma.parse_ids("") == [] and ma.parse_ids(None) == [])
from brain import llm_brain
env = llm_brain._parse_compact_envelope(
    "ACTION: speak | Bo\nSAY: How is Biscuit's spot in the garden?\nUSES: [mem_aaaaaaa1]\nTHEN: keep chatting")
check("the envelope parser reads USES", env["uses"] == ["mem_aaaaaaa1"], str(env))
env2 = llm_brain._parse_compact_envelope("ACTION: speak | Bo\nSAY: Hi")
check("... and gives an empty list when there is none", env2["uses"] == [])
dec = llm_brain._to_legacy_decision(env) if hasattr(llm_brain, "_to_legacy_decision") else None
check("it reaches the speech of the decision", dec is None or dec["speech"].get("uses_memories") == ["mem_aaaaaaa1"], str(dec and dec.get("speech")))
check("the prompt asks for it", "USES:" in llm_brain.build_system_prompt({"action_types": []}))

# ---- validation ------------------------------------------------------------------------------------------------------------------------
say = "How is Biscuit's grave in the garden? I still think about that."
ok = ma.validate(ann, "bo", ["mem_aaaaaaa1"], "I was thinking about Biscuit, how are you holding up?")
check("a real memory about the listener that the line draws on holds up", [m["id"] for m in ok] == ["mem_aaaaaaa1"])
check("an invented id does not", ma.validate(ann, "bo", ["mem_deadbeef"], say) == [])
check("a memory about someone else does not", ma.validate(ann, "bo", ["mem_aaaaaaa6"], "Is it Cy's birthday in June?") == [])
check("an unfit memory does not (a grudge)", ma.validate(ann, "bo", ["mem_aaaaaaa3"], "You cheated me out of fifty dollars") == [])
check("a line with nothing of the memory in it does not", ma.validate(ann, "bo", ["mem_aaaaaaa1"], "Nice weather today, isn't it?") == [])
check("no more than three", len(ma.validate(person("x", [mem(f"mem_0000000{i}", f"Bo likes thing{i}ing", ["bo"]) for i in range(6)]), "bo",
      [f"mem_0000000{i}" for i in range(6)], "Bo, you like thing0ing thing1ing thing2ing thing3ing thing4ing")) <= ma.MAX_REFS)

# ---- into the ledger --------------------------------------------------------------------------------------------------------------------
random.seed(3)
ann, bo, cy, w = scene()
bo["relationships"]["ann"] = {"trust": 30, "friendship": 30}
got = ma.acknowledge(ann, bo, ["mem_aaaaaaa1"], "I was thinking about Biscuit, how are you holding up?", w, ref={"type": "conversation", "id": "c1"})
event_bus.flush(w)
led = rl.get_ledger(w, "ann", "bo", create=False)
check("a validated acknowledgement is emitted", [m["id"] for m in got] == ["mem_aaaaaaa1"])
entries = led["entries"] if led else []
intent = next((e for e in entries if e["layer"] == "intent"), None)
check("it is a personal acknowledgement carrying the memory ids", intent and intent["kind"] == "personal_acknowledgement" and intent["memory_refs"] == ["mem_aaaaaaa1"], str(entries))
check("the magnitude follows how much the memory mattered", intent and 6.5 <= intent["magnitude"] <= 7.5, str(intent and intent["magnitude"]))
check("the reference carries the memory text for the panel", intent and intent["ref"]["memories"][0]["text"].startswith("Bo's dog Biscuit"), str(intent and intent["ref"]))
perceived = [e for e in entries if e["layer"] == "perceived"]
check("when it registers it is positive for the pair", not perceived or (perceived[0]["polarity"] > 0 and perceived[0]["memory_refs"] == ["mem_aaaaaaa1"]))

# limits
ann, bo, cy, w = scene()
line = "I was thinking about Biscuit, how are you holding up?"
check("not when the line is meant to hurt", ma.acknowledge(ann, bo, ["mem_aaaaaaa1"], line, w, intent={"valence": "hurt"}) == [])
check("nor to deceive", ma.acknowledge(ann, bo, ["mem_aaaaaaa1"], line, w, intent={"valence": "deceive"}) == [])
check("a helpful intent is fine", len(ma.acknowledge(ann, bo, ["mem_aaaaaaa1"], line, w, intent={"valence": "help"})) == 1)
check("not again straight away", ma.acknowledge(ann, bo, ["mem_aaaaaaa2"], "Are you still nervous about the interview?", w) == [])
w["tick"] += ma.COOLDOWN_TICKS + 1
check("but after the cooldown", len(ma.acknowledge(ann, bo, ["mem_aaaaaaa2"], "Are you still nervous about the interview?", w)) == 1)
check("no ids, no acknowledgement", ma.acknowledge(ann, bo, [], line, w) == [])

# ---- the speech path -------------------------------------------------------------------------------------------------------------------------
from tests import determinism
import brain.agent_loop  # noqa: F401
from systems.action_router import apply_speech
import systems.conversation_interest as _ci

wf = determinism.fixture("2026-11-04T08:00:00")
adults = [c for c in wf["characters"].values() if (c.get("age") or 0) >= 18 and not c.get("is_workplace_npc") and not c.get("is_service_worker")]
speaker, listener = adults[0], adults[1]
for c in (speaker, listener):
    c["activity"] = None
    c["posture"] = "standing"
    c["x"], c["y"] = 5, 5
    c["building_id"] = None
speaker["relationships"].setdefault(listener["id"], {})
listener.setdefault("relationships", {}).setdefault(speaker["id"], {}).update({"trust": 60, "friendship": 50})
speaker.setdefault("memories", []).append(mem("mem_feedc0de", f"{listener['name']} is learning to play the cello.", [listener["id"]], 0.7))
_ci.check_conversation_interest = lambda *a, **k: (True, 0.8, None)
random.seed(5)
apply_speech(speaker, wf, {"target": listener["id"], "speech_act": "ask", "topic": "hobbies",
                           "utterance": "How is the cello coming along?", "uses_memories": ["mem_feedc0de", "mem_00000000"]})
event_bus.flush(wf)
led = rl.get_ledger(wf, speaker["id"], listener["id"], create=False)
kinds = [(e["kind"], e["layer"]) for e in (led["entries"] if led else [])]
check("a real spoken line that draws on a memory reaches the ledger", ("personal_acknowledgement", "intent") in kinds, str(kinds))
ack = next((e for e in led["entries"] if e["kind"] == "personal_acknowledgement" and e["layer"] == "intent"), None)
check("with only the valid id", ack and ack["memory_refs"] == ["mem_feedc0de"], str(ack and ack["memory_refs"]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
