"""
Worry tuning: envy is not a quarrel, quarrels alone cannot take all of someone's focus, a breakdown takes sustained overwhelm, and envy
grievances do not pile up (worry_producers.py, worry_cases.py, worry_breakdown.py, life_comparison.py).

Run inside the backend container:   python tests/test_worry_tuning.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import life_comparison as lc, worry_breakdown as bd, worry_cases as wc, worry_producers as wp

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def griev(who, kind, n, weight=0.5, tick=0):
    return [{"id": f"g{who}{kind}{i}", "caused_by": who, "event_type": kind, "weight": weight, "severity": weight, "tick": tick + i} for i in range(n)]


world = {"tick": 1000, "characters": {"x": {"name": "X Test"}, "y": {"name": "Y Test"}}}
c = {"id": "me", "grievances": griev("x", "life_envy", 20) + griev("y", "insult", 1, weight=20)}
want = wp._wanted_grievances(c, world)
check("a pile of small envy grievances is not an unsettled quarrel", "conflict:x" not in want, str(list(want)))
check("a real insult still is", "conflict:y" in want)
c2 = {"id": "me", "grievances": griev("x", "life_envy", 20, weight=3.0) + griev("x", "insult", 1, weight=13)}
check("envy on top of a real quarrel does not hide what the quarrel was", "insult" in wp._wanted_grievances(c2, world)["conflict:x"][2], str(wp._wanted_grievances(c2, world)))

me = {"id": "me", "worry_cases": {}}
for i in range(12):
    me["worry_cases"][f"c{i}"] = {"id": f"c{i}", "status": "active", "expires": 10**9, "focus_cost": 11, "subject": {"kind": "conflict", "ref": str(i)}}
check("a dozen quarrels take no more than the quarrel cap", wc.update_focus(me, world)["load"] == wc.CONFLICT_LOAD_CAP)
me["worry_cases"]["m"] = {"id": "m", "status": "active", "expires": 10**9, "focus_cost": 20, "subject": {"kind": "event", "ref": "e"}}
check("other worries add to it as before", wc.update_focus(me, world)["load"] == wc.CONFLICT_LOAD_CAP + 20)
check("so quarrels alone never put anyone at the floor", wc.CONFLICT_LOAD_CAP < wc.MAX_LOAD)

check("a breakdown takes an hour and a half at the floor", bd.BREAKDOWN_AFTER_TICKS >= 60 * 60)
check("... and the next not for most of a day", bd.BREAKDOWN_COOLDOWN_TICKS >= 12 * 3600)

pile = {"id": "me", "grievances": griev("x", "life_envy", 300) + griev("x", "insult", 2, weight=5) + griev("y", "life_envy", 3)}
dropped = lc.trim_envy_grievances(pile)
left_x = [g for g in pile["grievances"] if g["caused_by"] == "x" and g["event_type"] == "life_envy"]
check("an old pile of envy grievances is trimmed to the newest few", len(left_x) == lc.MAX_ENVY_GRIEVANCES_PER_PERSON and dropped == 295)
check("... the newest ones, and nothing else is touched", min(g["tick"] for g in left_x) >= 295 and len([g for g in pile["grievances"] if g["event_type"] == "insult"]) == 2
      and len([g for g in pile["grievances"] if g["caused_by"] == "y"]) == 3)
check("no more are added past the cap", lc.at_envy_cap(pile, "x") and not lc.at_envy_cap(pile, "y"))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
