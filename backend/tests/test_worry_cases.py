"""
Worry system, step 1: the case file, registration, refresh, expiry, the focus budget, the hourly poll,
the producers (pattern concern, suspicion) and the prompt line  (systems/worry_cases.py,
docs/worry_system_plan.md).

Run inside the backend container:   python tests/test_worry_cases.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import worry_cases as wc
from systems.worry_cases import HOUR

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, name=None, age=35, traits=(), rel=None):
    return {"id": cid, "name": name or cid.title(), "age": age, "traits": list(traits), "memories": [],
            "relationships": rel or {}, "household_id": "h1"}


def world(tick=0, **chars):
    return {"tick": tick, "characters": dict(chars), "news": [], "definitions": {}}


SELF = {"kind": "self", "ref": None, "label": "myself"}


def P(cid, label=None):
    return {"kind": "person", "ref": cid, "label": label or cid}


# ---- severity ------------------------------------------------------------------------------------------------------
calm = person("calm", traits=["calm", "resilient"])
nervy = person("nervy", traits=["nervous", "paranoid"], rel={"kid": {"kinship": "child", "friendship": 0, "familiarity": 9}})
check("an anxious character worries more than a steady one", wc.propensity(nervy) > 1.4 > 0.8 > wc.propensity(calm) - 0.01 or wc.propensity(nervy) > wc.propensity(calm) * 2)
check("closeness: a child counts for more than a stranger", wc.closeness(nervy, "kid") > wc.closeness(nervy, "nobody"))
check("severity is base x closeness x propensity, clamped to 1-10",
      wc.compute_severity(nervy, 4, "kid") == min(10.0, round(4 * wc.propensity(nervy) * 1.5, 1)) and wc.compute_severity(calm, 0.1) == 1.0 and wc.compute_severity(nervy, 99) == 10.0)

# ---- registering -----------------------------------------------------------------------------------------------------
a = person("a")
w = world(1000, a=a)
check("below the registration threshold nothing is registered", wc.register_worry(a, SELF, 1.5, "t", "meh", w) is None and not a.get("worry_cases"))
case = wc.register_worry(a, P("b", "Bea"), 5, "t", "Bea is not herself", w, tags=["pattern"], summary="Bea is not herself")
check("a case is created with severity, cost, expiry and tags", case and case["severity"] == 5 and case["focus_cost"] == 10
      and case["expires"] == 1000 + 5 * HOUR and "b" in case["tags"] and "pattern" in case["tags"] and case["status"] == "active")
check("focus is reduced by the cost", a["focus_state"]["available"] == 90 and wc.focus_available(a, w) == 90)
check("registering stores a memory that is not mistaken for evidence", any("worry_case" in m["tags"] for m in a["memories"]))

# the same subject refreshes instead of duplicating
w["tick"] = 1500
again = wc.register_worry(a, P("b", "Bea"), 5, "t2", "and again", w)
check("one case per subject: a repeat refreshes it", again is case and len(a["worry_cases"]) == 1 and case["refreshes"] == 1 and len(case["evidence"]) == 2)
check("a refresh extends the expiry", case["expires"] == 1500 + case["severity"] * HOUR)
check("a refresh nudges severity by at most one", case["severity"] == 6.0, str(case["severity"]))
for i in range(6):
    w["tick"] += 10
    wc.register_worry(a, P("b", "Bea"), 5, "t", "more", w)
check("severity never rises above what was reported + 2", case["severity"] <= 7.0, str(case["severity"]))
check("evidence is capped", len(case["evidence"]) <= wc.MAX_EVIDENCE)

# cost cap and load cap
big = person("big")
wb = world(0, big=big)
wc.register_worry(big, SELF, 10, "t", "everything is falling apart", wb)
check("a severity-10 case costs 20 focus, and no case can cost more than CASE_COST_CAP",
      big["worry_cases"]["self:"]["focus_cost"] == 20 and wc._focus_cost(99) == wc.CASE_COST_CAP)
for i in range(6):
    wc.register_worry(big, {"kind": "event", "ref": f"e{i}", "label": f"e{i}"}, 10, "t", f"event {i}", wb)
check("worries together never take more than MAX_LOAD", big["focus_state"]["load"] == wc.MAX_LOAD and big["focus_state"]["available"] == 100 - wc.MAX_LOAD)

# areas
b = person("b")
wb2 = world(0, b=b)
area = wc.register_worry(b, {"kind": "area", "ref": "finances", "label": "finances"}, 9, "news", "bills are piling up", wb2)
check("a generic area is capped at severity 3 and lasts half as long per point",
      area and area["severity"] == 3 and area["expires"] == int(3 * HOUR * 0.5))
other = wc.register_worry(b, {"kind": "area", "ref": "politics", "label": "politics"}, 3, "news", "a headline", wb2)
check("no second area while one is active", other is None)
wc.register_worry(b, SELF, 4, "t", "something specific", wb2)
check("but a specific worry can be added next to an area", len(wc.active_cases(b)) == 2)
c2 = person("c2")
wc.register_worry(c2, SELF, 4, "t", "specific", world(0, c2=c2))
check("an area is not created while a specific worry is active",
      wc.register_worry(c2, {"kind": "area", "ref": "media", "label": "media"}, 3, "news", "x", world(0, c2=c2)) is None)

# small children
kid = person("kid", age=5, rel={"mum": {"kinship": "parent"}})
wk = world(0, kid=kid)
check("a small child does not worry about a stranger", wc.register_worry(kid, P("stranger"), 5, "t", "x", wk) is None)
check("... but does about their parent and about themselves",
      wc.register_worry(kid, P("mum"), 5, "t", "mum is sad", wk) and wc.register_worry(kid, SELF, 4, "t", "my tummy", wk))

check("a small child has no worries about politics or money, but may about family",
      wc.register_worry(kid, {"kind": "area", "ref": "politics", "label": "politics"}, 3, "news", "x", wk) is None
      and wc.register_worry(person("kid2", age=6), {"kind": "area", "ref": "family", "label": "family"}, 3, "memory", "mum and dad argued", world(0)) is not None)

# ---- expiry and closing -------------------------------------------------------------------------------------------------
e = person("e")
we = world(0, e=e)
wc.register_worry(e, SELF, 2, "t", "small", we)
wc.register_worry(e, P("f"), 6, "t", "big", we)
we["tick"] = 2 * HOUR + 1
wc.update_focus(e, we)
check("a case lapses when its time is up", e["worry_cases"]["self:"]["status"] == "lapsed" and e["worry_cases"]["person:f"]["status"] == "active")
check("and gives its focus back", e["focus_state"]["available"] == 100 - e["worry_cases"]["person:f"]["focus_cost"])
wc.close_case(e, "person:f", we, reason="it was nothing")
check("closing a case frees its focus", e["focus_state"]["available"] == 100 and e["worry_cases"]["person:f"]["status"] == "resolved")
check("a closed subject can be worried about again", wc.register_worry(e, P("f"), 5, "t", "again", we)["status"] == "active")
many = person("many")
wm = world(0, many=many)
for i in range(12):
    wm["tick"] = i * 10 * HOUR
    wc.register_worry(many, {"kind": "event", "ref": f"x{i}", "label": "x"}, 2, "t", "n", wm)
wm["tick"] = 500 * HOUR
wc.update_focus(many, wm)
wc.register_worry(many, SELF, 2, "t", "n", wm)
check("closed cases are pruned", sum(1 for cs in many["worry_cases"].values() if cs["status"] != "active") <= wc.KEEP_CLOSED_CASES)

# ---- the poll ---------------------------------------------------------------------------------------------------------------
class Trap(dict):
    """A memory the poll must never look inside: it is older than the last poll."""
    def get(self, key, default=None):
        if key == "tick":
            return dict.get(self, "tick", default)
        raise AssertionError("an old memory was examined")


p = person("p")
wp = world(10 * HOUR, p=p)
wc.register_worry(p, P("q", "Quinn"), 5, "t", "Quinn is acting strange", wp, tags=["pattern"])
p["focus_state"]["last_poll"] = 10 * HOUR
p["memories"] = [Trap(id=f"old{i}", tick=i, text="boom", tags=["x"]) for i in range(2000)]
wp["tick"] = 11 * HOUR
p["memories"] += [
    {"id": "m1", "tick": 10 * HOUR + 50, "text": "Quinn snapped at me", "tags": ["conflict"], "people": ["q"], "importance": 0.4, "emotional_impact": -0.3},
    {"id": "m2", "tick": 10 * HOUR + 60, "text": "I walked to the shop", "tags": ["errand"], "people": [], "importance": 0.2},
    {"id": "m3", "tick": 10 * HOUR + 70, "text": "worry about quinn", "tags": ["worry_case"], "people": ["q"], "importance": 0.9},
]
before = wc.active_cases(p)[0]["expires"]
res = wc.poll_worries(p, wp)
case = p["worry_cases"]["person:q"]
check("the poll refreshes a case when its person shows up in new memories", "person:q" in res["refreshed"] and case["expires"] > before and case["evidence"][-1]["ref"] == "m1")
check("it never looks at memories older than the last poll", True)         # the Trap would have raised
check("a memory about the worry itself is not evidence", all(ev["ref"] != "m3" for ev in case["evidence"]))
check("an unrelated memory changes nothing", all(ev["ref"] != "m2" for ev in case["evidence"]))

# area worry from a bad memory, when nothing else is on their mind
r = person("r")
wr = world(5 * HOUR, r=r)
r["focus_state"] = {"last_poll": 4 * HOUR}
r["memories"] = [{"id": "m9", "tick": 4 * HOUR + 5, "text": "My boss said there might be layoffs.", "tags": ["work"], "people": [], "importance": 0.6, "emotional_impact": -0.4}]
res = wc.poll_worries(r, wr)
check("a negative workplace memory starts a workplace worry", res["started"] == ["area:workplace"] and r["worry_cases"]["area:workplace"]["severity"] <= wc.AREA_SEVERITY_CAP)
r2 = person("r2")
wr2 = world(5 * HOUR, r2=r2)
r2["focus_state"] = {"last_poll": 4 * HOUR}
r2["memories"] = [{"id": "m8", "tick": 4 * HOUR + 5, "text": "Lovely sunny day, my boss brought donuts.", "tags": ["work"], "people": [], "importance": 0.3, "emotional_impact": 0.5}]
check("a pleasant memory in the same area does not", wc.poll_worries(r2, wr2)["started"] == [])

# news
n = person("n")
wn = world(5 * HOUR, n=n)
wn["news"] = [{"id": "nw1", "tick": 4 * HOUR + 100, "headline": "Wave of burglaries hits the harbor district", "summary": "police advise caution",
               "sentiment": "negative", "intensity": 0.7, "tags": ["local", "crime"], "related_entities": []}]
n["focus_state"] = {"last_poll": 4 * HOUR}
check("negative news starts a neighbourhood worry", wc.poll_worries(n, wn)["started"] == ["area:neighbourhood"])
n2 = person("n2")
wn2 = world(5 * HOUR, n2=n2)
wn2["news"] = [dict(wn["news"][0], sentiment="positive")]
n2["focus_state"] = {"last_poll": 4 * HOUR}
check("positive news does not", wc.poll_worries(n2, wn2)["started"] == [])

# scheduling: staggered, about once an hour
chars = {f"c{i}": person(f"c{i}") for i in range(20)}
ws = world(100000, **chars)
wc.tick_worry_polls(ws)
lasts = [c["focus_state"]["last_poll"] for c in chars.values()]
check("characters are spread over the hour on first sight", len(set(lasts)) > 10 and all(100000 - HOUR < t <= 100000 for t in lasts))
polled_at = {cid: c["focus_state"]["last_poll"] for cid, c in chars.items()}
ws["tick"] = 100000 + 600
wc.tick_worry_polls(ws)
repolled = sum(1 for cid, c in chars.items() if c["focus_state"]["last_poll"] != polled_at[cid])
check("only those whose hour is up are polled again", 0 < repolled < 20, str(repolled))

# ---- the prompt line ------------------------------------------------------------------------------------------------------------
s = person("s")
wsx = world(0, s=s)
check("no worries, no line", wc.context_lines(s, wsx) == [])
wc.register_worry(s, P("t", "Tess"), 4, "t", "Tess has been so quiet lately", wsx)
lines = wc.context_lines(s, wsx)
check("a worry shows up as a line", lines and "Tess has been so quiet lately" in lines[0], str(lines))
for i in range(4):
    wc.register_worry(s, {"kind": "event", "ref": f"ev{i}", "label": "x"}, 8, "t", f"event {i}", wsx)
check("when focus is low the line says so", any("barely concentrate" in l for l in wc.context_lines(s, wsx)))
check("at most three cases are listed", sum(1 for l in wc.context_lines(s, wsx) if l.startswith("On your mind")) == 3)

# ---- producers ------------------------------------------------------------------------------------------------------------------
from systems import pattern_concern as pcn
from systems.activities import ACTIVITIES
CHORE = next(k for k, v in ACTIVITIES.items() if v.get("category") in pcn.IRRATIONAL_CATEGORIES and k not in pcn.BENIGN_ACTIVITIES)
obs = person("obs", rel={"sub": {"kinship": "sibling", "friendship": 20, "familiarity": 20}})
sub = person("sub", name="Sam")
sub["_loop_flagged"] = {}
wpc = world(50000, obs=obs, sub=sub)
pcn.check_sighting(obs, sub, wpc, CHORE)
wpc["tick"] += 100
res = pcn.check_sighting(obs, sub, wpc, CHORE)
check("noticing a repeating pattern opens a case about that person", res and "person:sub" in obs["worry_cases"]
      and obs["worry_cases"]["person:sub"]["subject"]["label"] == "Sam", str(obs.get("worry_cases")))
sev0 = obs["worry_cases"]["person:sub"]["severity"]
pcn.check_sighting(obs, sub, wpc, "stretch")
wpc["tick"] += 100
pcn.check_sighting(obs, sub, wpc, "read")
check("when the pattern stops the case is resolved", obs["worry_cases"]["person:sub"]["status"] == "resolved", str(obs["worry_cases"]["person:sub"]["status"]))

from systems.worries import bump_suspicion
sus = person("sus", rel={"x": {"kinship": None, "friendship": 12, "familiarity": 9}})
wsu = world(1000, sus=sus, x=person("x", name="Xavier"))
bump_suspicion(sus, "x", 0.1, "routine_deviation", "left at an odd hour", wsu)
check("a little suspicion is not yet a case", not sus.get("worry_cases"))
bump_suspicion(sus, "x", 0.3, "routine_deviation", "came back with wet clothes", wsu)
check("enough suspicion becomes a case about that person", "person:x" in (sus.get("worry_cases") or {}), str(sus.get("worry_cases")))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
