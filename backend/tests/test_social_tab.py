"""
The Social tab and agreements on the schedule.

A. parse_time: a time in an agreement -- "after dinner", "on Sundays", "by 9pm", "Saturday at 10am", "from 4 to 6" --
   becomes a window (and days); "clean the kitchen", "30 minutes at most" have none.
B. sync(): the expectation behind a timed term gets that window (time_window), its label says when; a weekly one on a
   named day; a term re-read later gets its new window.
C. expectations: a daily timed expectation's window is today at that time, and it's missed once that's gone by
   without it; a weekly one falls on its day; agreed after its time today -> nothing to miss today; a one-off with a
   time is due the next time it comes round.
D. api/social.py: the list (mine / everyone), and one agreement in full -- terms, people with their responsibilities,
   expectations (with the agreed time on the schedule), rights and breaches.

Run inside the backend container:   python tests/test_social_tab.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import systems.agreements as G
import systems.expectations as E

# A
P = G.parse_time
check("A: after dinner", (P("clean up after dinner") or {}).get("start") == "18:30")
t = P("take out the trash on Sundays") or {}
check("A: on Sundays -> Sunday, all day", t.get("weekdays") == [6] and t.get("start") == "00:00", t)
t = P("be home by 9pm") or {}
check("A: by 9pm -> the two hours before 21:00", (t.get("start"), t.get("end")) == ("19:00", "21:00"), t)
t = P("talk about it Saturday at 10am") or {}
check("A: Saturday at 10am", t.get("weekdays") == [5] and t.get("start") == "10:00", t)
t = P("do homework from 4 to 6") or {}
check("A: from 4 to 6 -> 16:00-18:00", (t.get("start"), t.get("end")) == ("16:00", "18:00"), t)
check("A: the term's own deadline counts", (P("tidy the garage", {"deadline": "Friday evening"}) or {}).get("weekdays") == [4])
check("A: no time -> None", P("clean the kitchen") is None and P("spend 30 minutes at most on it") is None)

# B
cal = {"year": 2026, "month": 11, "day": 28, "weekday": "saturday", "hour": 12, "minute": 0}
def mk_world():
    d = {"id": "d", "name": "Daniel Martinez"}
    p = {"id": "p", "name": "Pamela Martinez"}
    return {"tick": 100000, "calendar": dict(cal), "characters": {"d": d, "p": p}, "social_contracts": {
        "k1": {"id": "k1", "parties": ["d", "p"], "state": "active", "status": "active", "created_tick": 90000,
               "title": "Household chores", "terms": [
                   {"id": "term_1", "responsible_party": "d", "obligation": "clean up after dinner"},
                   {"id": "term_2", "responsible_party": "p", "obligation": "take out the trash on Sundays"},
                   {"id": "term_3", "responsible_party": "p", "obligation": "knock before coming in"}]}}}
w = mk_world()
G.sync(w)
d, p = w["characters"]["d"], w["characters"]["p"]
a1 = next(a for a in d["agreements"] if a["mine"])
e1 = d["expectations"][a1["expectation_id"]]
check("B: the timed term's expectation has the agreed window", e1.get("time_window") == {"start": "18:30", "end": "20:30", "weekdays": None}, e1.get("time_window"))
check("B: its label says it's agreed (and with whom)", "agreed with Pamela" in e1.get("label", ""), e1.get("label"))
a2 = next(a for a in p["agreements"] if a["mine"] and a["kind"] == "task")
e2 = p["expectations"][a2["expectation_id"]]
check("B: the Sunday term is weekly, on Sunday", e2["cadence"] == "weekly" and e2["time_window"]["weekdays"] == [6], e2)
check("B: ...and the label says when", "Sundays" in e2["label"] or "Sunday" in e2["label"], e2["label"])
w["social_contracts"]["k1"]["terms"][0]["obligation"] = "clean up after dinner every evening at 7pm"
G.sync(w)
check("B: re-read with a new time -> the new window", d["expectations"][a1["expectation_id"]]["time_window"]["start"] == "19:00",
      d["expectations"][a1["expectation_id"]]["time_window"])
w["social_contracts"]["k1"]["terms"][0]["obligation"] = "clean up after dinner"
G.sync(w)

# C
E._apply_miss_feedback = lambda c, nd, world: None
E.assign_expectations = lambda c, defs, world=None: None
E._refresh_intention = lambda c, nd, world: None
import brain.intentions as BI
BI.remove_intention = lambda c, t: None
E.update_expectations(d, w)
e1 = d["expectations"][a1["expectation_id"]]
start_expected = w["tick"] + (18 * 60 + 30 - 12 * 60) * 60
check("C: today's window is 18:30-20:30", (e1["window_start_tick"], e1["window_end_tick"]) == (start_expected, start_expected + 2 * 3600),
      (e1["window_start_tick"], e1["window_end_tick"], start_expected))
check("C: pending until then", e1["status"] == "pending")
w["tick"] = e1["window_end_tick"] + 60
w["calendar"].update(hour=20, minute=31)
E.update_expectations(d, w)
check("C: gone by without it -> missed", e1["status"] == "missed" and e1["missed_count"] == 1, e1)

w = mk_world()
G.sync(w)
p = w["characters"]["p"]
E.update_expectations(p, w)
e2 = next(e for e in p["expectations"].values() if (e.get("time_window") or {}).get("weekdays") == [6])
sunday = w["tick"] + (24 * 60 - 12 * 60) * 60
check("C: the weekly one falls on Sunday", e2["window_start_tick"] == sunday and e2["window_end_tick"] == sunday + 86400,
      (e2["window_start_tick"], sunday))

w = mk_world()
w["calendar"].update(hour=21, minute=0)
G.sync(w)
d = w["characters"]["d"]
E.update_expectations(d, w)
e1 = next(iter(d["expectations"].values()))
check("C: agreed after tonight's window -> nothing to miss today", e1["status"] == "satisfied" and e1.get("not_applicable"), e1)

c = {"id": "x", "expectations": {}}
eo = E.synthesize_expectation(c, "talk_once", "once", "chores", True)
eo["time_window"] = {"start": "10:00", "end": "11:00", "weekdays": [5]}
w2 = {"tick": 500000, "calendar": dict(cal, hour=12)}
E.update_expectations(c, w2)
nxt = w2["tick"] + (7 * 24 * 60 + 10 * 60 - 12 * 60) * 60
check("C: a one-off on Saturday at 10, agreed Saturday noon -> next Saturday 10:00", eo["window_start_tick"] == nxt,
      (eo["window_start_tick"], nxt))

# D
w = mk_world()
G.sync(w)
w["social_contracts"]["k1"]["violation_records"] = [{"responsible_party": "p", "evidence": "didn't take out the trash",
                                                     "timestamp": 99000, "observed_by": "d"}]
w["social_contracts"]["k2"] = {"id": "k2", "parties": ["p", "x"], "state": "terminated", "status": "cancelled",
                               "terms": [{"id": "term_1", "responsible_party": "p", "obligation": "feed the cat"}]}
import types
sys.modules.setdefault("db", types.SimpleNamespace(load_world=lambda sim_id="default": w))   # no database needed
import api.social as S
S.load_world = lambda sim_id="default": w
mine = S.contracts(char_id="d")["contracts"]
check("D: Daniel's list: just his agreement", [k["id"] for k in mine] == ["k1"] and mine[0]["in_force"], mine)
every = S.contracts(char_id="d", scope="all")["contracts"]
check("D: everyone's: both, the ended one last", [k["id"] for k in every] == ["k1", "k2"] and not every[1]["in_force"], every)
k = S.contract("k1")
dan = next(x for x in k["people"] if x["id"] == "d")
pam = next(x for x in k["people"] if x["id"] == "p")
check("D: what was agreed: three terms, who does each", [t["responsible_name"] for t in k["terms_detail"]] == ["Daniel", "Pamela", "Pamela"])
check("D: Daniel's responsibility", [r["obligation"] for r in dan["responsibilities"]] == ["clean up after dinner"], dan["responsibilities"])
check("D: ...expected of him: on the schedule at the agreed time", dan["expectations"] and dan["expectations"][0]["agreed_time"] == "18:30–20:30",
      dan["expectations"])
check("D: Daniel's rights: Pamela's trash, and her rule", any("take out the trash" in r for r in dan["rights"])
      and any("knock before coming in" in r for r in dan["rights"]), dan["rights"])
check("D: Pamela's rights: Daniel cleans up after dinner", any("Daniel clean up after dinner" in r for r in pam["rights"]), pam["rights"])
check("D: the breach is Pamela's", len(pam["breaches"]) == 1 and not dan["breaches"], (pam["breaches"], dan["breaches"]))
check("D: rules aren't expectations", all("knock" not in e["label"] for e in pam["expectations"]), pam["expectations"])

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
