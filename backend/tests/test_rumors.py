"""
Remarks about a third person and how they travel (systems/rumors.py), end to end into the relationship ledger and grudges.

Run inside the backend container:   python tests/test_rumors.py
(the last section uses the seeded fixture and needs /tmp/backup_world.json, see tests/determinism.py)
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from systems import rumors as rm
from systems import relationship_ledger as rl
from systems.rumors import HOUR

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, traits=(), age=35, rel=None, **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "traits": list(traits), "memories": [], "relationships": rel or {},
         "active_intentions": [], "alive": True, "x": 1, "y": 1}
    d.update(extra)
    return d


def world(tick=100000, *chars):
    return {"tick": tick, "characters": {c["id"]: c for c in chars}, "definitions": {}}


def trio(listener_rel=None, **kw):
    sam = person("sam")
    lia = person("lia", rel=listener_rel or {"sam": {"trust": 40, "friendship": 30}})
    zed = person("zed", **kw)
    return sam, lia, zed, world(100000, sam, lia, zed)


# ---- what kind of remark -----------------------------------------------------------------------------------------------------
check("a hurtful remark is meanness", rm.remark_kind("speak", {"valence": "hurt"}) == "meanness")
check("gossip with no declared intent is too", rm.remark_kind("gossip", None) == "meanness")
check("a lie about someone is slander", rm.remark_kind("lie", None) == "slander" and rm.remark_kind("speak", {"valence": "deceive"}) == "slander")
check("kind words about someone are a compliment", rm.remark_kind("speak", {"valence": "help"}) == "compliment")
check("an ordinary line says nothing about a third person", rm.remark_kind("ask", None) is None and rm.remark_kind("speak", {"valence": "neutral"}) is None)

# ---- credibility -----------------------------------------------------------------------------------------------------------------
sam, lia, zed, w = trio()
base = rm.credibility(lia, "sam", "zed", "meanness", -1)
check("a trusted friend is believed more often than not", base > 0.6, str(base))
lia["relationships"]["zed"] = {"friendship": 60, "trust": 50}
resist = rm.credibility(lia, "sam", "zed", "meanness", -1)
check("someone who is fond of the subject resists a hurtful remark", resist < base - 0.25, f"{resist} vs {base}")
check("... but not praise of them", rm.credibility(lia, "sam", "zed", "compliment", +1) >= base)
check("a lie is harder to swallow than a barb", rm.credibility(lia, "sam", "zed", "slander", -1) < resist)
stranger = person("str", rel={})
check("a stranger's word counts for little", rm.credibility(stranger, "sam", "zed", "meanness", -1) < 0.5)
kid = person("kid", age=7, rel={})
check("a child believes what they are told", rm.credibility(kid, "sam", "zed", "meanness", -1) > rm.credibility(stranger, "sam", "zed", "meanness", -1) + 0.15)
check("credibility is always a probability", all(0.1 <= rm.credibility(person("p", rel={"sam": {"trust": t, "friendship": f}}), "sam", "zed", "slander", -1) <= 0.95
                                                  for t in (-100, 0, 100) for f in (-100, 0, 100)))

# ---- the listener hears it ---------------------------------------------------------------------------------------------------------
random.seed(1)
sam, lia, zed, w = trio()
lia["relationships"]["zed"] = {"friendship": 10, "respect": 10, "trust": 10}
data = {"speaker_id": "sam", "listener_id": "lia", "subject_id": "zed", "kind": "meanness", "text": "Zed never pays his share", "discretion": 0.6}
random.seed(2)
res = [rm._on_remark(dict(data, text=f"Zed never pays his share {i}"), world(100000, sam, lia, zed))[1] for i in range(30)]
check("sometimes believed, sometimes not", 8 < sum(res) < 30, str(sum(res)))

import unittest.mock as mock
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rumor, believed = rm._on_remark(data, w)
check("believed: their view of the subject sours a little", believed and lia["relationships"]["zed"]["friendship"] < 10
      and lia["relationships"]["zed"]["respect"] < 10 and lia["relationships"]["zed"]["trust"] < 10, str(lia["relationships"]["zed"]))
check("they remember who said what about whom", any("Sam talked about Zed" in m["text"] and "never pays" in m["text"] and "gossip" in m["tags"] for m in lia["memories"]))
check("a rumor is recorded with its believer", rumor["believers"] == ["lia"] and rumor["subject"] == "zed" and not rumor["told_to_subject"])
check("nothing is written on the pair's ledger yet: the subject has not heard", rl.get_ledger(w, "sam", "zed", create=False) is None)
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rm._on_remark(data, w)
check("the same remark again is the same rumor", len(w["rumors"]) == 1 and w["rumors"][rumor["id"]]["believers"] == ["lia"])

sam, lia, zed, w = trio()
lia["relationships"]["zed"] = {"friendship": 10, "respect": 10, "trust": 10}
with mock.patch("systems.rumors.random.random", return_value=0.999):
    rumor, believed = rm._on_remark(dict(data), w)
check("doubted: their view doesn't change, and they say so in the memory", not believed and lia["relationships"]["zed"]["friendship"] == 10
      and any("not sure I believe" in m["text"] for m in lia["memories"]))
check("... and they don't carry it", rumor["believers"] == [])

sam, lia, zed, w = trio()
lia["relationships"]["zed"] = {"friendship": 10}
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rm._on_remark(dict(data, kind="compliment", text="Zed is so reliable"), w)
check("praise warms them to the subject", lia["relationships"]["zed"]["friendship"] > 10)
check("a remark about the listener or the speaker is ignored", rm._on_remark(dict(data, subject_id="lia"), w) is None
      and rm._on_remark(dict(data, subject_id="sam"), w) is None and rm._on_remark(dict(data, kind="no_such_kind"), w) is None)

# ---- carrying it to the subject ---------------------------------------------------------------------------------------------------
sam, lia, zed, w = trio()
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rumor, _ = rm._on_remark(dict(data, kind="slander", text="Zed stole from the till"), w)
events = []
real_emit = rm.emit
rm.emit = lambda name, d: events.append((name, d))
rm.tick_rumors(w)
check("nobody tells them while they are not around", not events and not rumor["told_to_subject"])
lia["perception"] = {"visible_people": [{"id": "zed"}]}
with mock.patch("systems.rumors.random.random", return_value=0.9):
    rm.tick_rumors(w)
check("and not on a bad roll", not events)
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rm.tick_rumors(w)
check("a believer near the subject tells them", len(events) == 1 and rumor["told_to_subject"] and rumor["told_by"] == "lia", str(events))
name, payload = events[0]
check("it arrives as an impact from the original speaker, delivered straight to the subject",
      name == "impact_intent" and payload["source_id"] == "sam" and payload["target_id"] == "zed" and payload["kind"] == "slander"
      and payload["channel"] == "learned_secondhand" and payload["audience"] == "targets" and payload["ref"]["told_by"] == "lia")
check("the subject remembers who told them", any("Lia told me that Sam" in m["text"] and "heard_about_me" in m["tags"] for m in zed["memories"]))
check("the teller remembers telling", any("I told Zed" in m["text"] for m in lia["memories"]))
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rm.tick_rumors(w)
check("it is told only once", len(events) == 1)
rm.emit = real_emit

sam, lia, zed, w = trio()
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rumor, _ = rm._on_remark(dict(data), w)
w["tick"] += rm.RUMOR_LIFETIME_TICKS + 10
lia["perception"] = {"visible_people": [{"id": "zed"}]}
rm.tick_rumors(w)
check("an old rumor lapses", not w["rumors"])

# who tells, and how readily
chatty = person("c1", traits=["gossipy"], rel={"zed": {"friendship": 30}})
quiet = person("q1", traits=["secretive"], rel={"zed": {"friendship": 30}})
plain = person("p1", rel={"zed": {"friendship": 30}})
neg = {"polarity": -1}
check("a gossip tells more readily, a discreet person less", rm._tell_chance(chatty, zed, neg) > rm._tell_chance(plain, zed, neg) > rm._tell_chance(quiet, zed, neg))
check("good news travels faster than bad", rm._tell_chance(plain, zed, {"polarity": 1}) > rm._tell_chance(plain, zed, neg))
check("a friend of the subject is likelier to speak up than an acquaintance",
      rm._tell_chance(plain, zed, neg) > rm._tell_chance(person("a1", rel={"zed": {"friendship": 0}}), zed, neg))

# ---- into the ledger and the grudge ---------------------------------------------------------------------------------------------------
sam, lia, zed, w = trio()
zed["relationships"] = {"sam": {"trust": 5, "friendship": 5}}
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rumor, _ = rm._on_remark(dict(data, kind="slander", text="Zed stole from the till"), w)
events = []
rm.emit = lambda name, d: events.append((name, d))
lia["perception"] = {"visible_people": [{"id": "zed"}]}
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rm.tick_rumors(w)
rm.emit = real_emit
written = rl.handle_intent(events[0][1], w)
led = rl.get_ledger(w, "sam", "zed", create=False)
perceived = [e for e in led["entries"] if e["layer"] == "perceived"] if led else []
check("once told, it registers on the (speaker, subject) pair through the ordinary ladder", written and perceived
      and perceived[-1]["channel"] == "learned_secondhand" and perceived[-1]["source"] == "sam" and perceived[-1]["target"] == "zed", str(led and led["entries"][-2:]))
check("... and the subject holds a grudge against the one who said it", "sam" in (zed.get("grudges") or {}) and zed["grudges"]["sam"]["status"] == "open"
      and zed["grudges"]["sam"]["origin"]["kind"] == "slander", str(zed.get("grudges")))
check("the speaker is none the wiser", not sam.get("grudges"))

# mild praise told to the subject registers as something good
sam2, lia2, zed2, w2 = trio()
with mock.patch("systems.rumors.random.random", return_value=0.0):
    r2, _ = rm._on_remark(dict(data, kind="compliment", text="Zed is so reliable"), w2)
events = []
rm.emit = lambda name, d: events.append((name, d))
lia2["perception"] = {"visible_people": [{"id": "zed"}]}
with mock.patch("systems.rumors.random.random", return_value=0.0):
    rm.tick_rumors(w2)
rm.emit = real_emit
rl.handle_intent(events[0][1], w2)
led2 = rl.get_ledger(w2, "sam", "zed", create=False)
check("praise that reaches them is a positive entry and no grudge", led2 and led2["summary"]["pos_total"] > 0 and not zed2.get("grudges"))

# ---- the speech path ------------------------------------------------------------------------------------------------------------------------
from tests import determinism
import brain.agent_loop  # noqa: F401
from systems.action_router import apply_speech

wf = determinism.fixture("2026-11-04T08:00:00")
adults = [c for c in wf["characters"].values() if (c.get("age") or 0) >= 18 and not c.get("is_workplace_npc") and not c.get("is_service_worker")]
speaker, listener = adults[0], adults[1]
third = next(c for c in wf["characters"].values() if c["id"] not in (speaker["id"], listener["id"]) and not c.get("is_workplace_npc") and not c.get("is_service_worker"))
for c in (speaker, listener):
    c["activity"] = None
    c["posture"] = "standing"
    c["x"], c["y"] = 5, 5
    c["building_id"] = None
speaker["relationships"].setdefault(listener["id"], {})
listener.setdefault("relationships", {}).setdefault(speaker["id"], {}).update({"trust": 60, "friendship": 50})
import systems.conversation_interest as _ci
_ci.check_conversation_interest = lambda *a, **k: (True, 0.8, None)         # the listener is willing to talk
seen_events = []
orig_dispatch = event_bus.dispatch
event_bus.dispatch = lambda et, data, world: (seen_events.append(et), orig_dispatch(et, data, world))[1]
random.seed(5)
apply_speech(speaker, wf, {"target": listener["id"], "speech_act": "gossip", "topic": "gossip",
                           "utterance": f"Between us, {third['name'].split()[0]} is hopeless at everything.", "intent": {"valence": "hurt"}})
event_bus.flush(wf)
event_bus.dispatch = orig_dispatch
check("a line that names an absent third person is recorded as a remark", "third_party_remark" in seen_events, str(seen_events))
check("... and becomes a rumor about them, with the speaker as its source", any(r["subject"] == third["id"] and r["source"] == speaker["id"]
      and r["kind"] == "meanness" for r in (wf.get("rumors") or {}).values()), str(wf.get("rumors")))
check("the directed line itself still went through the ordinary speech path", any("hopeless" in m.get("utterance", "") for m in speaker.get("speech_log", [])))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
