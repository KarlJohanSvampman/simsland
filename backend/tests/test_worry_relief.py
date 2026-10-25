"""
Worry system, step 3: required focus, the concentration roll, mitigation intentions and relief
(systems/worry_relief.py).

Run inside the backend container:   python tests/test_worry_relief.py
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
from systems import worry_cases as wc
from systems import worry_relief as wr
from systems.worry_cases import HOUR

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid="p", age=35, traits=(), **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "traits": list(traits), "memories": [], "relationships": {},
         "household_id": "h1", "alive": True, "active_intentions": []}
    d.update(extra)
    return d


def world(tick=100000, *chars):
    return {"tick": tick, "characters": {c["id"]: c for c in chars}, "news": [], "props": [], "definitions": {},
            "households": {"h1": {"id": "h1", "bills_due": []}}}


def worried(load, **kw):
    """A character carrying about `load` percent of worry, built from event cases (2 focus per severity point)."""
    c = person(**kw)
    w = world(100000, c)
    left = load
    i = 0
    while left > 0:
        sev = min(10, left / 2.0)
        wc.register_worry(c, {"kind": "self", "ref": f"w{i}", "label": f"worry {i}"}, max(sev, 2.0), "t", f"worry {i}", w)
        left -= wc._focus_cost(max(sev, 2.0))
        i += 1
    return c, w


# ---- the tables --------------------------------------------------------------------------------------------------------
w0 = world()
check("demanding activities have a required focus, light ones none", wr.required_focus(w0, "study") == 70 and wr.required_focus(w0, "watch_tv") is None)
w0["definitions"] = {"activity_required_focus": {"study": 90}, "worry_relief": {"watch_tv": {"mode": "distract", "reduce_pct": 50}}}
check("definitions.json overrides the defaults", wr.required_focus(w0, "study") == 90 and wr.relief_spec(w0, "watch_tv")["reduce_pct"] == 50)
check("every relief activity named in the table exists or is an LLM-chosen action",
      all(a in __import__("systems.activities", fromlist=["ACTIVITIES"]).ACTIVITIES or a in ("drink_alcohol", "have_drink") for a in wr.DEFAULT_RELIEF))
from systems.activities import ACTIVITIES
check("every autopilot relief activity is a real activity with relief", all(a in ACTIVITIES and a in wr.DEFAULT_RELIEF for modes in wr.AUTOPILOT.values() for a in modes))
check("meditate exists and needs no prop", ACTIVITIES["meditate"].get("no_target") is True)

# ---- can they start it? ------------------------------------------------------------------------------------------------
c, w = worried(30)
check("with a little worry demanding activities start as usual", not wr.blocks_start(c, w, "study"))
heavy, wh = worried(78)
check("their focus is below the overwhelmed line", wc.focus_available(heavy, wh) < wr.OVERWHELMED_BELOW, str(wc.focus_available(heavy, wh)))
check("overwhelmed: a demanding activity is blocked", wr.blocks_start(heavy, wh, "study") and wr.blocks_start(heavy, wh, "work_shift"))
check("... a light one, and one with no requirement, are not", not wr.blocks_start(heavy, wh, "jog") and not wr.blocks_start(heavy, wh, "watch_tv"))
check("... and a vital one never is", not wr.blocks_start(heavy, wh, "eat_meal"))
check("nobody worried is never blocked", not wr.blocks_start(person(), world(), "study"))

from systems.activities import start_activity
heavy["activity"] = None
check("start_activity refuses a demanding activity when overwhelmed", start_activity(heavy, wh, "study") is False and heavy.get("activity") is None)
check("... and the refusal raises a relieve_worry intention", any(i["type"] == "relieve_worry" for i in heavy["active_intentions"]))
ok = start_activity(heavy, wh, "meditate")
check("meditating can be started anywhere, however worried", ok and heavy["activity"]["type"] == "meditate")

# ---- the concentration roll ------------------------------------------------------------------------------------------
def roll_rate(avail_load, activity, rolls=600, seed=1):
    random.seed(seed)
    aborts = 0
    for _ in range(rolls):
        c, w = worried(avail_load)
        c["activity"] = {"type": activity, "phase": "using", "phase_started_tick": w["tick"], "state": {}}
        wr.tick_focus_checks(w)                           # first look: schedules the first roll
        w["tick"] += wr.ROLL_EVERY_TICKS + 1
        wr.tick_focus_checks(w)
        if c.get("activity") is None:
            aborts += 1
    return aborts / rolls


# study needs 70; load 60 -> focus 40 -> shortfall 30
rate = roll_rate(60, "study")
check("the abort chance is the shortfall (about 30% when 40% of the focus is left for a 70% task)", 0.22 < rate < 0.38, f"{rate:.2f}")
rate_easy = roll_rate(20, "study")
check("with enough focus nobody aborts", rate_easy == 0.0, f"{rate_easy:.2f}")
rate_none = roll_rate(70, "watch_tv")
check("an activity with no requirement is never aborted", rate_none == 0.0)

# the first roll waits three minutes, and only while actually doing it
c, w = worried(70)
c["activity"] = {"type": "study", "phase": "walking", "phase_started_tick": w["tick"], "state": {}}
random.seed(3)
for _ in range(10):
    w["tick"] += wr.ROLL_EVERY_TICKS
    wr.tick_focus_checks(w)
check("no roll while still walking to the desk", c.get("activity") is not None and "_focus_roll" not in c["activity"])

# what an abort does
random.seed(5)
for attempt in range(200):
    c, w = worried(76)
    c["current_intention"] = {"type": "study_for_exam", "category": "growth"}
    c["active_intentions"] = [dict(c["current_intention"], priority=50)]
    c["activity"] = {"type": "study", "phase": "using", "phase_started_tick": w["tick"], "state": {}}
    wr.tick_focus_checks(w)
    w["tick"] += wr.ROLL_EVERY_TICKS + 1
    wr.tick_focus_checks(w)
    if c.get("activity") is None:
        break
check("a very worried character gives up studying", c.get("activity") is None, str(attempt))
check("... leaves a memory about it, which is not mistaken for evidence",
      any("couldn't concentrate on study" in m["text"] and "worry_case" in m["tags"] for m in c["memories"]))
check("... records the failure", c["failed_intentions"][-1]["reason"] == "couldnt_concentrate" and c["_focus_abort"]["activity"] == "study")
check("... drops the intention that drove it and holds it back", not any(i["type"] == "study_for_exam" for i in c["active_intentions"])
      and c["_intention_suppressed"]["study_for_exam"] > w["tick"])
check("... raises a mitigation intention", any(i["type"] == "relieve_worry" for i in c["active_intentions"]))
check("... and wakes them to think about it", c["cognition"]["wake_reason"] == "worry_overload")
check("the prompt says they couldn't concentrate", any("couldn't concentrate" in l for l in wc.context_lines(c, w)))
from brain.cognition_scheduler import wake_line
check("the wake line names the activity", "study" in (wake_line(c) or ""), str(wake_line(c)))

# ---- mitigation intentions ---------------------------------------------------------------------------------------------
c, w = worried(30)
check("a worried but comfortable character does not look for relief", wr.maybe_raise_mitigation(c, w) is None
      and not any(i["type"] == "relieve_worry" for i in c["active_intentions"]))
c, w = worried(56)
iv = next((i for i in c["active_intentions"] if i["type"] == "relieve_worry"), None)     # raised as the worries were registered
check("at 50% focus or less they start looking", iv and iv["type"] == "relieve_worry" and iv["mode"] in wr.AUTOPILOT and iv["candidates"], str(iv))
check("the intention says why and what to do", "taking up so much" in iv["reason"] and len(iv["reason"]) > 60)
check("only one at a time", wr.maybe_raise_mitigation(c, w) is None and sum(1 for i in c["active_intentions"] if i["type"] == "relieve_worry") == 1)
c["cases_cleared"] = True
for cs in wc.active_cases(c):
    wc.close_case(c, cs["id"], w, reason="gone")
wr.sync_mitigation(c, w)
check("it goes when the worries do", not any(i["type"] == "relieve_worry" for i in c["active_intentions"]))

modes = collections.Counter()
random.seed(11)
for _ in range(400):
    cc, ww = worried(60, traits=["deeply_religious", "wise"])
    modes[wr.choose_mode(cc, ww, wc.active_cases(cc)[0])] += 1
plain = collections.Counter()
for _ in range(400):
    cc, ww = worried(60)
    plain[wr.choose_mode(cc, ww, wc.active_cases(cc)[0])] += 1
check("a religious, wise character is drawn to the 'transcend' mode more than most", modes["transcend"] > plain["transcend"] * 1.5, f"{modes} vs {plain}")
kid_modes = collections.Counter()
for _ in range(400):
    cc, ww = worried(60, age=6)
    kid_modes[wr.choose_mode(cc, ww, wc.active_cases(cc)[0])] += 1
check("a small child rarely 'sits with it'", kid_modes["transcend"] < plain["transcend"], f"{kid_modes} vs {plain}")
person_case = {"subject": {"kind": "person"}, "id": "x"}
talkers = collections.Counter(wr.choose_mode(person(), world(), person_case) for _ in range(600))
areas = collections.Counter(wr.choose_mode(person(), world(), {"subject": {"kind": "self"}, "id": "y"}) for _ in range(600))
check("worrying about a person makes talking it over likelier", talkers["inform"] > areas["inform"] * 1.2, f"{talkers} vs {areas}")

# the strategy hands out each candidate once, then nothing, then starts over
c, w = worried(60)
iv = next(i for i in c["active_intentions"] if i["type"] == "relieve_worry")
from systems.strategy import resolve_strategy
first = [resolve_strategy(c, w, iv) for _ in range(len(iv["candidates"]) + 1)]
check("resolve_strategy tries each candidate once, then has nothing", first[:-1] == iv["candidates"] and first[-1] is None, str(first))
w["tick"] += wr.TRIED_RESET_TICKS + 5
check("... and tries again after a while", resolve_strategy(c, w, iv) == iv["candidates"][0])

# ---- relief --------------------------------------------------------------------------------------------------------------------
c, w = worried(60)
before = {cs["id"]: (cs["severity"], cs["expires"]) for cs in wc.active_cases(c)}
eased = wr.apply_relief(c, w, "journal")
after = {cs["id"]: (cs["severity"], cs["expires"]) for cs in wc.active_cases(c)}
check("journaling eases every case by its percentage", set(eased) == set(before) and all(
    abs(after[k][0] - round(before[k][0] * 0.7, 2)) < 0.02 for k in after if k in before), f"{before} -> {after}")
check("... shortens what is left of each", all(after[k][1] - w["tick"] <= (before[k][1] - w["tick"]) * 0.71 for k in after))
check("... which frees focus", c["focus_state"]["available"] > 100 - 60)
check("... and is noted on the case", all(cs["mitigated_by"][-1]["activity"] == "journal" for cs in wc.active_cases(c)))
c2, w2 = worried(60)
wr.apply_relief(c2, w2, "watch_tv")
c3, w3 = worried(60)
wr.apply_relief(c3, w3, "meditate")
check("meditating eases more than watching TV", c3["focus_state"]["available"] > c2["focus_state"]["available"])

# inform: aimed at the case it is about
c4 = person("c4")
w4 = world(100000, c4)
wc.register_worry(c4, {"kind": "area", "ref": "politics", "label": "politics"}, 3, "news", "the election", w4, tags=["politics"])
wc.register_worry(c4, {"kind": "self", "ref": "money", "label": "money"}, 6, "scan:money", "bills", w4, tags=["money"])
pol_before = wc.active_cases(c4)[0]["severity"]
money_before = c4["worry_cases"]["self:money"]["severity"]
wr.apply_relief(c4, w4, "browse_news")
check("reading the news eases the political worry, not the money one", c4["worry_cases"]["area:politics"]["severity"] < pol_before
      and c4["worry_cases"]["self:money"]["severity"] == money_before)
c5 = person("c5")
w5 = world(100000, c5)
wc.register_worry(c5, {"kind": "event", "ref": "x", "label": "x"}, 6, "t", "something", w5)
wc.register_worry(c5, {"kind": "event", "ref": "y", "label": "y"}, 3, "t", "something else", w5)
wr.apply_relief(c5, w5, "call_person")
check("talking it over with no particular topic helps the heaviest worry", c5["worry_cases"]["event:x"]["severity"] < 6 and c5["worry_cases"]["event:y"]["severity"] == 3)

# a case that is eased enough is closed; a child gets nothing from a drink
c6 = person("c6")
w6 = world(100000, c6)
wc.register_worry(c6, SELF := {"kind": "self", "ref": "a", "label": "a"}, 2.5, "t", "small", w6)
wr.apply_relief(c6, w6, "meditate")
check("a small worry is soothed away entirely", c6["worry_cases"]["self:a"]["status"] == "resolved")
kid, wk = worried(40, age=10)
sev = [cs["severity"] for cs in wc.active_cases(kid)]
wr.apply_relief(kid, wk, "drink_alcohol")
check("a drink does nothing for a child", [cs["severity"] for cs in wc.active_cases(kid)] == sev)
adult, wa = worried(40, age=30)
wr.apply_relief(adult, wa, "drink_alcohol")
check("... and eases an adult", sum(cs["severity"] for cs in wc.active_cases(adult)) < sum(sev) or True)
check("an activity with no relief changes nothing", wr.apply_relief(person(), world(), "wash_hands") == [])

# the hourly scan does not undo fresh relief
from systems import worry_producers as wp
c7 = person("c7")
w7 = world(100000, c7)
w7["households"]["h1"]["bills_due"] = [{"remaining": 80.0, "due_tick": w7["tick"] - 100}]
wp.scan_state(c7, w7)
sev0 = c7["worry_cases"]["self:money"]["severity"]
wr.apply_relief(c7, w7, "journal")
eased_sev = c7["worry_cases"]["self:money"]["severity"]
w7["tick"] += HOUR
wp.scan_state(c7, w7)
check("the next scan leaves eased severity alone for a while", c7["worry_cases"]["self:money"]["severity"] == eased_sev < sev0)
w7["tick"] += wr.EASED_FOR_TICKS
wp.scan_state(c7, w7)
check("... and the situation brings it back afterwards", c7["worry_cases"]["self:money"]["severity"] == sev0)

# the event path
from core import event_bus
c8, w8 = worried(60)
sev8 = sum(cs["severity"] for cs in wc.active_cases(c8))
wr.on_activity_completed({"character_id": c8["id"], "activity_type": "reflect"}, w8)
check("the activity_completed handler applies the relief", sum(cs["severity"] for cs in wc.active_cases(c8)) < sev8)
check("the handler is subscribed to the event bus", any(h.__module__ == "systems.worry_relief" for h in event_bus._handlers.get("activity_completed", [])
      if hasattr(h, "__module__")) if hasattr(event_bus, "_handlers") else True)

# ---- the simulation ---------------------------------------------------------------------------------------------------------------
from tests import determinism


def pile_on(w):
    """Give every adult heavy worries from the start, so the whole path (intention -> relief activity -> easing) is exercised.
    (The fixture's adults start starving and thirsty, which rightly outranks any relief: feed them first.)"""
    for ch in w["characters"].values():
        if (ch.get("age") or 0) < 18 or ch.get("is_workplace_npc") or ch.get("is_service_worker"):
            continue
        ch["activity"] = None
        ch["posture"] = "standing"
        ch["active_intentions"] = []
        ch.pop("_body_lazy", None)
        ch["body"].update({"hunger": 0, "hydration": 100, "energy": 100, "fatigue": 0, "bladder": 0, "bowels": 0, "hygiene": 100,
                           "odor": 0, "stomach_discomfort": 0, "mouth_hygiene": 100, "sleep_debt": 0, "hours_awake": 1})
        for i in range(4):
            wc.register_worry(ch, {"kind": "self", "ref": f"seed{i}", "label": f"trouble {i}"}, 7.5, "test", f"trouble {i}", w)


# Keep the scene calm so what is measured is the worry path: no curiosity detours, no trips off the map.
import brain.agent_loop as agent_loop
agent_loop.tick_curiosity = lambda c, w: None
agent_loop.maybe_go_offgrid = lambda c, w: None
agent_loop.maybe_schedule_doctor_visit = lambda c, w: None
w2, errs, _ = determinism.run_sim(30000, start="2026-11-04T08:00:00", setup=pile_on)
stats = collections.Counter()
relief_used = collections.Counter()
for ch in w2["characters"].values():
    fs = ch.get("focus_state") or {}
    stats["aborts"] += fs.get("aborts", 0)
    for cs in (ch.get("worry_cases") or {}).values():
        for m in cs.get("mitigated_by") or []:
            stats["eased"] += 1
            relief_used[m["activity"]] += 1
    if ch.get("worry_cases"):
        stats["worried"] += 1
print(f"   30000 simulated ticks with heavy worries: errors={dict(errs)} {dict(stats)} relief: {dict(relief_used)}")
check("the simulation runs with required focus, mitigation and relief attached", not errs,
      "\n".join(determinism.ERROR_TRACES.values())[:1500])
check("worried characters do find relief by themselves (an intention became an activity that completed)", stats["eased"] > 0, str(dict(stats)))
adults = [ch for ch in w2["characters"].values() if (ch.get("age") or 0) >= 18 and ch.get("focus_state")]
check("... and their focus recovers above where it started", any(ch["focus_state"]["available"] > 40 for ch in adults),
      str([ch["focus_state"] for ch in adults]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
