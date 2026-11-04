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
check("one conversation is one sitting: each talk with Noor is its own entry", len(with_noor) == 4 and len(log) == 5,
      str([(e["with"], e["id"]) for e in log]))
check("... in order", [e["id"] for e in with_noor] == ["c1", "c2", "c3", "c5"])
check("... a line keeps its words, quote marks cleaned at the source", with_noor[0]["lines"][0]["utterance"].strip('"') == "How's the morning going, Noor?")
check("... the medium is the conversation's own", with_noor[-1]["medium"] == "call" and with_noor[0]["medium"] == "in_person")
check("the other person has the same entries", len(noor["conversation_log"]) == 4)
check("a different person is a different entry", len([e for e in log if {p["id"] for p in e["with"]} == {"lena"}]) == 1)
check("each is in the archive once", len(w["conversation_archive"]) == 5)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
