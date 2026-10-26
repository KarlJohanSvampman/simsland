"""
One conversation log object per set of people, and spoken lines without the quote marks wrapped around them
(brain/conversations.py::add_to_conversation_log, systems/text_clean.py).

Run inside the backend container:   python tests/test_conversation_log.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from brain import conversations as cv
from systems.text_clean import clean_utterance

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---- quote marks ----------------------------------------------------------------------------------------------------------------
check("a line in quotes loses them", clean_utterance('"How\'s the morning going, Noor?"') == "How's the morning going, Noor?")
check("so does one wrapped again and again", clean_utterance('"""How\'s the morning going, Noor?"""') == "How's the morning going, Noor?")
check("unbalanced runs too", clean_utterance('"Okay, I\'ll get the kids to school on time today.""') == "Okay, I'll get the kids to school on time today.")
check("curly quotes", clean_utterance("“Hello there”") == "Hello there")
check("a line that quotes somebody is left alone", clean_utterance('"Hi," she said, "bye."') == '"Hi," she said, "bye."')
check("a line with nothing to remove, or nothing at all", clean_utterance("Just a line.") == "Just a line." and clean_utterance("") == "" and clean_utterance(None) == "")
check("an apostrophe is not a quote", clean_utterance("'Tis the season") == "'Tis the season")


# ---- the log ------------------------------------------------------------------------------------------------------------------------------
def person(cid, name):
    return {"id": cid, "name": name, "conversation_log": []}


def conv(cid, a, b, lines, tick, medium="in_person", topic="general"):
    return {"id": cid, "participants": [a["id"], b["id"]], "medium": medium, "topic": topic, "started_at": tick, "last_update": tick + 30,
            "active": False,
            "history": [{"speaker": s, "utterance": u, "speech_act": "declare", "tick": tick + i} for i, (s, u) in enumerate(lines)]}


karim, noor, lena = person("karim", "Karim"), person("noor", "Noor"), person("lena", "Lena")
w = {"tick": 5000, "characters": {c["id"]: c for c in (karim, noor, lena)}}
cv._archive_conversation(w, conv("c1", karim, noor, [("karim", '"How\'s the morning going, Noor?"')], 100))
cv._archive_conversation(w, conv("c2", karim, noor, [("karim", '""How\'s the morning going, Noor?""')], 200))
cv._archive_conversation(w, conv("c3", karim, noor, [("karim", '"""How\'s the morning going, Noor?"""'), ("noor", "Fine, thanks Dad.")], 300))
cv._archive_conversation(w, conv("c4", karim, lena, [("karim", "Morning, love.")], 400))
cv._archive_conversation(w, conv("c5", noor, karim, [("noor", "Dad, can we play?")], 500, medium="call"))

log = karim["conversation_log"]
with_noor = [e for e in log if {p["id"] for p in e["with"]} == {"noor"}]
check("all conversations with the same person are one object", len(with_noor) == 1 and len(log) == 2, str([(e["with"], e["conv_ids"]) for e in log]))
e = with_noor[0]
check("it knows which conversations it holds", e["conv_ids"] == ["c1", "c2", "c3", "c5"], str(e["conv_ids"]))
check("the same line said again is one line, said three times", [l["utterance"] for l in e["lines"]][:2] == ["How's the morning going, Noor?", "Fine, thanks Dad."]
      and e["lines"][0].get("repeats") == 3, str(e["lines"]))
check("with all the lines in order, from every conversation", [l["utterance"] for l in e["lines"]] == ["How's the morning going, Noor?", "Fine, thanks Dad.", "Dad, can we play?"])
check("each line remembers which conversation it was from", [l["conv_id"] for l in e["lines"]] == ["c1", "c3", "c5"], str([l["conv_id"] for l in e["lines"]]))
check("started at the first, ended at the last", e["started_tick"] == 100 and e["ended_tick"] == 530, f"{e['started_tick']} {e['ended_tick']}")
check("mediums are all listed, the latest as the main one", e["mediums"] == ["in_person", "call"] and e["medium"] == "call", str(e.get("mediums")))
check("the other person's side has the same single thread", len(noor["conversation_log"]) == 1 and len(noor["conversation_log"][0]["lines"]) == 3)
check("a different person is a different object", len([e for e in log if {p["id"] for p in e["with"]} == {"lena"}]) == 1)

# entries written before this (one per conversation) are folded together
old = person("old", "Old")
old["conversation_log"] = [
    {"conv_id": f"o{i}", "started_tick": i * 10, "ended_tick": i * 10 + 5, "medium": "in_person", "topic": "general",
     "with": [{"id": "x", "name": "X"}], "lines": [{"speaker": "x", "utterance": f'"line {i}"', "speech_act": "declare", "tick": i * 10}]}
    for i in range(4)]
cv.add_to_conversation_log(old, {"conv_id": "o9", "started_tick": 90, "ended_tick": 95, "medium": "in_person", "topic": "general",
                                 "with": [{"id": "x", "name": "X"}], "lines": [{"speaker": "x", "utterance": "last", "speech_act": "declare", "tick": 90}]})
check("older separate entries become one thread", len(old["conversation_log"]) == 1 and len(old["conversation_log"][0]["lines"]) == 5, str(len(old["conversation_log"])))
check("with their quote marks cleaned", old["conversation_log"][0]["lines"][0]["utterance"] == "line 0")

# a group conversation is its own thread, and the log is capped
g = person("g", "G")
for i in range(cv.CONVERSATION_LOG_CAP + 10):
    cv.add_to_conversation_log(g, {"conv_id": f"g{i}", "started_tick": i, "ended_tick": i, "medium": "in_person", "topic": "general",
                                   "with": [{"id": f"p{i}", "name": "P"}], "lines": [{"speaker": "p", "utterance": "hi", "tick": i}]})
check("the log is still capped at the number of different people", len(g["conversation_log"]) == cv.CONVERSATION_LOG_CAP)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
