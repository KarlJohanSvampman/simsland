"""
A remote call/text is written ahead of time off the tick thread and played back like a script
(llm/scripted_conversation.py, systems/scripted_conversations.py).

  - creating the event no longer waits for the model (it used to run on the tick thread, which abandons a model call after
    3 seconds, so on a slow model every remote conversation fell back to the same four stock lines);
  - the whole script is parsed from "Name: line" lines, a cut-off reply still gives the lines before the cut;
  - the call/text starts when the script arrives, and plays to its last line;
  - if the model gives nothing usable three times, or the people can no longer talk, it simply doesn't happen.

Run inside the backend container:   python tests/test_scripted_pending.py
"""

import os
import sys
import time

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from llm import scripted_conversation as sc
from systems import bg_llm, events, scripted_conversations as scr

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, name, **extra):
    c = {"id": cid, "name": name, "age": 35, "age_group": "adult", "household_id": "h", "building_id": "home", "room_id": "kitchen",
         "x": 5, "y": 5, "traits": [], "relationships": {}, "memories": [], "legal": {"status": "free"}, "status": {"reputation": 0.0},
         "stress": 10, "money": 100, "alive": True, "activity": None}
    c.update(extra)
    return c


def make_world():
    w = {"tick": 1000, "characters": {}, "households": {}, "events": [], "shared_events": [], "conversations": {}}
    for c in (person("a", "Anna"), person("r", "Rui")):
        w["characters"][c["id"]] = c
    return w


def run_until(w, cond, seconds=8.0, step=1):
    end = time.time() + seconds
    while time.time() < end:
        w["tick"] += step
        scr.tick_scripted_conversations(w)
        if cond():
            return True
        time.sleep(0.02)
    return False


# ---- parsing -------------------------------------------------------------------------------------------------------------------------
req = {"a_name": "Anna", "a_id": "a", "b_name": "Rui", "b_id": "r"}
text = ('Anna: Hey Rui, got a minute?\nRui: "Sure, what\'s up?"\n**Anna**: It\'s about the noise last night.\n'
        '- Rui: I know, I\'m sorry.\n3. Anna: Okay. Thanks.\nSomebody: not a participant\nRui: ')
lines = sc.parse_script(req, text)
check("'Name: line' lines are read, markdown and numbering ignored", [t["speaker"] for t in lines] == ["Anna", "Rui", "Anna", "Rui", "Anna"], str(lines))
check("... quotes are stripped and other names are skipped", lines[1]["line"] == "Sure, what's up?" and len(lines) == 5)
cut = sc.parse_script(req, "Anna: One.\nRui: Two.\nAnna: Three.\nRui: Four.\nAnna: Fi")
check("a reply cut off mid-line still gives the lines before the cut", len(cut) == 5 and cut[3]["line"] == "Four.")
check("a JSON reply is still read", len(sc.parse_script(req, '{"lines":[{"speaker":"Anna","line":"a"},{"speaker":"Rui","line":"b"}]}')) == 2)
check("too little is no script", sc.parse_script(req, "I examine the sink.") == [])
ids = sc.script_from_lines(req, [{"speaker": "Anna", "line": "x"}, {"speaker": "Nobody", "line": ""}, "oops"])
check("speakers resolve to ids, a stray name alternates, a bad turn is an empty line", [t["speaker_id"] for t in ids] == ["a", "r", "a"] and ids[1]["line"] == "...", str(ids))

# ---- the request carries what it is about and how long it runs -----------------------------------------------------------
w = make_world()
a, r = w["characters"]["a"], w["characters"]["r"]
a["relationships"]["r"] = {"designation": "close_friend", "labels": ["sibling"]}
rq = sc.build_script_request(w, a, r, "pleasant", None, "call", {"subcategory": "praise", "focus_id": "a", "source_id": "r"})
check("the request says who is praising whom and what they are to each other", "Rui is praising Anna" in rq["context"] and "close friend" in rq["context"], rq["context"])
check("a call runs longer than the old 4-8 lines", 8 <= rq["n_turns"] <= 14 and sc.build_script_request(w, a, r, "conflict", "High", "call")["n_turns"] >= 12)
import json
check("the request is plain JSON (it goes to a worker)", json.loads(json.dumps(rq)) == rq)

# ---- creating the event does not wait for the model ---------------------------------------------------------------------------
GOOD = [{"speaker": "Anna" if i % 2 == 0 else "Rui", "line": f"line {i}"} for i in range(10)]
calls = []


def slow_write(req):
    calls.append(req)
    time.sleep(0.3)
    return GOOD


sc.write_script = slow_write
w = make_world()
t0 = time.time()
ev = events.create_shared_event(w, ["a", "r"], "pleasant", severity=None, medium="call")
check("the event is created at once, with the script still to come", time.time() - t0 < 0.2 and not ev.get("conv_id") and ev["id"] in w["pending_scripts"], f"{time.time() - t0:.2f}s")
check("... no conversation exists yet", not w["conversations"] and not w.get("scripted_conversations"))
ok = run_until(w, lambda: ev.get("conv_id"))
check("when the script arrives the call starts and the event links to it", ok and ev["conv_id"] in w["conversations"] and not w["pending_scripts"], str(ev))
check("... both are on the phone", (w["characters"]["a"].get("activity") or {}).get("interaction") == "phone_call")
ok = run_until(w, lambda: not w.get("scripted_conversations"), seconds=15, step=40)
conv = w["conversations"][ev["conv_id"]]
check("the whole script plays to its last line", ok and len(conv["history"]) == len(GOOD), f"{len(conv['history'])} of {len(GOOD)}")
check("... in order, from the right people", [m["utterance"] for m in conv["history"]] == [t["line"] for t in GOOD])
check("one model call was made for the whole exchange", len(calls) == 1, str(len(calls)))

# ---- a text does not occupy anyone ---------------------------------------------------------------------------------------------
w = make_world()
ev = events.create_shared_event(w, ["a", "r"], "neutral", medium="text")
run_until(w, lambda: ev.get("conv_id"))
check("a text starts the same way and leaves everyone free", ev.get("conv_id") and not w["characters"]["a"].get("activity"))

# ---- the model gives nothing -----------------------------------------------------------------------------------------------------
sc.write_script = lambda req: None
w = make_world()
ev = events.create_shared_event(w, ["a", "r"], "argument", severity="Low", medium="call")
ok = run_until(w, lambda: not w["pending_scripts"], seconds=10)
check("three empty answers and it doesn't happen", ok and not ev.get("conv_id") and not w["conversations"] and ev.get("script_failed"), str(ev))
check("... and the timeline says so, not 'exchanging a call'", "tried to call Rui" in ev["text"] and "exchanging" not in ev["text"], ev["text"])
check("... and no stock lines were played", not w.get("scripted_conversations"))

# ---- they can no longer talk -------------------------------------------------------------------------------------------------------
sc.write_script = lambda req: GOOD
w = make_world()
ev = events.create_shared_event(w, ["a", "r"], "pleasant", medium="call")
w["characters"]["r"]["activity"] = {"type": "sleep"}
run_until(w, lambda: not w["pending_scripts"])
check("if one of them fell asleep meanwhile, the call doesn't start", not ev.get("conv_id") and "no longer talk" in ev.get("script_failed", ""), str(ev))

# ---- gives up on its own if it never comes back ---------------------------------------------------------------------------------
sc.write_script = lambda req: time.sleep(30)
w = make_world()
ev = events.create_shared_event(w, ["a", "r"], "pleasant", medium="text")
scr.tick_scripted_conversations(w)
w["tick"] += scr.SCRIPT_WAIT_TICKS + 5
scr.tick_scripted_conversations(w)
check("a script that never comes back is dropped after a while", not w["pending_scripts"] and ev.get("script_failed") == "took too long", str(ev))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
