"""
Two fixes from a live conversation between Kathleen Okafor and Susan Moreau (2026-11-01) that was really 17 one-line
conversations, every one "ignored" or "lapsed":

A. Someone in a light activity (chatting, sitting, watching TV, ...) who is spoken to gets to decide how to answer
   (brain/agent_loop.py::LISTENING_ACTIVITIES). Before, any running activity -- "socialize" included -- skipped the
   decision step, so the listener never answered within the conversation's notice window.
B. A line goes to the person it is for (systems/addressing.py::addressee, agent_loop._direct_speech): Susan's
   "Hi, Dad, I'm really sorry..." had gone to Kathleen (nearest), starting a conversation with her.

Run inside the backend container:   python tests/test_talking.py
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
import brain.agent_loop as al
import brain.cognition_actor as ca
from brain.cognition_scheduler import wake_character
from systems.action_router import _scaffold, apply_speech
from systems.addressing import addressee

calls = []
ca.request_decision = lambda c, world, context, wake_reason, prio: calls.append((c["id"], wake_reason)) or "req"
al.build_context = lambda *a, **k: {"stub": True}


def world_with_kids():
    w = make_world()
    w["calendar"] = {"year": 2026, "month": 11, "day": 1, "hour": 15, "minute": 0, "second": 0,
                     "minute_of_day": 900, "weekday": "Sunday"}
    w["characters"]["steven"] = {"id": "steven", "name": "Steven Moreau", "first_name": "Steven",
                                 "family_name": "Moreau", "household_id": "mor", "building_id": "starter_house_3",
                                 "x": 88, "y": 7, "age": 31, "age_group": "adult", "sex": "male", "alive": True}
    w["households"]["mor"]["members"].append("steven")
    s, k = w["characters"]["susan"], w["characters"]["kathleen"]
    s.update(age=11, age_group="child", sex="female", x=83, y=5)
    k.update(age=10, age_group="child", sex="female", x=84, y=5, building_id="starter_house_3")
    return w, s, k


def busy(c, w, act_type):
    c["activity"] = _scaffold(c, w, act_type, target_id="kathleen", interaction=act_type, duration=600)
    c["activity"]["phase"] = "using"
    c.setdefault("cognition", {})["next_think_tick"] = w["tick"] + 999


# ---- A. answering while busy ---------------------------------------------------------------------------------------
w, s, k = world_with_kids()
busy(s, w, "socialize")
wake_character(s, w, "heard_speech", {"speaker_name": "Kathleen Okafor", "utterance": "Susan, wanna play?"})
calls.clear()
al.update_agent(s, w)
check("spoken to while chatting: she gets to decide what to answer", calls == [("susan", "heard_speech")], str(calls))
check("... and keeps chatting meanwhile", (s.get("activity") or {}).get("type") == "socialize")

w, s, k = world_with_kids()
busy(s, w, "sleep")
wake_character(s, w, "heard_speech", {"speaker_name": "Kathleen Okafor", "utterance": "Susan, wanna play?"})
calls.clear()
al.update_agent(s, w)
check("asleep: no decision (as before)", calls == [], str(calls))

w, s, k = world_with_kids()
busy(s, w, "socialize")
wake_character(s, w, "idle")
calls.clear()
al.update_agent(s, w)
check("chatting, not spoken to: no extra decision", calls == [], str(calls))

# ---- B. who a line is for ------------------------------------------------------------------------------------------
w, s, k = world_with_kids()
check("'Hi, Dad, ...' from Susan is for Steven (the man of her household)",
      addressee(w, s, "Hi, Dad, I'm really sorry for not hearing you earlier.") == "steven")
check("'Hey, Kathleen! ...' is for Kathleen", addressee(w, s, "Hey, Kathleen! Excuse me, can I talk to you?") == "kathleen")
check("'..., Daddy?' at the end counts too", addressee(w, s, "Can I have some water, Daddy?") == "steven")
check("a line that names nobody: None", addressee(w, s, "I wanna play too!") is None)
check("the listener the model named comes first", addressee(w, s, "Sorry!", "Kathleen Okafor") == "kathleen")
s["relationships"] = {"robert": {"kinship": "child"}}
w["characters"]["robert"].update(sex="male")
check("a real family relation beats the household guess", addressee(w, s, "Dad, look!") == "robert")
s["relationships"] = {}

speech = {"utterance": "Hi, Dad, I'm really sorry for not hearing you earlier.", "target": "kathleen", "speech_act": "apologize"}
s["perception"] = {"visible_people": [{"id": "kathleen"}]}
al._direct_speech(s, w, speech)
check("a line for Dad that was going to Kathleen goes to Steven, called out (he's not in view)",
      speech["target"] == "steven" and speech.get("mode") == "remark", str(speech))
speech = {"utterance": "Hi, Dad, I'm sorry.", "target": None, "speech_act": "apologize"}
s["perception"] = {"visible_people": [{"id": "kathleen"}, {"id": "steven"}]}
al._direct_speech(s, w, speech)
check("Steven in view: an ordinary line to him", speech["target"] == "steven" and not speech.get("mode"), str(speech))
speech = {"utterance": "Wanna play outside?", "target": "kathleen", "speech_act": "ask"}
al._direct_speech(s, w, speech)
check("a line that names nobody stays with its listener", speech == {"utterance": "Wanna play outside?", "target": "kathleen",
                                                                    "speech_act": "ask"}, str(speech))

w, s, k = world_with_kids()
w["conversations"] = {}
s["perception"] = {"visible_people": [{"id": "kathleen", "visibility": 1.0}]}
speech = {"utterance": "Hi, Dad, I'm really sorry for not hearing you earlier.", "target": None, "speech_act": "apologize"}
al._direct_speech(s, w, speech)
apply_speech(s, w, speech)
from brain.conversations import find_conversation
check("... and no conversation with Kathleen comes of it", find_conversation(w, ["susan", "kathleen"]) is None)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
