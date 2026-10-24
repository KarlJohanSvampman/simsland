"""
Meeting people through people you know (systems/introductions.py).

Run inside the backend container:   python tests/test_introductions.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import introductions as intro

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, age=35, **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "traits": [], "memories": [], "relationships": {}, "alive": True,
         "perception": {"visible_people": []}}
    d.update(extra)
    return d


def know(a, b, friendship=30, trust=20, **kw):
    r = {"friendship": friendship, "trust": trust, "familiarity": 30, "interaction_count": 20, "hostility": 0}
    r.update(kw)
    a["relationships"][b["id"]] = r


def scene(m, *others):
    m["perception"]["visible_people"] = [{"id": o["id"]} for o in others]
    w = {"tick": 5000, "characters": {c["id"]: c for c in (m, *others)}}
    return w


def rel(a, b):
    return a["relationships"].get(b["id"]) or {}


random.seed(2)
intro.INTRO_CHANCE = 1.0


def basic(**mutate):
    m, a, b = person("m"), person("a"), person("b")
    for x in (a, b):
        know(m, x)
        know(x, m)
    w = scene(m, a, b)
    return m, a, b, w

# ---- the happy path -----------------------------------------------------------------------------------------------------
m, a, b, w = basic()
intro.tick_introductions(w)
check("a friend in view of two strangers introduces them", "b" in a["relationships"] and "a" in b["relationships"])
check("they now know each other and who introduced them", rel(a, b)["familiarity"] >= 6 and rel(a, b)["introduced_by"] == "m" and "introduced" in rel(a, b)["labels"], str(rel(a, b)))
check("with a little trust and friendship from the vouching", rel(a, b)["trust"] >= 2 and rel(a, b)["friendship"] >= 2)
check("all three remember it", all(any("introduc" in x["text"] for x in p["memories"]) for p in (m, a, b)))
check("it is logged", len(w["introductions"]) == 1)
before = dict(rel(a, b))
intro.tick_introductions(w)
check("only once per pair", rel(a, b) == before and len(w["introductions"]) == 1)
m2, a2, b2, w2 = basic()
for x in (a2, b2):
    m2["relationships"][x["id"]]["friendship"] = 60
    x["relationships"]["m"].update(friendship=80, trust=70)
intro.tick_introductions(w2)
check("a stronger vouch gives a warmer start", rel(a2, b2)["friendship"] > rel(a, b)["friendship"], f"{rel(a2, b2)['friendship']} vs {rel(a, b)['friendship']}")

# ---- who doesn't get introduced ---------------------------------------------------------------------------------------------
def blocked(name, mutate):
    m, a, b, w = basic()
    mutate(m, a, b, w)
    intro.tick_introductions(w)
    check(name, "b" not in a["relationships"] or "introduced" not in rel(a, b).get("labels", []))

blocked("not when they already know each other", lambda m, a, b, w: (know(a, b, friendship=20), know(b, a, friendship=20)))
blocked("not when one side has met the other a lot", lambda m, a, b, w: a["relationships"].update(b={"interaction_count": 5, "friendship": 0}))
blocked("not family", lambda m, a, b, w: a["relationships"].update(b={"kinship": "cousin"}))
blocked("not when the introducer hardly knows one of them", lambda m, a, b, w: m["relationships"]["b"].update(friendship=4))
blocked("not when one of them hardly trusts the introducer", lambda m, a, b, w: b["relationships"]["m"].update(friendship=2))
blocked("not when the introducer is hostile to one", lambda m, a, b, w: m["relationships"]["a"].update(hostility=40))
blocked("not when one holds a grudge against the introducer", lambda m, a, b, w: a.update(grudges={"m": {"offender": "m", "status": "open"}}))
blocked("not when the introducer is asleep", lambda m, a, b, w: m.update(activity={"type": "sleep"}))
blocked("not when one of them is asleep", lambda m, a, b, w: a.update(activity={"type": "sleep"}))
blocked("not when one is away", lambda m, a, b, w: b.update(off_grid=True))
blocked("not across ages: a child and a grown-up", lambda m, a, b, w: a.update(age=8))
m, a, b, w = basic()
m["perception"]["visible_people"] = [{"id": "a"}]
intro.tick_introductions(w)
check("not when only one of them is in view", "b" not in a["relationships"])
m, a, b, w = basic()
intro.INTRO_CHANCE = 0.0
intro.tick_introductions(w)
intro.INTRO_CHANCE = 1.0
check("the chance is a chance", "b" not in a["relationships"])
m = person("m")
m["traits"] = ["shy"]; shy = intro._chance(m); m["traits"] = ["extroverted"]; out = intro._chance(m); m["traits"] = []
check("shy people introduce less, outgoing people more", shy < intro._chance(m) < out, f"{shy} {intro._chance(m)} {out}")

# ---- children ---------------------------------------------------------------------------------------------------------------------
k, k1, k2 = person("k", 8), person("k1", 7), person("k2", 9)
for x in (k1, k2):
    know(k, x, friendship=12, trust=8)
    know(x, k, friendship=12, trust=8)
w = scene(k, k1, k2)
intro.tick_introductions(w)
check("a child introduces two other children at a lower bar of friendship", "k2" in k1["relationships"] and "introduced" in rel(k1, k2)["labels"])

# ---- hearsay: praise makes a stranger a name you know -----------------------------------------------------------------------------
from systems import rumors
l, s = person("l"), person("s")
rumors._shift_listener(l, "s", +1, 6)
check("a believed compliment about a stranger gives a little familiarity", rel(l, s)["familiarity"] == rumors.HEARD_OF_FAMILIARITY, str(rel(l, s)))
rumors._shift_listener(l, "s", -1, 6)
check("it is not repeated for gossip and never lowers familiarity", rel(l, s)["familiarity"] == rumors.HEARD_OF_FAMILIARITY)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
