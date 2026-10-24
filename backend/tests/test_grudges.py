"""
Grudges (systems/grudges.py): what a registered insult leaves behind, built on the relationship ledger.

Run inside the backend container:   python tests/test_grudges.py
(the last section runs the seeded simulation and needs /tmp/backup_world.json, see tests/determinism.py)
"""

import collections
import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import grudges as gr
from systems import relationship_ledger as rl
from systems.grudges import HOUR

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, traits=(), **extra):
    d = {"id": cid, "name": cid.title(), "age": 35, "traits": list(traits), "memories": [], "relationships": {},
         "active_intentions": [], "alive": True, "x": 1, "y": 1}
    d.update(extra)
    return d


def world(tick=100000, *chars):
    return {"tick": tick, "characters": {c["id"]: c for c in chars}, "definitions": {}}


def hurt(w, source, target, kind="insult", value=9.0, flags=None, text="you are useless"):
    """A perceived entry on the pair, the way the ledger writes it once the evaluation ladder has passed."""
    intent = rl.log_intent(w, source["id"], target["id"], kind, value, 0.2, "speech", text=text)
    return rl.register(w, intent, target, value, 6, [], flags=flags)


def setup(holder_traits=(), offender_traits=(), tick=100000):
    a, b = person("hana", holder_traits), person("otto", offender_traits)
    return a, b, world(tick, a, b)


# ---- opening ------------------------------------------------------------------------------------------------------------
a, b, w = setup()
hurt(w, b, a, "insult", 3.0)
check("a small slight leaves no grudge", not a.get("grudges"))
hurt(w, b, a, "insult", 9.0)
g = a["grudges"]["otto"]
check("a heavy one does", g["status"] == "open" and g["origin"]["kind"] == "insult" and g["origin"]["text"] == "you are useless")
check("with a priority, a short term and a retention", 1 <= g["priority"] <= 10 and g["short_term_until"] == w["tick"] + gr.SHORT_TERM_TICKS
      and 0.2 <= g["retention"] <= 1.0 and g["retention"] == g["retention_at_creation"])
check("they remember it", any("grudge" in m["tags"] and "apology" in m["text"] for m in a["memories"]))
check("the offender holds nothing against them", not b.get("grudges"))

a, b, w = setup()
for v in (5.0, 5.0, 4.0):
    w["tick"] += 600
    hurt(w, b, a, "meanness", v)
check("several together within two hours do", "otto" in a.get("grudges", {}))
a, b, w = setup()
for v in (5.0, 5.0, 4.0):
    w["tick"] += 3 * HOUR
    hurt(w, b, a, "meanness", v)
check("spread over days they do not", not a.get("grudges"))

a, b, w = setup()
hurt(w, b, a, "insult", 9.0, flags={"witnessed": True, "victim": "x"})
hurt(w, b, a, "insult", 9.0, flags={"misattributed": True})
check("only what was done to them counts, not what they saw or assumed", not a.get("grudges"))

soft, hard = setup(["forgiving"])[:1], setup(["petty", "vindictive"])[:1]
a1, b1, w1 = setup(["forgiving"])
a2, b2, w2 = setup(["petty", "vindictive"])
hurt(w1, b1, a1, "insult", 9.0)
hurt(w2, b2, a2, "insult", 9.0)
check("a forgiving character holds on less firmly than a vindictive one", a1["grudges"]["otto"]["retention"] < a2["grudges"]["otto"]["retention"],
      f"{a1['grudges']['otto']['retention']} vs {a2['grudges']['otto']['retention']}")

# ---- refreshing --------------------------------------------------------------------------------------------------------------
a, b, w = setup()
hurt(w, b, a, "insult", 9.0)
g = a["grudges"]["otto"]
before = (g["priority"], g["retention"], g["short_term_until"])
w["tick"] += 3000
hurt(w, b, a, "disrespect", 5.0)
check("another hurt refreshes it: more priority, firmer, a later short term", g["refreshes"] == 1 and g["priority"] == before[0] + 1
      and g["retention"] > before[1] and g["short_term_until"] > before[2], str((g, before)))
check("still one grudge", len(a["grudges"]) == 1)

# ---- resolving --------------------------------------------------------------------------------------------------------------------
a, b, w = setup()
hurt(w, b, a, "insult", 9.0)
b["active_intentions"] = [{"type": "apologize_to", "target_id": "hana", "category": "social", "priority": 42}]
g = a["grudges"]["otto"]
r0 = g["retention"]
w["tick"] += 1800
hurt(w, b, a, "kindness", 4.0)
check("a kind act shortens it a little", g["status"] == "open" and g["retention"] < r0)
r1 = g["retention"]
hurt(w, b, a, "apology", 6.0)
check("an apology ends the short term and halves what is left", g["short_term_until"] <= w["tick"] and abs(g["retention"] - r1 * 0.5) < 0.01
      or g["status"] == "resolved", str(g))
w["tick"] += 600
hurt(w, b, a, "apology", 6.0)
check("a second one settles it", g["status"] == "resolved" and g["closed_how"], str(g["status"]))
hours = (g["closed"] - g["created"]) / HOUR
import math
check("the score is hours open x the retention it started with", g["score"] == math.ceil(hours * g["retention_at_creation"]))
led = rl.get_ledger(w, "hana", "otto", create=False)
check("... and is added to the pair's engagement", led["summary"]["engagement"] >= g["score"])
check("they keep one memory of how it began and ended", any("upset with Otto" in m["text"] and "ended" in m["text"] for m in a["memories"]))
check("the offender's urge to apologise is gone", not any(i["type"] == "apologize_to" for i in b["active_intentions"]))

# a real act from someone else does not settle it
a, b, w = setup()
c3 = person("cleo")
w["characters"]["cleo"] = c3
hurt(w, b, a, "insult", 9.0)
hurt(w, c3, a, "apology", 6.0)
check("an apology from a third party changes nothing", a["grudges"]["otto"]["status"] == "open" and a["grudges"]["otto"]["retention"] == a["grudges"]["otto"]["retention_at_creation"])

# ---- fading ----------------------------------------------------------------------------------------------------------------------------
a, b, w = setup()
hurt(w, b, a, "insult", 9.0)
g = a["grudges"]["otto"]
w["tick"] += gr.SHORT_TERM_TICKS - 100
gr.tick_grudges(w)
check("while the short term lasts it does not fade", g["retention"] == g["retention_at_creation"])
w["tick"] += 100 + gr.LONG_TERM_TICKS // 2
gr.tick_grudges(w)
check("afterwards it fades gradually", 0 < g["retention"] < g["retention_at_creation"] and g["status"] == "open", str(g["retention"]))
w["tick"] += gr.LONG_TERM_TICKS
gr.tick_grudges(w)
check("and goes of its own accord", g["status"] == "faded" and g["closed_how"] == "time passed")
check("a faded grudge is still remembered", any("faded on its own" in m["text"] for m in a["memories"]))

a, b, w = setup()
hurt(w, b, a, "insult", 9.0)
b["alive"] = False
gr.tick_grudges(w)
check("a grudge against someone who has died is closed", a["grudges"]["otto"]["status"] == "faded")

# ---- what they do about it ---------------------------------------------------------------------------------------------------------------
import systems.expressions as expressions
said = []
real_express = expressions.express
expressions.express = lambda c, w, speech: said.append((c["id"], speech)) or None
random.seed(7)
hot, other, wh = setup(["hot_tempered"])
hot["perception"] = {"visible_people": [{"id": "otto"}]}
hurt(wh, other, hot, "insult", 9.0)
for _ in range(400):
    wh["tick"] += 60
    if wh["tick"] > hot["grudges"]["otto"]["short_term_until"]:
        break
    gr.tick_grudges(wh)
jabs = [s for who, s in said if who == "hana"]
check("a hot-tempered holder jabs at the offender when they are near", jabs and all(s["speech_act"] == "insult" and s["target"] == "otto"
      and s["intent"]["valence"] == "hurt" for s in jabs), str(jabs[:2]))
check("... but not more than once per cooldown", len(jabs) <= (gr.SHORT_TERM_TICKS // gr.JAB_COOLDOWN_TICKS) + 1, str(len(jabs)))
said.clear()
calm, other2, wc2 = setup(["calm"])
calm["perception"] = {"visible_people": [{"id": "otto"}]}
hurt(wc2, other2, calm, "insult", 9.0)
for _ in range(60):
    wc2["tick"] += 60
    if wc2["tick"] > calm["grudges"]["otto"]["short_term_until"]:
        break
    gr.tick_grudges(wc2)
check("a calm one only mutters or sighs, aimed at no one", said and all(s["target"] is None and s["speech_act"] in ("mutter", "sigh") for _, s in said), str(said[:2]))
said.clear()
far, other3, wf = setup(["hot_tempered"])
hurt(wf, other3, far, "insult", 9.0)
for _ in range(60):
    wf["tick"] += 60
    gr.tick_grudges(wf)
check("nothing is said when the offender is not around", not said)
expressions.express = real_express

# the offender is moved to apologise; the proud are not
random.seed(3)
nudged = 0
for i in range(40):
    aa, bb, ww = setup()
    hurt(ww, bb, aa, "insult", 9.0)
    ww["tick"] += gr.NUDGE_AFTER_TICKS + 10
    gr.tick_grudges(ww)
    nudged += any(x["type"] == "apologize_to" and x["target_id"] == "hana" for x in bb["active_intentions"])
check("most offenders are nudged towards apologising", 15 <= nudged <= 38, str(nudged))
aa, bb, ww = setup(offender_traits=["stubborn"])
hurt(ww, bb, aa, "insult", 9.0)
ww["tick"] += gr.NUDGE_AFTER_TICKS + 10
gr.tick_grudges(ww)
check("a proud one is not", not any(x["type"] == "apologize_to" for x in bb["active_intentions"]))
check("... and the grudge is known to them either way", aa["grudges"]["otto"]["aware"])

# escalation
events = []
real_emit = gr.emit
gr.emit = lambda name, data: events.append((name, data))
aa, bb, ww = setup()
aa["perception"] = {"visible_people": [{"id": "otto"}]}
hurt(ww, bb, aa, "humiliation", 10.0)
check("a heavy grudge has a high priority", aa["grudges"]["otto"]["priority"] >= gr.ESCALATE_PRIORITY)
ww["tick"] += 60
gr.tick_grudges(ww)
gr.tick_grudges(ww)
check("it asks for a confrontation once, when the offender is in view", [e[0] for e in events] == ["confrontation_desired"]
      and events[0][1]["initiator_id"] == "hana" and events[0][1]["target_id"] == "otto", str(events))
gr.emit = real_emit

# ---- what they know -----------------------------------------------------------------------------------------------------------------------
a, b, w = setup()
hurt(w, b, a, "insult", 9.0)
lines = gr.context_lines(a, w)
check("the holder is told they are waiting for an apology", lines and "waiting for them to apologise" in lines[0] and "Otto" in lines[0], str(lines))
check("the offender isn't told until it is known to them", gr.context_lines(b, w) == [])
a["grudges"]["otto"]["aware"] = True
check("... once it is, they are", any("Hana is upset with you" in l for l in gr.context_lines(b, w)))
check("others hear nothing", gr.context_lines(person("zed"), w) == [])
from brain import context_builder
ctx_lines = context_builder._sec_grudges(a, w)
check("the context builder carries it", ctx_lines and "apologise" in ctx_lines[0])

# ---- worries --------------------------------------------------------------------------------------------------------------------------------
from systems import worry_producers as wp
res = wp.scan_state(a, w)
check("an open grudge is a quarrel that worries them", "conflict:otto" in res["opened"] and "angry" in a["worry_cases"]["conflict:otto"]["summary"], str(res))
gr.close(w, a, a["grudges"]["otto"], "resolved", "they apologised")
check("when it is over, so is the worry", wp.scan_state(a, w)["closed"] == ["conflict:otto"])

# ---- the simulation ---------------------------------------------------------------------------------------------------------------------------
from tests import determinism
import brain.agent_loop as agent_loop
agent_loop.tick_curiosity = lambda c, w: None
agent_loop.maybe_go_offgrid = lambda c, w: None
import systems.offgrid as _offgrid
import systems.travel as _travel
_offgrid.send_offgrid = lambda *a, **k: None          # nobody leaves the map: the feud needs both of them home
_travel.begin_travel = lambda *a, **k: None


def start_feud(w):
    adults = [ch for ch in w["characters"].values() if (ch.get("age") or 0) >= 18 and not ch.get("is_workplace_npc") and not ch.get("is_service_worker")]
    h, o = adults[0], adults[1]
    for ch in adults:
        ch["activity"] = None
        ch["posture"] = "standing"
        ch["active_intentions"] = []
        ch.pop("_body_lazy", None)
        ch["body"].update({"hunger": 0, "hydration": 100, "energy": 100, "fatigue": 0, "bladder": 0, "bowels": 0, "hygiene": 100,
                           "odor": 0, "stomach_discomfort": 0, "mouth_hygiene": 100, "sleep_debt": 0, "hours_awake": 1})
    h["traits"] = list(set(h.get("traits", [])) | {"hot_tempered"})
    o["traits"] = [t for t in o.get("traits", []) if t not in gr.PROUD_TRAITS]
    intent = rl.log_intent(w, o["id"], h["id"], "humiliation", 10.0, 0.1, "speech", text="in front of everyone")
    rl.register(w, intent, h, 10.0, 6, [])
    w["_feud"] = (h["id"], o["id"])


w2, errs, _ = determinism.run_sim(9000, start="2026-11-04T08:00:00", setup=start_feud)
hid, oid = w2["_feud"]
holder = w2["characters"][hid]
g = holder["grudges"][oid]
print(f"   9000 simulated ticks: errors={dict(errs)}; grudge {holder['name']} -> {w2['characters'][oid]['name']}: status={g['status']} "
      f"retention={g['retention']} refreshes={g['refreshes']} jabbed={g['jabbed'] > 0} nudged={g['nudged']} aware={g['aware']} escalated={g['escalated']}")
check("the simulation runs with grudges attached", not errs)
check("the grudge lived through it: it was acted on, the offender was nudged, and a confrontation was asked for",
      g["jabbed"] > 0 and g["nudged"] and g["escalated"] and g["aware"], str(g))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
