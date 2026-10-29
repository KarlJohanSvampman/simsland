"""
Worry system, step 4: breakdown episodes (systems/worry_breakdown.py).

Run inside the backend container:   python tests/test_worry_breakdown.py
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
from systems import worry_breakdown as bd
from systems import worry_cases as wc
from systems.worry_cases import HOUR

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid="p", age=35, traits=(), **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "traits": list(traits), "memories": [], "relationships": {},
         "household_id": "h1", "alive": True, "active_intentions": [], "x": 1, "y": 1}
    d.update(extra)
    return d


def world(tick, *chars):
    return {"tick": tick, "characters": {c["id"]: c for c in chars}, "news": [], "props": [], "definitions": {},
            "households": {"h1": {"id": "h1", "bills_due": []}}}


def maxed(**kw):
    """A character carrying the maximum worry load (focus at the floor)."""
    c = person(**kw)
    w = world(100000, c)
    for i in range(5):
        wc.register_worry(c, {"kind": "self", "ref": f"w{i}", "label": f"trouble {i}"}, 10, "t", f"trouble {i}", w)
    return c, w


# ---- when ------------------------------------------------------------------------------------------------------------------
check("the trigger floor is the lowest focus worries can leave", bd.BREAKDOWN_AT == 100 - wc.MAX_LOAD == 20)
c, w = maxed()
check("at the floor", wc.focus_available(c, w) == bd.BREAKDOWN_AT)
check("not at the very first look", bd.should_break_down(c, w, 20) is None and "low_since" in c["focus_state"])
w["tick"] += bd.BREAKDOWN_AFTER_TICKS - 1
check("... nor a moment short of the time it takes", bd.should_break_down(c, w, 20) is None)
w["tick"] += 1
check("... but after long enough at the floor", bd.should_break_down(c, w, 20) == "overwhelmed")
c2, w2 = maxed()
bd.should_break_down(c2, w2, 20)
w2["tick"] += bd.BREAKDOWN_AFTER_TICKS + 10
bd.should_break_down(c2, w2, 45)
check("a moment of relief resets the clock", "low_since" not in c2["focus_state"] and bd.should_break_down(c2, w2, 20) is None)

c3, w3 = maxed()
c3["focus_state"]["breakdown_cooldown_until"] = w3["tick"] + 4 * bd.BREAKDOWN_AFTER_TICKS
w3["tick"] += bd.BREAKDOWN_AFTER_TICKS
bd.should_break_down(c3, w3, 20)
w3["tick"] += bd.BREAKDOWN_AFTER_TICKS
check("the cooldown holds it off", bd.should_break_down(c3, w3, 20) is None)

for label, kw in (("asleep", {"activity": {"type": "sleep"}}), ("away", {"off_grid": True}), ("a toddler", {"age": 2}),
                  ("unconscious", {"posture": "incapacitated"})):
    cc, ww = maxed(**kw)
    bd.should_break_down(cc, ww, 20)
    ww["tick"] += bd.BREAKDOWN_AFTER_TICKS + 5
    check(f"nobody who is {label} breaks down", bd.should_break_down(cc, ww, 20) is None)

# repeated failures
c4, w4 = person("c4"), world(500000)
for i in range(2):
    w4["tick"] += 600
    bd.note_abort(c4, w4)
check("two given-up activities are not yet a breakdown", bd.should_break_down(c4, w4, 70) is None)
w4["tick"] += 600
bd.note_abort(c4, w4)
check("three within two hours are", bd.should_break_down(c4, w4, 70) == "gave_up_too_often")
c5, w5 = person("c5"), world(500000)
for i in range(3):
    bd.note_abort(c5, w5)
    w5["tick"] += bd.BREAKDOWN_ABORT_WINDOW // 2 + 10
check("failures long ago don't count", bd.should_break_down(c5, w5, 70) is None)

# ---- the episode ---------------------------------------------------------------------------------------------------------------
import systems.activities as acts
started = []
real_start = acts.start_activity
acts.start_activity = lambda c, w, a: (started.append(a), True)[1]
import systems.occupancy as occ
occ.interrupt_activity = lambda c, w, **kw: c.__setitem__("activity", None)

random.seed(4)
c, w = maxed(traits=["calm"])
c["active_intentions"] = [{"type": "eat_food", "category": "survival", "priority": 88, "reason": "you are hungry"},
                          {"type": "study_for_exam", "category": "identity", "priority": 40, "reason": "the exam is on Friday"},
                          {"type": "relieve_worry", "category": "identity", "priority": 60, "reason": "worry"}]
bd.start_breakdown(c, w, "overwhelmed")
b = c["_breakdown"]
check("an episode lasts 10 to 30 sim-minutes", bd.EPISODE_TICKS[0] <= b["end"] - b["start"] <= bd.EPISODE_TICKS[1])
check("it begins with a beat straight away", b["beats"] == 1 and started and w["expressions"][-1]["intent"]["source"] == "breakdown")
check("their model is not asked and nothing pending", c["cognition"]["pending"] is None and c["cognition"]["next_think_tick"] > b["end"])
check("state is flagged", bd.in_breakdown(c) and c["focus_state"]["breakdowns"] == 1)

# beats every 1-3 minutes
beats_at = [w["tick"]]
for _ in range(60 * 30):
    w["tick"] += 1
    n = b["beats"]
    bd.tick_breakdown(c, w, 20) if w["tick"] % 60 == 0 else None
    if not bd.in_breakdown(c):
        break
    if b["beats"] != n:
        beats_at.append(w["tick"])
gaps = [y - x for x, y in zip(beats_at, beats_at[1:])]
check("beats come every one to three minutes (to the minute job's resolution)", gaps and all(60 <= g <= 240 for g in gaps), str(gaps))
check("the episode ends by itself", not bd.in_breakdown(c))

# what the beats do
pairs = collections.Counter()
for _ in range(200):
    cc, ww = maxed()
    cc["active_intentions"] = [{"type": "eat_food", "category": "survival", "priority": 88, "reason": "you are hungry"}]
    started.clear()
    cc["_breakdown"] = {"start": ww["tick"], "end": ww["tick"] + 1000, "next_beat": ww["tick"], "beats": 0, "why": "x", "witnesses": []}
    bd.beat(cc, ww)
    for a in started:
        pairs[a] += 1
from systems.activities import ACTIVITIES
check("the activities are not the intention's own, nor vital, nor someone's job",
      pairs and not (set(pairs) & {"eat_food", "eat_meal", "eat_snack", "sleep", "work_shift", "fight", "argue", "use_toilet"}), str(pairs))
check("they come from a variety of kinds", len({ACTIVITIES[a]["category"] for a in pairs}) >= 3, str({ACTIVITIES[a]["category"] for a in pairs}))
check("every one is a real activity of an allowed kind", all(a in ACTIVITIES and ACTIVITIES[a]["category"] in bd.ALLOWED_CATEGORIES for a in pairs))
kid = person("kid", age=6)
wk = world(100000, kid)
kid["_breakdown"] = {"start": 0, "end": 10 ** 6, "next_beat": 0, "beats": 0, "why": "x", "witnesses": []}
from systems.action_registry import ACTION_TYPE_MIN_AGE
kid_acts = set()
for _ in range(100):
    started.clear()
    bd.beat(kid, wk)
    kid_acts.update(started)
check("nothing a child isn't allowed to do", all(ACTION_TYPE_MIN_AGE.get(a, 0) <= 6 for a in kid_acts), str(kid_acts))

# what they say
hot = person("hot", traits=["hot_tempered"], perception={"visible_people": [{"id": "bystander"}]})
bystander = person("bystander", name="Bea")
wh = world(100000, hot, bystander)
hot["_breakdown"] = {"start": 0, "end": 10 ** 6, "next_beat": 0, "beats": 0, "why": "x", "witnesses": []}
random.seed(8)
for _ in range(60):
    bd.beat(hot, wh)
aimed = [e for e in wh["expressions"] if e["target"] == "bystander"]
check("a hot-tempered character sometimes lashes out at whoever is near", aimed and all(e["speech_act"] == "yell" for e in aimed), str(len(aimed)))
check("... and the person nearby counts as a witness", "bystander" in hot["_breakdown"]["witnesses"])
calm = person("calm2", traits=["calm"], perception={"visible_people": [{"id": "bystander"}]})
wcm = world(100000, calm, bystander)
calm["_breakdown"] = {"start": 0, "end": 10 ** 6, "next_beat": 0, "beats": 0, "why": "x", "witnesses": []}
for _ in range(60):
    bd.beat(calm, wcm)
check("a calm one never does", not [e for e in wcm["expressions"] if e["target"]])
check("the lines are one-way expressions (no conversation, no floor)", all(e["speech_act"] in ("vent", "yell", "mutter", "sigh") for e in wcm["expressions"])
      and not wcm.get("conversations"))

# survival needs still get through
calls = []
import systems.strategy as strategy
real_resolve = strategy.resolve_strategy
strategy.resolve_strategy = lambda c, w, i: (calls.append(i["type"]), "eat_meal")[1]
sv = person("sv")
sv["active_intentions"] = [{"type": "study", "category": "identity", "priority": 90}, {"type": "eat_food", "category": "survival", "priority": 70},
                           {"type": "check_in_on", "category": "social", "priority": 80}]
check("only a survival intention can take over during an episode", bd.survival_only(sv, world(1, sv)) and calls == ["eat_food"] and sv["current_intention"]["type"] == "eat_food", str(calls))
strategy.resolve_strategy = real_resolve

# ---- the end ---------------------------------------------------------------------------------------------------------------------
acts.start_activity = real_start
c, w = maxed()
before = {cs["id"]: cs["severity"] for cs in wc.active_cases(c)}
watcher = person("watcher", name="Wanda", rel=None, relationships={"p": {"kinship": "sibling", "friendship": 20, "familiarity": 20}})
stranger = person("stranger", relationships={})
w["characters"].update({"watcher": watcher, "stranger": stranger})
c["_breakdown"] = {"start": w["tick"] - 1200, "end": w["tick"], "next_beat": 0, "beats": 9, "why": "overwhelmed",
                   "witnesses": ["watcher", "stranger"]}
bd.end_breakdown(c, w)
check("the episode is over", not bd.in_breakdown(c))
check("30% of every case's severity is relieved", all(abs(cs["severity"] - round(before[cs["id"]] * 0.7, 2)) < 0.02 for cs in wc.active_cases(c)
      if cs["id"] in before), str({cs["id"]: cs["severity"] for cs in wc.active_cases(c)}))
check("... and it is noted", all(cs["mitigated_by"][-1]["activity"] == "breakdown" for cs in wc.active_cases(c) if cs["id"] in before))
check("a long cooldown starts", c["focus_state"]["breakdown_cooldown_until"] == w["tick"] + bd.BREAKDOWN_COOLDOWN_TICKS)
check("they remember it", any("fell apart" in m["text"] for m in c["memories"]))
check("they are left with a worry about the episode itself", wc.active_cases(c) and "self:breakdown" in c["worry_cases"])
check("someone who saw it is worried about them", "person:p" in (watcher.get("worry_cases") or {}) and "fell apart" in watcher["worry_cases"]["person:p"]["summary"])
check("and, being close, means to check in", any(i["type"] == "check_in_on" and i["target_id"] == "p" for i in watcher["active_intentions"]))
check("a stranger is merely shaken, doesn't plan to check in", not any(i["type"] == "check_in_on" for i in stranger["active_intentions"]))
check("they are woken to think again", c["cognition"]["wake_reason"] == "worry_overload")
check("the prompt says they broke down", any("broke down" in l for l in wc.context_lines(c, w)))

# ---- other systems respect the episode ---------------------------------------------------------------------------------------------
import brain.agent_loop as agent_loop
import brain.cognition_actor as ca
called = []
real_pd = agent_loop.process_decision
agent_loop.process_decision = lambda *a, **k: called.append(1)
d = person("d")
wd = world(1000, d)
d["cognition"] = {"pending": {"id": "r1", "tick": 1, "wall": 0, "wake_reason": "idle"}}
d["_breakdown"] = {"start": 0, "end": 10 ** 6, "next_beat": 10 ** 6, "beats": 1, "why": "x", "witnesses": []}
ca.on_decision_ready({"character_id": "d", "request_id": "r1", "decision": {"thought": "x", "action": {"type": "wait"}}, "wake_reason": "idle"}, wd)
check("a decision that arrives mid-episode is not acted on", called == [])
del d["_breakdown"]
d["cognition"] = {"pending": {"id": "r2", "tick": 1, "wall": 0, "wake_reason": "idle"}}
ca.on_decision_ready({"character_id": "d", "request_id": "r2", "decision": {"thought": "x", "action": {"type": "wait"}}, "wake_reason": "idle"}, wd)
check("... but is when there is none", called == [1])
agent_loop.process_decision = real_pd

# ---- the simulation ----------------------------------------------------------------------------------------------------------------------
from tests import determinism


def pile_on(w):
    """Maximum worries for the adults, fed and rested, so what is measured is the worry path."""
    for ch in w["characters"].values():
        if (ch.get("age") or 0) < 18 or ch.get("is_workplace_npc") or ch.get("is_service_worker"):
            continue
        ch["activity"] = None
        ch["posture"] = "standing"
        ch["active_intentions"] = []
        ch.pop("_body_lazy", None)
        ch["body"].update({"hunger": 0, "hydration": 100, "energy": 100, "fatigue": 0, "bladder": 0, "bowels": 0, "hygiene": 100,
                           "odor": 0, "stomach_discomfort": 0, "mouth_hygiene": 100, "sleep_debt": 0, "hours_awake": 1})
        for i in range(5):
            wc.register_worry(ch, {"kind": "self", "ref": f"seed{i}", "label": f"trouble {i}"}, 10, "test", f"trouble {i}", w)
        # the seeded scene has no relief within reach: strip it so the floor is held until an episode
        ch["focus_state"]["comfort_override"] = True


import brain.agent_loop as agent_loop2
agent_loop2.tick_curiosity = lambda c, w: None
agent_loop2.maybe_go_offgrid = lambda c, w: None
agent_loop2.maybe_schedule_doctor_visit = lambda c, w: None
import systems.worry_relief as wr
wr.maybe_raise_mitigation = lambda c, w, force=False: None            # nobody looks for relief: the floor holds
wr.sync_mitigation = lambda c, w, avail=None, **kw: None
SIM_TICKS = bd.BREAKDOWN_AFTER_TICKS + 3000     # long enough at the floor for the first episodes to start
w2, errs, _ = determinism.run_sim(SIM_TICKS, start="2026-11-04T08:00:00", setup=pile_on)
stats = collections.Counter()
for ch in w2["characters"].values():
    fs = ch.get("focus_state") or {}
    stats["breakdowns"] += fs.get("breakdowns", 0)
    if bd.in_breakdown(ch):
        stats["in_episode_now"] += 1
bd_exprs = [e for e in w2.get("expressions", []) if (e.get("intent") or {}).get("source") == "breakdown"]
print(f"   {SIM_TICKS} simulated ticks, maxed adults: errors={dict(errs)} {dict(stats)} breakdown lines={len(bd_exprs)} sample: {[e['text'] for e in bd_exprs[:3]]}")
check("the simulation runs with episodes attached", not errs)
check("adults at the floor really do break down", stats["breakdowns"] >= 2, str(dict(stats)))
check("... and say things aloud while they do", len(bd_exprs) >= 4, str(len(bd_exprs)))
adults = [ch for ch in w2["characters"].values() if (ch.get("age") or 0) >= 18 and ch.get("focus_state")]
check("after one, the cooldown keeps it from happening again at once",
      all(ch["focus_state"].get("breakdowns", 0) <= 1 + SIM_TICKS // bd.BREAKDOWN_COOLDOWN_TICKS for ch in adults))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
