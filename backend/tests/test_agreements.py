"""
What people agree to gets done -- or noticed when it isn't (systems/agreements.py; live 2026-11-28: 26 agreements on
record, every term "manual", so a compromise changed nothing).

A. Terms classified from their words (the live ones): a chore -> task (daily / weekly); "make a schedule" -> once;
   "knock before entering" -> rule.
B. sync(): the responsible person gets a real expectation (on their to-do list, labelled with the agreement), both
   sides get the agreement on their list; an ended contract takes it away again.
C. Doing a matching activity keeps it: the expectation met, the contract's term kept, both lists updated; once a period.
D. A period missed -> the agreement is broken (a violation reported, once per miss).
E. A one-off talk-it-through is done by talking with the other party again.
F. The prompt: what you agreed to, what others agreed to, rules.

Run inside the backend container:   python tests/test_agreements.py
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

# A
cases = {
    "clean the kitchen": ("task", "daily"), "handle the living room": ("task", "daily"),
    "clean up at the same time every day": ("task", "daily"), "Contribute to cleaning up after themselves": ("task", "daily"),
    "do the dishes after dinner": ("task", "daily"), "take out the trash on weekends": ("task", "weekly"),
    "Create a cleaning schedule": ("once", "once"), "Clean up after self, make schedule": ("task", "daily"),
    "knock or call before entering each other's homes": ("rule", None), "let each other know when they'll be late": ("rule", None),
    # live 2026-11-28, second look
    "cleaning up after dinner": ("task", "daily"), "check on Christopher Carter before bed": ("task", "daily"),
    "Tell an authorized person before leaving": ("rule", None), "be more understanding and patient with Christopher": ("rule", None),
    "stay focused on economic discussions": ("rule", None), "set aside time each week to discuss frustrations": ("task", "weekly"),
    "take care of recycling": ("task", "daily"), "get Daniel a drink": ("once", "once"),
}
for ob, (kind, cad) in cases.items():
    k, c_, acts = G.classify(ob)
    check(f"A: '{ob}' -> {kind}/{cad}", (k, c_) == (kind, cad), (k, c_, acts))
check("A: the dishes are kept by washing dishes", G.classify("do the dishes after dinner")[2][0] == "wash_dishes")
check("A: cleaning up after dinner is cleaning, not cooking", G.classify("cleaning up after dinner")[2][0] == "dust_and_wipe")
check("A: making a schedule is done by talking it through", G.classify("Create a cleaning schedule")[2] == [])

# B
world = {"tick": 1000, "calendar": {"year": 2026, "month": 11, "day": 28, "hour": 9, "weekday": "Saturday"},
         "definitions": {"expectation_templates": {}},
         "characters": {"d": {"id": "d", "name": "Daniel Martinez"}, "p": {"id": "p", "name": "Pamela Martinez"}},
         "social_contracts": {"k1": {"id": "k1", "title": "Household Chores Schedule", "parties": ["d", "p"], "state": "active",
                                     "terms": [{"id": "term_1", "responsible_party": "d", "obligation": "clean the kitchen", "status": "pending"},
                                               {"id": "term_2", "responsible_party": "p", "obligation": "knock before coming in", "status": "pending"}]}}}
G.sync(world)
d, p = world["characters"]["d"], world["characters"]["p"]
eid = [a for a in d["agreements"] if a["mine"] and a["kind"] == "task"][0]["expectation_id"]
check("B: Daniel's task is a real expectation, labelled with the agreement", eid in d.get("expectations", {})
      and d["expectations"][eid]["label"] == "clean the kitchen (agreed with Pamela)" and eid.startswith("dust_and_wipe_agreed"), d.get("expectations"))
check("B: both have it on their list", len(d["agreements"]) == 2 and len(p["agreements"]) == 2
      and any(not a["mine"] and a["obligation"] == "clean the kitchen" for a in p["agreements"]))
check("B: a rule makes no task", not any(a.get("expectation_id") for a in p["agreements"] if a["kind"] == "rule"))
G.sync(world)
check("B: syncing again changes nothing", len(d["agreements"]) == 2 and len(d["expectations"]) == 1)

# C
import social.contracts as SC
kept_calls = []
SC.kept = lambda world, k, rid, term_id=None: kept_calls.append((rid, term_id))
import systems.expectations as E
sat = []
E.satisfy_expectation = lambda c, e, w: sat.append(e) or True
G.on_activity_finished({"character_id": "d", "activity_type": "dust_and_wipe"}, world)
mine = [a for a in d["agreements"] if a["mine"]][0]
check("C: wiping the kitchen keeps it: expectation met, contract told", sat == [eid] and kept_calls == [("d", "term_1")]
      and mine["status"] == "kept" and mine["kept"] == 1, (sat, kept_calls, mine))
check("C: Pamela's list shows it kept too", [a for a in p["agreements"] if a["term_id"] == "term_1"][0]["status"] == "kept")
G.on_activity_finished({"character_id": "d", "activity_type": "wash_dishes"}, world)
check("C: once a day", mine["kept"] == 1)

# D
viol = []
SC.violation = lambda world, k, rid, what, **kw: viol.append((rid, what))
d["expectations"][eid]["missed_count"] = 1
G.check_missed(world)
check("D: a missed day -> the agreement broken, reported", viol == [("d", "clean the kitchen")] and mine["status"] == "missed", viol)
G.check_missed(world)
check("D: reported once per miss", len(viol) == 1)

# E
world["social_contracts"]["k2"] = {"id": "k2", "title": "Talk it out", "parties": ["d", "p"], "state": "active",
                                   "terms": [{"id": "term_1", "responsible_party": "d", "obligation": "talk with Pamela about the schedule"}]}
G.sync(world)
once = [a for a in d["agreements"] if a["contract_id"] == "k2"][0]
world["tick"] += 900
G.on_speech({"character_id": "d", "target_id": "p"}, world)
check("E: a talk-it-through is done by talking with her again", once["status"] == "done", once)

# duplicates and lapsing
world["social_contracts"]["k3"] = {"id": "k3", "title": "Again", "parties": ["d", "p"], "state": "active", "created_tick": 5000,
                                   "terms": [{"id": "term_1", "responsible_party": "d", "obligation": "Clean the kitchen."}]}
G.sync(world)
check("B: the same promise agreed again -> one entry, one task", sum(1 for a in d["agreements"] if a["mine"] and "kitchen" in a["obligation"].lower()) == 1
      and sum(1 for e in d["expectations"].values() if "kitchen" in str(e.get("label", "")).lower()) == 1, [a["obligation"] for a in d["agreements"]])
del world["social_contracts"]["k3"]
G.sync(world)
world["social_contracts"]["k4"] = {"id": "k4", "title": "Errand", "parties": ["d", "p"], "state": "active",
                                   "terms": [{"id": "term_1", "responsible_party": "d", "obligation": "get Pamela a drink"}]}
G.sync(world)
errand = [a for a in d["agreements"] if a["contract_id"] == "k4"][0]
world["tick"] += G.ONCE_LAPSE_TICKS + 10
G.sync(world)
check("B: a one-off left for days is let go, its task gone", errand["status"] == "lapsed" and errand["expectation_id"] not in d["expectations"])
del world["social_contracts"]["k4"]
G.sync(world)

# F
lines = G.prompt_lines(d, world)
check("F: the prompt says what you agreed to, and the rules", any(l.startswith("What you agreed to do: clean the kitchen every day -- agreed with Pamela") for l in lines)
      and any(l.startswith("What you agreed on: knock before coming in") for l in lines), lines)
check("F: and what the other agreed to", any(l.startswith("What others agreed to do: Daniel: clean the kitchen") for l in G.prompt_lines(p, world)), G.prompt_lines(p, world))

# B (ended)
world["social_contracts"]["k1"]["state"] = "terminated"
G.sync(world)
check("B: an ended agreement is taken off both lists, its task gone", not any(a["contract_id"] == "k1" for a in d["agreements"])
      and eid not in d["expectations"])

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
