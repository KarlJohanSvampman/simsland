"""
CPL phase 2 (docs/cpl_implementation_plan.md section 8, 6.3): what changes a conversation from outside it --
interruptions, people becoming unavailable, a restart -- and the pieces of the lifecycle around them: pause and
resume, the template summary, an invitation's initiator waiting, a legacy "ignored" held back for CPL.

Run inside the backend container:   python tests/test_cpl_lifecycle.py
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
from cpl import config, lifecycle, participants, shadow, store, turns
from cpl import conversations as CV

config.CPL_MODE = "on"
asked = []
event_bus.subscribe("cpl.turn_requested", lambda data, world=None: asked.append(dict(data)))


def world():
    return {"tick": 0, "sim_time": 1000.0, "timers": [], "conversations": {},
            "characters": {k: {"id": k, "name": k.title(), "cognition": {}} for k in ("ana", "theo", "mia")}}


def talking(w, a="ana", b="theo", channel="in_person"):
    c = CV.open_conversation(w, a, [b], channel=channel, purpose="social")
    CV.submit(w, c, {"type": "turn", "by": b})
    return c


# ── interruptions ────────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
c = talking(w)
asked.clear()
hit = lifecycle.interrupt(w, "ana", by="mia", kind="doorbell")
event_bus.flush(w)
check("the doorbell interrupts Ana's conversation", hit == [c["id"]] and c["interruption"]["kind"] == "doorbell")
check("... both are asked what to do about it", {a["who"] for a in asked if a.get("interrupted")} == {"ana", "theo"}, asked)
blk = turns.context_block(w, w["characters"]["ana"])
check("... and Ana's prompt says so, with what she can do", blk["interrupted"] == "the doorbell rang"
      and "NEXT: pause" in turns.prompt_section(blk), blk)
check("... Theo's prompt doesn't claim his doorbell rang", turns.context_block(w, w["characters"]["theo"])["interrupted"] is None)
legacy = {"id": "L1", "participants": ["ana", "theo"], "medium": "in_person", "active": True}
w["cpl_legacy_map"] = {"L1": c["id"]}
shadow.on_line(w, legacy, "ana", "Hold on, someone's at the door.", "declare")
check("once someone speaks, the interruption is dealt with", c["interruption"] is None)

w = world()
c = talking(w)
call = talking(w, "mia", "ana", channel="call")
hit = lifecycle.interrupt(w, "ana", by="mia", kind="phone", channel="in_person")
check("a call interrupts the face-to-face conversation, not the call itself", hit == [c["id"]], hit)

# ── pause and resume ─────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
c = talking(w)
w["cpl_legacy_map"] = {"L1": c["id"]}
legacy = {"id": "L1", "participants": ["ana", "theo"], "medium": "in_person", "active": True}
w["characters"]["ana"]["_cpl_turn"] = "NEXT: pause"
shadow.on_line(w, legacy, "ana", "One second.", "declare")
w["characters"]["ana"].pop("_cpl_turn")
check("NEXT pause: the conversation is on hold", c["state"] == "paused")
check("... the prompt says it is on hold", turns.context_block(w, w["characters"]["theo"])["paused"])
shadow.on_line(w, legacy, "ana", "Sorry, where were we?", "declare")
check("speaking again picks it up (ACTIVE)", c["state"] == "active", c["state"])

# ── unavailability, from the existing events ─────────────────────────────────────────────────────────────────────────
for event, data, why in (("character.offgrid", {"character_id": "theo", "reason": "work"}, "goes off the map"),
                         ("character_arrested", {"character_id": "theo", "crime": "x"}, "is arrested"),
                         ("activity_started", {"character_id": "theo", "activity_type": "sleep"}, "falls asleep")):
    w = world()
    c = talking(w)
    event_bus.emit(event, data)
    event_bus.flush(w)
    check(f"Theo {why}: the conversation ends (unavailable)", c["state"] == "resolved" and c["reason"] == "unavailable",
          (c["state"], c["reason"]))
w = world()
c3 = CV.open_conversation(w, "ana", ["theo", "mia"], channel="in_person", purpose="social")
CV.submit(w, c3, {"type": "turn", "by": "theo"})
c3["participants"]["mia"]["status"] = "active"
lifecycle.notify_unavailable(w, "mia", "asleep")
check("three talking, one falls asleep: it carries on without her", c3["state"] == "active"
      and c3["participants"]["mia"]["status"] == "unavailable")

# ── recovery after a load ────────────────────────────────────────────────────────────────────────────────────────────
w = world()
c = talking(w)
CV.submit(w, c, {"type": "turn", "by": "ana", "requires_response": True})
gone = talking(w, "mia", "ana")
w["characters"]["mia"]["off_grid"] = True
asked.clear()
done = lifecycle.recover(w)
event_bus.flush(w)
check("after a load: the turn whose request was lost is asked again", c["id"] in done["re_asked"]
      and any(a.get("recovered") and a["who"] == "theo" for a in asked), (done, asked))
check("... and a conversation with someone now away is resolved", gone["state"] == "resolved" and gone["id"] in done["unavailable"])

# ── the summary ──────────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
legacy = {"id": "L9", "participants": ["ana", "theo"], "medium": "in_person", "active": True, "topic": "the weekend"}
shadow.on_line(w, legacy, "ana", "Any plans for the weekend?", "question")
shadow.on_line(w, legacy, "theo", "Hiking, I think.", "declare")
conv = store.get(w, w["cpl_legacy_map"]["L9"])
check("the template summary keeps up, line by line", conv["context"]["summary"].startswith("2 lines so far about the weekend"),
      conv["context"]["summary"])
check("... and shows on the prompt", "So far: 2 lines" in turns.prompt_section(turns.context_block(w, w["characters"]["ana"])))

# ── an invitation's initiator waits; a legacy "ignored" waits for CPL ────────────────────────────────────────────────
w = world()
p = CV.open_conversation(w, "ana", ["theo"], channel="in_person", purpose="social")
check("CPL on: the initiator of an unanswered invitation can't talk over it", participants.floor_blocks(w, "ana", "theo"))
config.CPL_MODE = "shadow"
check("... in shadow mode that is left to the legacy path", not participants.floor_blocks(w, "ana", "theo"))
config.CPL_MODE = "on"
w["cpl_legacy_map"] = {"L2": p["id"]}
check("CPL on, live copy: a legacy 'ignored' is held back", not shadow.legacy_end_allowed(w, {"id": "L2"}, "ignored"))
check("... a legacy 'resolved' is not", shadow.legacy_end_allowed(w, {"id": "L2"}, "resolved"))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
