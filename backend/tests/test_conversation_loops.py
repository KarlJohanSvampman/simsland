"""
Conversations that go in circles (systems/conversation_loops.py; live 2026-11-28: 13 of 18 conversations restated a
line from just before -- "clean it up together, like we said" -- mostly about the same mess).

A. Echo: real live restatements are caught; ordinary back-and-forth isn't.
B. on_line: an echo is flagged and counted; the second ends the conversation ("going_in_circles").
C. Settled: an offer (compromise / suggestion / deal) the other agrees to is settled for the conversation.
E. Sooner: one topic line after line gets a nudge then ends it; going back to an agreed topic is an echo; once agreed
   and nothing new comes up, it ends a couple of lines later ("agreed"); a new topic keeps it going.
D. The acts: a settled topic is dropped; a topic talked through with them in an earlier conversation in the last few
   hours scores much lower; the prompt says it's going in circles / what's already agreed.

Run inside the backend container:   python tests/test_conversation_loops.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import systems.conversation_loops as L

# A: real lines (live 2026-11-28)
echo_pairs = [
    ("Alexander, I don't think we should just leave it, Chris. Why don't we clean it up together now, so it's not just one person's job?",
     "Yeah, it's not fair to leave it like that. We said we'd clean it up together, and I think we should do it now."),
    ("Rachel, let's be honest, you agreed to clean your own space, and it's still a mess.",
     "Rachel, let's be honest, we both agreed to clean each other's spaces, but I haven't seen your space clean."),
]
plain_pairs = [
    ("Hey, Chris, what happened to the trash?", "Uh, I think I might have forgotten to put it out after dinner."),
    ("Daniel, can I ask you something about dinner plans? I'm still not sure what we're having.",
     "I was thinking pasta, but we're out of tomatoes, so maybe we pick some up on the way home."),
    ("How was work today? You look exhausted.", "Long day. The new manager keeps changing the schedule on us."),
]
for a, b in echo_pairs:
    check(f"A: echo caught ({L.similarity(a, b):.2f}): {b[:50]}...", L.similarity(a, b) >= L.ECHO_SIM)
for a, b in plain_pairs:
    check(f"A: ordinary reply not an echo ({L.similarity(a, b):.2f}): {b[:40]}...", L.similarity(a, b) < L.ECHO_SIM)

# B
ended = []
import systems.conversation_outcome as CO
CO.end = lambda world, conv, reason: (ended.append(reason), conv.update(active=False))
world = {"tick": 10}
conv = {"active": True, "history": []}
def say(who, text, act=None, topic=None):
    conv["history"].append({"speaker": who, "utterance": text, "conv_act": act, "conv_topic": topic})
    return L.on_line(world, conv, who, text, act, topic)
say("a", "We should clean the dining room together tonight and split the dishes between us.")
check("B: a new line isn't an echo", say("b", "Okay, but I have homework first, can we start at eight?") is None)
check("B: restating it is an echo", say("a", "So we clean the dining room together tonight and split the dishes, like I said.") == "echo"
      and conv["history"][-1].get("echo") and conv["echo_count"] == 1)
check("B: the prompt says it's going in circles", any("going in circles" in l for l in L.prompt_line(conv)))
r = say("b", "Right, we clean the dining room together tonight and split the dishes between us.")
check("B: the second echo ends it", r == "ended" and ended == ["going_in_circles"], (r, ended))

# C
conv = {"active": True, "history": []}
say("a", "How about you take the dishes and I take the laundry this week?", act="compromise", topic="the chores")
r = say("b", "Deal, that works for me.")
check("C: an offer agreed to is settled", r == "settled" and L.settled(conv, "the chores"), conv.get("settled_topics"))
check("C: the prompt says it's already agreed", any("Already agreed: the chores" in l for l in L.prompt_line(conv)))

check("C: a counter-offer isn't a yes", not L.agrees("Okay, but what if we alternate weeks instead?")
      and not L.agrees("I think a compromise could be to take turns doing the laundry each week."))
check("C: a plain yes is", L.agrees("Deal, that works for me.") and L.agrees("Yeah, okay, let's do that tonight."))

# E: live 2026-11-28 -- compromise after compromise about the laundry, each a paraphrase
ended.clear()
conv = {"active": True, "history": []}
lines = ["Let's figure out a way to split up the laundry tasks so neither of us is drowning.",
         "I think we should alternate weeks for laundry, one week you, one week me.",
         "Honestly, setting aside extra time each week for the backlog might help most.",
         "Maybe a shared calendar for chores, with laundry on Sundays, would keep us honest.",
         "What if the kids folded their own clothes and we only did the washing part?",
         "Or we could hire someone once a month just to catch up on everything."]
rs = []
for i, t in enumerate(lines):
    rs.append(say("ab"[i % 2], t, act="compromise", topic="the laundry"))
    if i == 3:
        check("E: four lines on one topic -> told to land on something", any("back and forth about the laundry" in l
              for l in L.prompt_line(conv)), L.prompt_line(conv))
check("E: six lines on one topic with nothing agreed ends it", rs[-1] == "ended" and ended == ["going_in_circles"], (rs, ended))

ended.clear()
conv = {"active": True, "history": []}
say("a", "How about you take the dishes and I take the laundry this week?", act="suggest", topic="the chores")
say("b", "Deal, that works for me.")
r = say("a", "Okay so we split the chores like that, you on dishes and me on laundry, everything fair.", act="compromise", topic="the chores")
check("E: going back to an agreed topic is an echo", conv["history"][-1].get("echo") and conv["echo_count"] == 1, conv["history"][-1])

ended.clear()
conv = {"active": True, "history": []}
say("a", "How about you take the dishes and I take the laundry this week?", act="suggest", topic="the chores")
say("b", "Deal, that works for me.")
check("E: one more line after agreeing is fine", say("a", "Great. Thanks, love.") is None and not ended)
r = say("b", "See you at dinner then.")
check("E: agreed and nothing new -> ends ('agreed')", r == "ended" and ended == ["agreed"], (r, ended))

ended.clear()
conv = {"active": True, "history": []}
say("a", "How about you take the dishes and I take the laundry this week?", act="suggest", topic="the chores")
say("b", "Deal, that works for me.")
say("a", "By the way, are you still going to the game on Saturday?", act="inquiry", topic="the game on Saturday")
r = say("b", "Yes, I got the tickets yesterday, front row behind the bench.")
check("E: a new topic after agreeing keeps it going", r is None and not ended, (r, ended))

# D
import systems.conversation_acts as A
import core.clock as clock
clock.now_ts = lambda w: 10000.0
A._now = lambda w: 10000.0
me = {"id": "a", "name": "Rachel Martinez", "traits": [], "emotional_temperature": 60, "emotion": "annoyed", "stress": 40,
      "relationships": {"d": {"friendship": 10, "trust": 10, "respect": 10}},
      "grievances": [{"caused_by": "d", "event_type": "left_mess", "weight": 12}]}
dan = {"id": "d", "name": "Daniel Martinez"}
w = {"tick": 0, "characters": {"a": me, "d": dan}, "social_issues": {}, "conversations": {}}
base = A.score(me, dan, w)
check("D: the grievance gives a criticism about the mess", "criticism" in base and "mess" in base["criticism"][1], base.get("criticism"))
w["conversations"] = {"cv": {"active": True, "participants": ["a", "d"], "history": [],
                             "settled_topics": {"the mess left lying around": 1}}}
check("D: settled in this conversation -> dropped", "criticism" not in A.score(me, dan, w))
w["conversations"] = {}
me["talk_topics"] = {"d": [{"topic": "the mess left lying around", "last_ts": 10000.0 - 3600, "times": 3}]}
later = A.score(me, dan, w)
check("D: talked through an hour ago -> much less likely", later["criticism"][0] < base["criticism"][0] * 0.5, (base["criticism"], later["criticism"]))
me["talk_topics"]["d"][0]["last_ts"] = 10000.0 - 5 * 3600
check("D: five hours later it can come up again", A.score(me, dan, w)["criticism"][0] == base["criticism"][0])
w["conversations"] = {"cv": {"active": True, "participants": ["a", "d"], "history": [
    {"speaker": "a", "conv_act": "criticism"}, {"speaker": "d"}, {"speaker": "a", "conv_act": "criticism"}]}}
me.pop("talk_topics")
check("D: the same act twice running -> a third is less likely", A.score(me, dan, w)["criticism"][0] < base["criticism"][0] * 0.7)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
