"""
One conversation is one sitting, kept as its own record and read by the AI (systems/conversation_archive.py):
tagged, filed under the argument it belongs to, and what's said about absent people moves the listeners' view of them
(systems/feelings.py).

Run inside the backend container:   python tests/test_conversation_archive.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
os.environ["BG_LLM_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from systems import conversation_archive as ca, conversation_outcome as co, feelings
from brain.conversations import create_conversation, add_message
from systems.room_assignment import refresh_character_room

w = make_world()
w["tick"] = 120000
k, r, j = (w["characters"][x] for x in ("kathleen", "robert", "joseph"))
for c in (k, r, j):
    c.update(relationships={}, memories=[], conversation_log=[], activity=None)
r["relationships"]["kathleen"] = {"trust": 60}
k.update(x=58, y=4, building_id="starter_house_2")
r.update(x=59, y=4, building_id="starter_house_2")
for c in (k, r):
    refresh_character_room(c, w)


def talk(lines, a=r, b=k):
    conv = create_conversation(w, [a["id"], b["id"]], topic="general")
    for who, text in lines:
        w["tick"] += 3
        add_message(w, conv, who["id"], text, "inform", "general", w["tick"])
    return conv


# ---- a conversation ends when someone leaves, and is kept as its own record -----------------------------------------
conv = talk([(r, "You left the dishes again."), (k, "I'll do them after dinner.")])
k.update(x=64, y=10)
refresh_character_room(k, w)
co.tick(w)
check("Kathleen walks off: the conversation is over (left), not paused", not conv["active"] and conv.get("end_reason") == "left",
      str((conv["active"], conv.get("end_reason"))))
entry = (w.get("conversation_archive") or {}).get(conv["id"])
check("... kept as its own record between the two of them", entry and set(entry["participants"]) == {"robert", "kathleen"}
      and entry["initiator"] == "robert" and len(entry["lines"]) == 2, str(entry))
check("... and in both their logs", any(e["id"] == conv["id"] for e in r["conversation_log"])
      and any(e["id"] == conv["id"] for e in k["conversation_log"]))
k.update(x=58, y=4)
refresh_character_room(k, w)

conv2 = talk([(r, "About the dishes..."), (k, "I said I'd do them.")])
w["tick"] += co.NO_REPLY_TICKS + 1
co.tick(w)
check("a minute with no reply ends it (no_response)", not conv2["active"] and conv2.get("end_reason") == "no_response")
check("the next talk between them is a new conversation, not the old one resumed",
      conv2["id"] != conv["id"] and len([e for e in r["conversation_log"]]) == 2)

conv3 = talk([(r, "a"), (k, "b"), (r, "c"), (k, "d"), (r, "e"), (k, "f")])
co.tick(w)
check(f"conversations are short: over at {co.MAX_LINES} lines", not conv3["active"])

# ---- the AI's tags: argument, filing, hearsay ------------------------------------------------------------------------
ca.apply_tags(w, w["conversation_archive"][conv["id"]],
              {"subject": "the dishes", "opening": "criticism", "tags": ["chores", "dishes"], "relates_to": None,
               "argument": {"type": "unmet_expectation", "subject": "the dishes", "started_by": "Robert"},
               "about_others": []})
arg = next(iter(w["arguments"].values()))
check("tagged as an argument: an argument record is opened, who started it and what kind",
      arg["type"] == "unmet_expectation" and arg["initiator"] == "robert" and arg["status"] == "open")
check("... the conversation is filed under it", conv["id"] in arg["conversation_ids"]
      and w["conversation_archive"][conv["id"]]["argument_id"] == arg["id"])
check("... both have it in their argument log", any(a["id"] == arg["id"] for a in k.get("argument_log", []))
      and any(a["id"] == arg["id"] for a in r.get("argument_log", [])))
check("... and their copies of the conversation carry the tags",
      next(e for e in k["conversation_log"] if e["id"] == conv["id"])["tags"]["opening"] == "criticism")

ca.apply_tags(w, w["conversation_archive"][conv2["id"]],
              {"subject": "the dishes again", "opening": "complaint", "tags": ["dishes"], "relates_to": conv["id"],
               "argument": {"type": "unmet_expectation", "subject": "dishes", "started_by": "Robert"},
               "about_others": []})
check("a later conversation that continues it goes under the same argument",
      conv2["id"] in arg["conversation_ids"] and len(w["arguments"]) == 1)

ca.file_fight(w, {"id": "fight_1", "tick": w["tick"], "parties": ["kathleen", "robert"], "topic": "the dishes",
                  "outcome": "storm_off", "peak": "heated_argument"})
check("a fight between them about it is filed there too", "fight_1" in arg["fight_ids"])
ca.resolve_between(w, "robert", "kathleen", "they agreed who does the dishes")
check("when they come to an understanding the argument is resolved", arg["status"] == "resolved"
      and any(a["status"] == "resolved" for a in k["argument_log"]))

conv4 = talk([(r, "Did you hear about Joseph?"), (k, "No, what?")])
w["tick"] += co.NO_REPLY_TICKS + 1
co.tick(w)
before = feelings.standing(k, "joseph")
ca.apply_tags(w, w["conversation_archive"][conv4["id"]],
              {"subject": "joseph's debts", "opening": "news", "tags": ["gossip"], "relates_to": None, "argument": None,
               "about_others": [{"name": "Joseph", "said_by": "Robert", "claim": "he stole from work", "tone": -2,
                                 "rumour": True}]})
check("gossip about Joseph: Kathleen thinks less of him", feelings.standing(k, "joseph") < before,
      str((before, feelings.standing(k, "joseph"))))
log = k["relationships"]["joseph"]["standing_log"]
check("... and her standing history with him says what she heard and from whom",
      "heard from Robert Okafor (a rumour): he stole from work" in log[-1]["cause"], str(log[-1]))
check("... Robert, who said it, isn't moved by his own gossip", "joseph" not in r["relationships"])

# ---- agitation fades ---------------------------------------------------------------------------------------------------
feelings.agitate(k, "robert", w, 60, cause="test")
w["tick"] += 2 * feelings.DAY
check("agitation fades by itself: 60, two days later 30", feelings.agitation(k, "robert", w) == 30.0,
      str(feelings.agitation(k, "robert", w)))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
