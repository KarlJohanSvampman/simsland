"""
Worry system, step 2: what gives a character something to worry about (systems/worry_producers.py).

Run inside the backend container:   python tests/test_worry_producers.py
(the last section runs the seeded simulation and needs /tmp/backup_world.json, see tests/determinism.py)
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import worry_cases as wc
from systems import worry_producers as wp
from systems.worry_cases import HOUR

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, name=None, age=35, traits=(), rel=None, **extra):
    d = {"id": cid, "name": name or cid.title(), "age": age, "traits": list(traits), "memories": [],
         "relationships": rel or {}, "household_id": "h1", "alive": True}
    d.update(extra)
    return d


def world(tick=100000, **chars):
    return {"tick": tick, "characters": dict(chars), "news": [], "households": {"h1": {"id": "h1", "bills_due": []}},
            "definitions": {"expectation_templates": {"go_to_work": {"label": "Go to work", "category": "work"},
                                                      "family_dinner": {"label": "Have dinner together"}}}}


def case(c, cid):
    return (c.get("worry_cases") or {}).get(cid)


# ---- expectations -----------------------------------------------------------------------------------------------------
a = person("a")
w = world(a=a)
nd = {"template_id": "family_dinner", "frustration": 0.4, "last_miss_reason": "you were busy cooking"}
wp.on_expectation_missed(a, nd, w)
dinner = case(a, "expectation:family_dinner")
check("a missed expectation opens a case that says why", dinner and dinner["subject"]["kind"] == "expectation"
      and "Have dinner together" in dinner["summary"] and "busy cooking" in dinner["summary"], str(dinner))
b = person("b")
wb = world(b=b)
wp.on_expectation_missed(b, {"template_id": "go_to_work", "frustration": 0.4}, wb)
b2 = person("b2")
wb2 = world(b2=b2)
wp.on_expectation_missed(b2, {"template_id": "family_dinner", "frustration": 0.4}, wb2)
check("missing work is graver than missing dinner", case(b, "expectation:go_to_work")["severity"] > case(b2, "expectation:family_dinner")["severity"])
wp.on_expectation_satisfied(a, "family_dinner", w)
check("getting it done closes the case", case(a, "expectation:family_dinner")["status"] == "resolved")

many = person("many")
wmany = world(many=many)
for t in ("a1", "a2", "a3", "a4", "a5"):
    wp.on_expectation_missed(many, {"template_id": t, "frustration": 0.4}, wmany)
spec = [k for k, cs in many["worry_cases"].items() if cs["subject"]["kind"] == "expectation"]
check("a pile of missed things is two cases and one 'everything I'm behind on', not five", len(spec) == wp.MAX_EXPECTATION_CASES
      and case(many, "self:behind") and case(many, "self:behind")["status"] == "active", str(list(many["worry_cases"])))
check("routine misses are mild", all(cs["severity"] < 5 for cs in many["worry_cases"].values()), str({k: v["severity"] for k, v in many["worry_cases"].items()}))

# the real hooks
from systems import expectations as ex
real = person("real", age=40)
wr = world(tick=500000, real=real)
wr["calendar"] = {"year": 2026, "month": 1, "day": 5, "hour": 20, "minute": 0, "weekday": "Monday"}
real["expectations"] = {"family_dinner": {"template_id": "family_dinner", "cadence": "daily", "frustration": 0.0, "missed_count": 0,
                                           "streak": 3, "status": "pending", "satisfied_this_period": False}}
ex._apply_miss_feedback(real, real["expectations"]["family_dinner"], wr)
check("the expectation code calls the producer when a miss is recorded", case(real, "expectation:family_dinner") is not None)
real["expectations"]["family_dinner"]["status"] = "pending"
ex.satisfy_expectation(real, "family_dinner", wr)
check("... and when it is satisfied", case(real, "expectation:family_dinner")["status"] == "resolved")

# ---- moments ------------------------------------------------------------------------------------------------------------
o = person("o")
bully = person("bully", name="Brutus")
wv = world(o=o, bully=bully)
wp.on_witnessed_violence(o, bully, wv)
fight = case(o, f"event:violence:bully:{wv['tick'] // HOUR}")
check("seeing someone get hurt opens an event case", fight and fight["subject"]["kind"] == "event" and "Brutus" in fight["summary"])
wp.on_witnessed_violence(o, bully, wv)
check("the same fight within the hour is one case", len([k for k in o["worry_cases"] if k.startswith("event:violence")]) == 1)
wv["tick"] += 2 * HOUR
wp.on_witnessed_violence(o, bully, wv)
check("a new incident later is a new case", len([k for k in o["worry_cases"] if k.startswith("event:violence")]) == 2)

victim = person("victim", name="Vic")
watcher = person("watcher", perception={"visible_people": [{"id": "victim"}]})
elsewhere = person("elsewhere")
wd = world(victim=victim, watcher=watcher, elsewhere=elsewhere)
wp.on_death_witnessed(victim, wd)
check("everyone who saw a death is shaken, nobody else", case(watcher, "event:death:victim") and not elsewhere.get("worry_cases"))
check("a death is grave", case(watcher, "event:death:victim")["severity"] >= 6)
from systems import health
dying = person("dying", name="Dina")
seer = person("seer", perception={"visible_people": [{"id": "dying"}]})
wh = world(dying=dying, seer=seer)
health._trigger_death(dying, wh, "heart_failure")
check("the health code calls the producer on death", case(seer, "event:death:dying") is not None)

lp = person("lp")
wl = world(lp=lp)
wp.on_loop_trip(lp, "dust shelf", wl)
check("tripping the loop guard is a worry about oneself", case(lp, "self:erratic") and "dust shelf" in case(lp, "self:erratic")["summary"])

# ---- states: grievances ------------------------------------------------------------------------------------------------------
g = person("g")
foe = person("foe", name="Fiona")
wg = world(g=g, foe=foe)
g["grievances"] = [{"id": "x", "caused_by": "foe", "event_type": "stole", "severity": 14, "weight": 6.0, "tick": 1}]
res = wp.scan_state(g, wg)
check("a small grudge is not a worry", not case(g, "conflict:foe") and res["opened"] == [])
g["grievances"].append({"id": "y", "caused_by": "foe", "event_type": "lied", "severity": 7, "weight": 9.0, "tick": 2})
res = wp.scan_state(g, wg)
check("a grudge past the threshold is a conflict case about that person", "conflict:foe" in res["opened"] and "Fiona" in case(g, "conflict:foe")["summary"])
res = wp.scan_state(g, wg)
check("the next scan refreshes rather than duplicates", res["refreshed"] == ["conflict:foe"] and res["opened"] == [])
g["grievances"] = []
res = wp.scan_state(g, wg)
check("when the grudge has faded the case is resolved", res["closed"] == ["conflict:foe"] and case(g, "conflict:foe")["status"] == "resolved")

# ---- states: the pair ledger --------------------------------------------------------------------------------------------------
from systems.relationship_ledger import get_ledger
l = person("l", rel={"bully": {"kinship": None, "friendship": 5, "familiarity": 20}})
wlg = world(l=l, bully=bully)
led = get_ledger(wlg, "l", "bully")
led["summary"].update({"pos_total": 2.0, "neg_total": 32.0, "balance": -30.0, "engagement": 34.0})
led["summary"]["by_char"]["bully"]["neg_caused"] = 30.0
led["summary"]["by_char"]["l"]["neg_caused"] = 2.0
res = wp.scan_state(l, wlg)
check("someone who keeps hurting you, and you not them, is a worry", "person:bully" in res["opened"], str(res))
led["summary"]["by_char"]["l"]["neg_caused"] = 28.0
led["summary"]["neg_total"] = 58.0
res = wp.scan_state(l, wlg)
check("a two-way quarrel is not (no longer) that kind of worry", res["closed"] == ["person:bully"])

# ---- states: health -------------------------------------------------------------------------------------------------------------
h = person("h", rel={"kid": {"kinship": "child", "friendship": 0, "familiarity": 9}, "pal": {"kinship": None, "friendship": 3, "familiarity": 4}})
kid = person("kid", name="Kiki", age=7, health_state={"doctor_visits_needed": 2, "active_emergencies": {}})
pal = person("pal", name="Pal", health={"sick": True})
wh2 = world(h=h, kid=kid, pal=pal)
res = wp.scan_state(h, wh2)
check("a sick child is a worry; a sick acquaintance is not", "person:kid" in res["opened"] and "person:pal" not in res["opened"], str(res))
h["health_state"] = {"doctor_visits_needed": 1, "active_emergencies": {}}
res = wp.scan_state(h, wh2)
check("one's own health trouble is a worry about oneself", "self:health" in res["opened"])
h["health_state"] = {}
kid["health_state"] = {}
res = wp.scan_state(h, wh2)
check("when everyone is well again the cases close", set(res["closed"]) == {"self:health", "person:kid"}, str(res))

# ---- states: money --------------------------------------------------------------------------------------------------------------
m = person("m")
wm = world(m=m)
wm["households"]["h1"]["bills_due"] = [{"remaining": 80.0, "due_tick": wm["tick"] - 100}]
res = wp.scan_state(m, wm)
check("an overdue bill is a money worry", "self:money" in res["opened"] and "overdue" in case(m, "self:money")["summary"])
sev_one = case(m, "self:money")["severity"]
for _ in range(4):
    wm["tick"] += HOUR
    wm["households"]["h1"]["bills_due"][0]["due_tick"] = wm["tick"] - 100
    wp.scan_state(m, wm)
check("a situation-derived case follows the situation instead of creeping up", case(m, "self:money")["severity"] == sev_one, f"{sev_one} -> {case(m, 'self:money')['severity']}")
wm["households"]["h1"]["bills_due"].append({"remaining": 50.0, "due_tick": wm["tick"] - 100})
wp.scan_state(m, wm)
check("... and rises when the situation gets worse", case(m, "self:money")["severity"] > sev_one)
wm["households"]["h1"]["bills_due"] = [{"remaining": 0.0, "due_tick": wm["tick"] - 100}]
check("paid, it closes", wp.scan_state(m, wm)["closed"] == ["self:money"])
m["government_debt"] = 500.0
check("unpaid tax is a money worry too", "self:money" in wp.scan_state(m, wm)["opened"])
not_due = person("nd")
wnd = world(nd=not_due)
wnd["households"]["h1"]["bills_due"] = [{"remaining": 80.0, "due_tick": wnd["tick"] + 3 * HOUR}]
check("a bill that is not yet due is not", not wp.scan_state(not_due, wnd)["opened"])

# ---- states: choices ------------------------------------------------------------------------------------------------------------
c1 = person("c1")
c2 = person("c2", name="Cleo")
wc2 = world(c1=c1, c2=c2)
wc2["proposals"] = {
    "p1": {"id": "p1", "kind": "romantic", "proposer_id": "c1", "recipients": ["c2"], "responses": {"c2": "pending"}, "status": "open", "created_tick": wc2["tick"] - 100},
    "p2": {"id": "p2", "kind": "chore", "proposer_id": "c1", "recipients": ["c2"], "responses": {"c2": "pending"}, "status": "open", "created_tick": wc2["tick"] - 5 * HOUR},
}
check("a question only just asked is not a worry yet", not wp.scan_state(c1, wc2)["opened"])
wc2["proposals"]["p1"]["created_tick"] -= 2 * HOUR
res = wp.scan_state(c1, wc2)
check("a high-stakes question left hanging is (an ordinary chore is not)", res["opened"] == ["choice:p1"], str(res))
res = wp.scan_state(c2, wc2)
check("so is one you owe an answer to", res["opened"] == ["choice:p1"])
wc2["proposals"]["p1"]["status"] = "resolved"
check("answered, both close", wp.scan_state(c1, wc2)["closed"] == ["choice:p1"] and wp.scan_state(c2, wc2)["closed"] == ["choice:p1"])

# ---- scans leave other people's cases alone -----------------------------------------------------------------------------------
k = person("k")
wk = world(k=k, bully=bully)
wc.register_worry(k, {"kind": "person", "ref": "bully", "label": "Brutus"}, 4, "pattern_concern", "he keeps repeating things", wk)
wp.scan_state(k, wk)
check("a scan does not close a case somebody else opened", case(k, "person:bully")["status"] == "active")

# ---- the poll runs the scan ---------------------------------------------------------------------------------------------------
q = person("q")
wq = world(q=q)
q["government_debt"] = 100.0
q["focus_state"] = {"last_poll": wq["tick"] - HOUR}
res = wc.poll_worries(q, wq)
check("the hourly poll includes the state scan", res["scan"]["opened"] == ["self:money"] and q["focus_state"]["available"] < 100)

# ---- a producer that breaks does not break its host ----------------------------------------------------------------------------
broken = person("broken")
check("producers swallow their own errors", wp.on_expectation_missed(broken, {}, {"tick": 1}) is None)

# ---- the simulation ---------------------------------------------------------------------------------------------------------------
from tests import determinism
import collections
w2, errs, _ = determinism.run_sim(12000, start="2026-11-04T08:00:00")
kinds = collections.Counter()
for ch in w2["characters"].values():
    for cs in (ch.get("worry_cases") or {}).values():
        kinds[(cs["subject"]["kind"], cs["subject"].get("ref") if cs["subject"]["kind"] in ("area", "self") else "", cs["status"])] += 1
print(f"   12000 simulated ticks: errors={dict(errs)}; cases by (kind, ref, status): {dict(kinds)}")
check("the simulation runs with all producers attached", not errs)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
