"""
A conversation ends once what was asked is answered (yes / no / later), or after MAX_LINES / MAX_TICKS
(systems/conversation_outcome.py). An answer about playing settles the play: no -> the urge is dropped, later -> both
children get a plan that becomes an urge at that time (systems/kids_play.py::start_agreed_play). A "None" SAY line is
not said (systems/text_clean.py).

Live (2026-11-01): Kathleen and Susan, 17 conversations of "wanna play?" with nothing agreed.

Run inside the backend container:   python tests/test_conversation_outcome.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from brain import intentions as intents
from brain.conversations import get_or_create_conversation, add_message
from systems import conversation_outcome as co
from systems.kids_play import start_agreed_play
from systems.text_clean import clean_utterance

# ---- reading answers -----------------------------------------------------------------------------------------------
W = {"tick": 10000, "calendar": {"hour": 15, "minute": 0, "minute_of_day": 900}}
for line, want, minutes in (
        ("Yeah, yeah! I wanna play too! But first, can I... um... get some water or something?", "yes", None),
        ("Hey Kathleen, sure, after dinner!", "later", 240),
        ("Okay, at 4:30!", "later", 90),
        ("Yes! In 20 minutes?", "later", 20),
        ("In an hour, okay?", "later", 60),
        ("Maybe later.", "later", 60),
        ("Sorry, I can't right now.", "no", None),
        ("Nah.", "no", None),
        ("No problem, let's go!", "yes", None),
        ("What kind of game did you have in mind?", None, None),
        ("Not much, you?", None, None)):
    v, t = co.read_answer(line, "declare", W, {"kathleen", "susan"})
    got_min = None if t is None else (t - W["tick"]) // 60
    check(f"{line[:45]!r} -> {want}" + (f" in {minutes} min" if minutes else ""), (v, got_min) == (want, minutes),
          str((v, got_min)))

check("a 'None' SAY line says nothing", clean_utterance("None") == "" and clean_utterance('"None."') == ""
      and clean_utterance("N/A") == "" and clean_utterance("None of your business!") == "None of your business!")


# ---- the whole conversation ---------------------------------------------------------------------------------------
def setup():
    w = make_world()
    w["tick"] = 20000
    w["calendar"] = {"year": 2026, "month": 11, "day": 1, "hour": 15, "minute": 0, "second": 0,
                     "minute_of_day": 900, "weekday": "Sunday"}
    w["conversations"] = {}
    intents.set_current_tick(w["tick"])
    k, s = w["characters"]["kathleen"], w["characters"]["susan"]
    for c in (k, s):
        c.update(memories=[], active_intentions=[], age_group="child")
    intents.add_intention(k, {"type": "play_with_friend", "category": "social", "priority": 48, "target_id": "susan",
                              "reason": "Susan Moreau lives close by"})
    conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
    conv["started_at"] = w["tick"]
    return w, k, s, conv


def say(w, conv, who, line, act="declare", dt=5):
    w["tick"] += dt
    add_message(w, conv, who, line, act, "general", w["tick"])


def has_play(c):
    return any(i.get("type") == "play_with_friend" for i in c.get("active_intentions") or [])


w, k, s, conv = setup()
say(w, conv, "kathleen", "Susan, wanna play?", "ask")
check("asking is the conversation's purpose", (conv.get("purpose") or {}).get("by") == "kathleen"
      and conv["purpose"]["about_play"])
say(w, conv, "susan", "Hmm, what game?", "ask")
check("a counter-question doesn't settle it", not conv.get("outcome"))
say(w, conv, "kathleen", "Tag!", "declare")
say(w, conv, "susan", "Sure, after dinner!", "accept")
check("'Sure, after dinner!' settles it: later", (conv.get("outcome") or {}).get("verdict") == "later")
check("... both children have the plan, for 19:00",
      all((c.get("_play_plans") or [{}])[0].get("at_tick") == w["tick"] + 4 * 3600 for c in (k, s)),
      str([c.get("_play_plans") for c in (k, s)]))
check("... and remember it", any("agreed to play at 19:00" in m["text"] for m in k["memories"])
      and any("agreed to play at 19:00" in m["text"] for m in s["memories"]))
check("... and Kathleen's urge to play right now is settled", not has_play(k))
check("the conversation is still open for a closing line", conv.get("active"))
say(w, conv, "kathleen", "Cool, see you then!", "declare")
check("the closing line ends it: resolved", not conv.get("active") and conv.get("end_reason") == "resolved")

w["tick"] = k["_play_plans"][0]["at_tick"] + 1
start_agreed_play(w)
check("at 19:00 both get the urge to play with each other",
      any(i["type"] == "play_with_friend" and i["target_id"] == "susan" for i in k["active_intentions"])
      and any(i["type"] == "play_with_friend" and i["target_id"] == "kathleen" for i in s["active_intentions"])
      and not k.get("_play_plans"))

w, k, s, conv = setup()
say(w, conv, "kathleen", "Wanna play outside?", "ask")
say(w, conv, "susan", "Sorry, I can't right now.", "decline")
check("a no settles it, and Kathleen lets the play go", conv["outcome"]["verdict"] == "no" and not has_play(k)
      and any("didn't want to play" in m["text"] for m in k["memories"]))
w["tick"] += co.CLOSE_GRACE_TICKS
co.tick(w)
check("... no closing line: it ends after the grace anyway", not conv.get("active") and conv["end_reason"] == "resolved")

w, k, s, conv = setup()
say(w, conv, "kathleen", "Wanna play?", "ask")
say(w, conv, "susan", "Yeah! Let's go!", "accept")
check("a yes now: resolved, nothing planned, the urge stays until they're together",
      conv["outcome"]["verdict"] == "yes" and not k.get("_play_plans") and has_play(k))

# ---- time limits ---------------------------------------------------------------------------------------------------
w, k, s, conv = setup()
for i in range(co.MAX_LINES):
    say(w, conv, ("kathleen", "susan")[i % 2], f"Nice weather today, number {i}.", "remark")
co.tick(w)
check(f"{co.MAX_LINES} lines and nothing settled: it ends", not conv.get("active") and conv["end_reason"] == "timed_out")

w, k, s, conv = setup()
s["activity"] = {"type": "socialize", "target_id": "kathleen", "phase": "using"}
say(w, conv, "kathleen", "So how was school?", "ask")
w["tick"] = conv["started_at"] + co.MAX_TICKS
co.tick(w)
check(f"{co.MAX_TICKS // 60} sim-minutes and nothing settled: it ends", not conv.get("active")
      and conv["end_reason"] == "timed_out")
check("... and they stop 'socializing' with each other", not s.get("activity"))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
