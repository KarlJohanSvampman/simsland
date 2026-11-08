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

# ---- picked up again within the minute: the same conversation ----------------------------------------------------------
from brain.conversations import get_or_create_conversation, REOPEN_TICKS
from systems.conversation_floor import _end
c5 = talk([(r, "Can you help me with the shelf?")])
_end(w, c5, "ignored")
w["tick"] += 10
again = get_or_create_conversation(w, ["robert", "kathleen"])
check("asked again a few seconds later: the same conversation carried on, not a new one",
      again["id"] == c5["id"] and again["active"] and c5["id"] not in w["conversation_archive"])
check("... and it's not in their logs twice", sum(1 for e in r["conversation_log"] if e["id"] == c5["id"]) == 0)
_end(w, again, "no_response")
w["tick"] += REOPEN_TICKS + 5
later = get_or_create_conversation(w, ["robert", "kathleen"])
check("a minute later it is a new conversation", later["id"] != c5["id"])
_end(w, later, "no_response")

# ---- the subject is kept on the conversation --------------------------------------------------------------------------
from brain.conversations import set_subject
c6 = create_conversation(w, ["robert", "kathleen"], topic="general")
set_subject(c6, "general")
check("'general' is not a subject", not c6.get("subject"))
set_subject(c6, "cleaning her room", by="kathleen")
set_subject(c6, None)
check("once it's about cleaning her room it stays that, until someone changes it", c6["subject"] == "cleaning her room")
_end(w, c6, "no_response")

# ---- the AI's reading: issues, positions, gossip --------------------------------------------------------------------------
from social import issues as I, standing, rumours as R
ca.apply_tags(w, w["conversation_archive"][conv["id"]],
              {"subject": "the dishes", "opening": "criticism", "tags": ["chores", "dishes"], "interaction_tags": ["criticism"],
               "tone": "tense", "relates_to": None,
               "issues": [{"same_as": None, "subject": "the dishes", "category": "household_responsibility",
                           "raised_by": "Robert", "between": ["Robert", "Kathleen"],
                           "positions": {"Robert": {"position": "She never does them", "stance": "opposed"},
                                         "Kathleen": {"position": "I do them after dinner", "stance": "opposed"}},
                           "status": "open"}],
               "confrontation": None, "agreement": None, "violations": [], "initiative_response": "accepted_reluctantly",
               "standing_events": [], "about_others": [], "told_about_themselves": []})
iss = I.between(w, "robert", "kathleen")
check("an issue is opened, with each one's own position", len(iss) == 1 and I.position(iss[0], "robert")["position"]
      == "She never does them" and I.position(iss[0], "kathleen")["position"] == "I do them after dinner")
check("... the conversation is filed under it", conv["id"] in iss[0]["conversation_ids"]
      and iss[0]["id"] in w["conversation_archive"][conv["id"]]["issue_ids"])
check("... and their copies of the conversation carry the reading",
      next(e for e in k["conversation_log"] if e["id"] == conv["id"])["tags"]["opening"] == "criticism")
ca.apply_tags(w, w["conversation_archive"][conv2["id"]],
              {"subject": "the dishes again", "opening": "complaint", "tags": ["dishes"], "interaction_tags": [],
               "tone": "tense", "relates_to": conv["id"],
               "issues": [{"same_as": iss[0]["id"], "subject": "dishes", "category": "household_responsibility",
                           "raised_by": "Robert", "between": [], "positions": {}, "status": "open"}],
               "confrontation": None, "agreement": None, "violations": [], "initiative_response": None,
               "standing_events": [], "about_others": [], "told_about_themselves": []})
check("a later conversation on it goes under the same issue", conv2["id"] in iss[0]["conversation_ids"]
      and len(I.between(w, "robert", "kathleen")) == 1)

conv4 = talk([(r, "Did you hear about Joseph?"), (k, "No, what?")])
w["tick"] += co.NO_REPLY_TICKS + 1
co.tick(w)
before = standing.score(k, "joseph")
ca.apply_tags(w, w["conversation_archive"][conv4["id"]],
              {"subject": "joseph's debts", "opening": "news", "tags": ["gossip"], "interaction_tags": ["gossip"],
               "tone": "neutral", "relates_to": None, "issues": [], "confrontation": None, "agreement": None,
               "violations": [], "initiative_response": None, "standing_events": [],
               "about_others": [{"name": "Joseph", "said_by": "Robert", "claim": "he stole from work", "tone": -2,
                                 "rumour": True, "same_as": None}], "told_about_themselves": []})
check("gossip about Joseph: Kathleen thinks less of him", standing.score(k, "joseph") < before,
      str((before, standing.score(k, "joseph"))))
log = k["relationships"]["joseph"]["standing_log"]
check("... her history with him says what she heard and from whom",
      "heard from Robert Okafor (a rumour): he stole from work" in log[-1]["cause"], str(log[-1]))
check("... it's a rumour she now knows, from Robert", any(r_["subject_id"] == "joseph" for r_ in R.known_by(w, "kathleen", 0.0)))
check("... Robert, who said it, isn't moved by his own gossip", "joseph" not in r["relationships"])

# ---- agitation fades ---------------------------------------------------------------------------------------------------
feelings.agitate(k, "robert", w, 50, cause="test")
a0 = feelings.agitation(k, "robert", w)
w["tick"] += 2 * 86400
check("how worked up she is fades by itself: 30 down in two days", feelings.agitation(k, "robert", w) == max(0.0, round(a0 - 30, 1)),
      str(feelings.agitation(k, "robert", w)))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
