"""
CPL phase 4 (docs/cpl_implementation_plan.md section 11): more than two people, and who knows what --

  * a group conversation: three participants; one leaving doesn't end it;
  * NEXT let_join:<name>: someone nearby joins under way -- the legacy conversation takes them in, and their prompt
    shows only what was said since they joined, with a summary of what came before (their knowledge boundary);
  * overheard vs told: a line said aloud records who overheard it; a claim keeps who was told apart from who only
    overheard;
  * a text conversation runs under the text policy (hours to answer, not a minute).

Run inside the backend container:   python tests/test_cpl_groups.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import event_bus
from cpl import config, policies, record, shadow
import cpl.conversations  # noqa: F401

config.CPL_MODE = "on"


def world():
    chars = {}
    for k, x in (("theo", 10), ("ana", 11), ("mia", 13), ("bo", 60)):
        chars[k] = {"id": k, "name": k.title(), "x": x, "y": 5, "building_id": "house_1" if k != "bo" else None,
                    "cognition": {}, "relationships": {}, "perception": {"visible_people": []}}
    return {"tick": 100, "sim_time": 1000.0, "timers": [], "conversations": {}, "characters": chars}


def say(w, legacy, who, text, lines=None, act="declare"):
    w["characters"][who]["_cpl_turn"] = lines
    legacy.setdefault("history", []).append({"speaker": who, "utterance": text, "speech_act": act, "tick": w["tick"]})
    shadow.on_line(w, legacy, who, text, act)
    w["characters"][who].pop("_cpl_turn", None)
    w["tick"] += 5
    w["sim_time"] += 5
    event_bus.flush(w)


# ── a group of three; one leaves ─────────────────────────────────────────────────────────────────────────────────────
w = world()
g = {"id": "G1", "participants": ["theo", "ana", "mia"], "medium": "in_person", "active": True}
w["conversations"]["G1"] = g
say(w, g, "theo", "So, what's everyone doing tonight?")
say(w, g, "ana", "Movies, I think.")
conv = record.for_legacy(w, "G1")
check("a group conversation has all three in it", set(conv["participants"]) == {"theo", "ana", "mia"})
conv["participants"]["mia"]["status"] = "active"
say(w, g, "mia", "I have to go, see you!", "NEXT: leave:excuse")
check("one of three leaves: it carries on without them", conv["state"] == "active"
      and conv["participants"]["mia"]["status"] == "left", (conv["state"], conv["participants"]["mia"]))

# ── a late joiner ────────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
legacy = {"id": "L1", "participants": ["theo", "ana"], "medium": "in_person", "active": True, "topic": "the trip"}
w["conversations"]["L1"] = legacy
say(w, legacy, "theo", "Should we drive or take the train?", "ACT: question")
say(w, legacy, "ana", "Train, it's cheaper.", "ANSWERS: Q1 answer")
w["characters"]["ana"]["perception"]["visible_people"] = [{"id": "mia", "visibility": 1.0}]
say(w, legacy, "ana", "Mia, come over -- we're planning the trip!", "NEXT: let_join:Mia")
conv = record.for_legacy(w, "L1")
p = conv["participants"].get("mia") or {}
check("NEXT let_join:Mia -- Mia joins as she is called over (she hears that line, not the two before)",
      p.get("status") == "active" and p.get("joined_at_seq") == 2, p)
check("... the legacy conversation takes her in too", "mia" in legacy["participants"] and "mia" in legacy["joined_ticks"])
say(w, legacy, "mia", "Ooh, where to?")
from brain.context_builder import build_active_conversations
mine = next(x for x in build_active_conversations(w["characters"]["mia"], w) if x["conversation_id"] == "L1")
said = [m["utterance"] for m in mine["recent_messages"]]
check("her prompt shows only what was said since she joined", "Train, it's cheaper." not in said
      and "Ooh, where to?" in said, said)
check("... and a summary of what came before", mine.get("before_you_joined") == "2 lines so far about the trip; 1 question answered",
      mine.get("before_you_joined"))
theirs = next(x for x in build_active_conversations(w["characters"]["theo"], w) if x["conversation_id"] == "L1")
check("Theo, there from the start, still sees it all", "Train, it's cheaper." in [m["utterance"] for m in theirs["recent_messages"]]
      and not theirs.get("before_you_joined"))

# ── overheard vs told ────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
legacy = {"id": "L2", "participants": ["theo", "ana"], "medium": "in_person", "active": True}
w["conversations"]["L2"] = legacy
say(w, legacy, "theo", "Don't tell anyone, but Bo is moving away.", act="gossip")
conv = record.for_legacy(w, "L2")
heard = conv["messages"][-1]["audience"]["overheard_by"]
check("Mia, in the room, overheard the line; Bo, outside and far away, didn't", heard == ["mia"], heard)
cl = list(conv["claims"].values())[0]
check("the claim keeps who was told (Ana) apart from who only overheard it (Mia)", cl["to"] == ["ana"]
      and cl["overheard_by"] == ["mia"], cl)

# ── a text conversation ──────────────────────────────────────────────────────────────────────────────────────────────
w = world()
legacy = {"id": "T1", "participants": ["theo", "bo"], "medium": "text", "active": True}
w["conversations"]["T1"] = legacy
say(w, legacy, "theo", "Are you coming on Saturday?", "ACT: question")
conv = record.for_legacy(w, "T1")
pol = policies.from_key(conv["policy_key"])
check("a text conversation runs under the text policy (hours to answer)", conv["channel"] == "text"
      and pol["invite_s"] >= 3600 and pol["reply_s"] >= 3600, (conv["channel"], pol["invite_s"]))
check("... and nobody overhears a text", not conv["messages"][-1]["audience"].get("overheard_by"))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
