"""
Loops seen live (2026-11-21, video "wtflloop"):

  A. Rebecca alternated "move to the chair_modern_a" / "examine the chair_modern_a" for minutes. Her decisions'
     "Your recent turns" never changed -- think() appended each turn to a COPY of the session that was never written
     back -- so the same moment made the same prompt, and the 5-minute reply cache handed back the same answer.
     Now: on_decision_ready notes the turn in c["_llm_session"]; decisions skip the reply cache; going back and
     forth between two things is called out in the history.
  B. A parent reminded a child about the toilet ten times a minute: the need was still over its threshold right after
     the reminder, so a new "remind child" went up at once. Now a reminded need waits REMIND_AGAIN_AFTER_TICKS, and
     isn't raised while the child is already seeing to it.

Run inside the backend container:   python tests/test_loops.py
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


from brain import llm_brain as lb  # noqa: E402

# ── A: history ──────────────────────────────────────────────────────────────────────────────────────────────────────
move = {"thought": "I head toward the chair.", "action": {"type": "move", "target_description": "the chair"}}
exam = {"thought": "I take a closer look at the chair.", "action": {"type": "examine", "target_description": "the chair"}}
session = {"history": []}
for d in (move, exam, move, exam, move):
    lb._append_history(session, d)
rendered = [lb._render_history_entry(h) for h in session["history"]]
check("back and forth is called out", "back and forth, 3 times" in rendered[-1] and "back and forth, 2 times" in rendered[-2],
      rendered)
s2 = {"history": []}
for d in (move, move, move):
    lb._append_history(s2, d)
check("a run still collapses (×3 in a row)", len(s2["history"]) == 1 and "×3 in a row" in lb._render_history_entry(s2["history"][0]))

from house_world import make_world  # noqa: E402
from brain import cognition_actor as ca  # noqa: E402
w = make_world()
k = w["characters"]["kathleen"]
k["cognition"] = {"pending": {"id": "r1", "tick": 5, "wall": 0, "wake_reason": "idle", "wake_seq": 0}}
k.pop("_llm_session", None)
try:
    ca.on_decision_ready({"character_id": "kathleen", "request_id": "r1", "tick": 5, "decision": exam}, w)
except Exception:
    pass                                    # acting on it needs more world than this; the history note comes first
hist = (k.get("_llm_session") or {}).get("history") or []
check("the decision is noted in the character's own session (the next prompt's recent turns)",
      hist and "closer look at the chair" in hist[-1]["text"], hist)

import inspect  # noqa: E402
src = inspect.getsource(lb.think)
check("a decision does not use the reply cache", "use_cache=False" in src)

# ── B: reminders ────────────────────────────────────────────────────────────────────────────────────────────────────
from systems import child_care as cc  # noqa: E402
child = {"id": "alex", "activity": None, "active_intentions": []}
w["tick"] = 10000
check("never reminded: may be reminded", not cc._recently_reminded(child, w, "bladder"))
child["_reminded"] = {"bladder": 9900}
check("reminded a moment ago: not again", cc._recently_reminded(child, w, "bladder"))
w["tick"] = 9900 + cc.REMIND_AGAIN_AFTER_TICKS
check("... until the wait is over", not cc._recently_reminded(child, w, "bladder"))
child["active_intentions"] = [{"type": "go_to_toilet"}]
check("on the way to the toilet already: no reminder", cc._recently_reminded(child, w, "bladder"))
child["active_intentions"] = []
child["activity"] = {"type": "sleep"}
check("asleep: no reminder about being tired", cc._recently_reminded(child, w, "fatigue"))

# ── C: a decision request lost with an earlier run of the process ──────────────────────────────────────────────────
import time as _time  # noqa: E402
k["cognition"] = {"pending": {"id": "old", "tick": 1, "wall": ca.PROCESS_STARTED - 5, "wake_reason": "idle"}}
k.pop("_ai_blackout", None)
check("a request from before this process started is dropped at once", ca.is_waiting(k, w) is False
      and k["cognition"]["pending"] is None)
check("... and doesn't count against them as the model failing (no blackout)", not k.get("_ai_blackout"))
k["cognition"] = {"pending": {"id": "new", "tick": 1, "wall": _time.time(), "wake_reason": "idle"}}
check("a fresh request is still waited for", ca.is_waiting(k, w) is True)

# ── D: a reply that only talks is a turn spent talking, not a model failure (no blackout) ───────────────────────────
env = lb._parse_compact_envelope('SAY: "Margaret, I\'m warning you, I\'m not going to drop this."')
check("a SAY-only reply is a turn: wait + the line", env and env["action"]["type"] == "wait" and "warning you" in env["say"], env)
env = lb._parse_compact_envelope('REMARK: "This isn\'t over yet, Patrick."')
check("a REMARK-only reply too", env and env["remark"].startswith("This isn't over"), env)
env = lb._parse_compact_envelope("What's wrong, Rach?")
check("bare words ending in a question are what they say", env and env["say"] == "What's wrong, Rach?", env)
check("plain narration is still not taken for speech", lb._parse_compact_envelope("I walk over to the sink.") is None)

# ── E: drinking / eating through a plain "interact" does what drinking / eating does ────────────────────────────────
from systems import activities as A  # noqa: E402
check("interact-drink counts as drinking, interact-eat as eating", A._INTERACT_AS == {"drink": "drink", "eat": "eat"})

# ── F: a whole sentence said twice to the same person is dropped, even while answering ─────────────────────────────
from cpl import participants as P  # noqa: E402
P.answering = lambda c, world, target_id: True
spk = {"id": "m", "speech_log": [{"tick": 100, "target": "p", "utterance": "I wish I'd met you before, you'd have loved it."}]}
ww = {"tick": 200}
check("a long line repeated is dropped even when answering",
      P.repeat_dropped(spk, ww, "I wish I'd met you before, you'd have loved it.", "p"))
spk["speech_log"].append({"tick": 150, "target": "p", "utterance": "Okay!"})
check("... a short stock answer may be said again", not P.repeat_dropped(spk, ww, "Okay!", "p"))

# ── G: replies that copy the format's <placeholders> are thrown away and asked again, never shown ──────────────────
echo1 = "<what you do, ONLY if it's worth describing -- skip this line for a routine action, don't narrate every single move>\nACTION: examine | a piece of fruit | it's an apple"
echo2 = "<what I do>"
echo3 = "<move> | towards Patrick Moore | I want to talk to him"
fine = "I pick a banana from the counter.\nACTION: eat | a banana on the kitchen counter |\nREMARK: Ugh."
check("placeholder copies are spotted", lb._echoes_template(echo1) and lb._echoes_template(echo2))
check("a real reply isn't", not lb._echoes_template(fine) and not lb._echoes_template("SAY: I love you <3"))
env = lb._parse_compact_envelope(lb._strip_template_echo(echo1))
check("cut out, the rest still reads -- and the placeholder never becomes the thought",
      env and env["action"]["type"] == "examine" and "worth describing" not in (env.get("narration") or ""), env)
env = lb._parse_compact_envelope(lb._strip_template_echo(echo3))
check("a real line wrapped in <...> is unwrapped", env and env["action"]["type"] == "move" and "Patrick" in env["action"]["target_description"], env)
env = lb._parse_compact_envelope(lb._strip_template_echo('<SAY: "Sorry, Christopher, but I think you should leave."'))
check("... a <SAY: ...> too", env and "you should leave" in env["say"], env)
src2 = inspect.getsource(lb.think)
check("think() asks again when the reply copies the template", "_echoes_template(raw)" in src2 and "_TEMPLATE_ECHO_RETRY" in src2)

# ── H: an AI-blackout episode fades once the AI answers again; a preempted call is not a failure ───────────────────
from systems import ai_blackout as AB  # noqa: E402
w["tick"] = 100000
ch = {"id": "kathleen", "name": "Kathleen", "memories": [],
      "psychosis_state": {"active": True, "trigger": "ai_blackout", "intensity": 1.0, "last_grow": 100000, "incident_id": "inc_x"},
      "_ai_blackout": {"since": 90000, "last": 99990, "failures": 5}}
w["characters"]["kathleen"] = ch
w["tick"] = 100060
AB._grow(ch, w)
check("still failing: it keeps growing (stays at the top)", ch["psychosis_state"]["intensity"] == 1.0)
ch.pop("_ai_blackout")
w["tick"] = 100060 + 600
AB._grow(ch, w)
check("the AI answering again: it fades", 0.45 <= ch["psychosis_state"]["intensity"] <= 0.55, ch["psychosis_state"])
w["tick"] += 900
AB._grow(ch, w)
check("... and ends", not AB.in_episode(ch), ch["psychosis_state"])
src3 = inspect.getsource(__import__("brain.agent_loop", fromlist=["x"]).process_decision)
check("a call cancelled for a more urgent one doesn't count as a blackout", "cancelled to make room" in src3)
src4 = inspect.getsource(lb.think)
check("a reply with no ACTION line is asked for again before anything else", "_NO_ACTION_RETRY" in src4)

# ── I: socializing needs someone to socialize with, awake ──────────────────────────────────────────────────────────
from systems.social import why_cant_talk  # noqa: E402
check("no target: can't socialize", why_cant_talk(None) == "nobody")
check("napping counts as asleep (Rachel 'socialized' with napping Daniel)", why_cant_talk({"activity": {"type": "nap"}}) == "asleep")
check("asleep / away / fine", why_cant_talk({"activity": {"type": "sleep"}}) == "asleep"
      and why_cant_talk({"off_grid": True}) == "away" and why_cant_talk({"activity": {"type": "eat"}}) is None)
from systems import activities as A2  # noqa: E402
w["tick"] = 70000
w["characters"]["dan"] = {"id": "dan", "x": 1, "y": 1, "building_id": "h", "activity": {"type": "nap"}}
rach = {"id": "rach", "x": 1, "y": 2, "building_id": "h"}
check("a chat partner who dozes off ends the chat at once",
      A2._socialize_partner_gone(rach, w, {"type": "socialize", "phase": "using", "target_id": "dan"}))

# ── J: doorbell messages end (Rachel carried one for 22 hours, "This cannot wait any longer") ───────────────────────
from systems import doorbell as DB  # noqa: E402
w["tick"] = 200000
w["characters"].update(vis={"id": "vis", "household_id": "h2", "building_id": None},
                       dad={"id": "dad", "household_id": "h1", "building_id": "house"})
me = {"id": "me", "active_intentions": [
    {"type": "relay_door_visitor_vis", "target_id": "dad", "visitor_id": "vis", "created_at": 200000 - 100},
    {"type": "relay_door_visitor_old", "target_id": "dad", "visitor_id": "vis", "created_at": 200000 - DB.RELAY_STALE_TICKS - 5},
    {"type": "drink"}]}
DB.settle_relay_intentions(me, w)
check("a fresh doorbell message stays, a half-hour-old one goes", [i["type"] for i in me["active_intentions"]]
      == ["relay_door_visitor_vis", "drink"], me["active_intentions"])
w["characters"]["vis"]["building_id"] = "house"
DB.settle_relay_intentions(me, w)
check("... and it's over once the visitor is inside with them", [i["type"] for i in me["active_intentions"]] == ["drink"])
check("napping counts as asleep at the door too", DB._is_asleep({"activity": {"type": "nap"}}))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
