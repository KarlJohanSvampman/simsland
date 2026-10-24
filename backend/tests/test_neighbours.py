"""
Who a character already knows from the street (systems/neighbours.py).

Run inside the backend container:   python tests/test_neighbours.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import neighbours as nb

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, age, household, hobbies=(), **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "household_id": household, "hobbies": list(hobbies), "traits": [],
         "memories": [], "relationships": {}, "alive": True}
    d.update(extra)
    return d


def town(*chars, homes=None):
    homes = homes or {"h1": (0, 0), "h2": (25, 0), "h3": (30, 10), "far": (300, 0)}
    return {"tick": 5000, "characters": {c["id"]: c for c in chars}, "households": {h: {"id": h} for h in homes},
            "buildings": [{"id": f"b_{h}", "x": x, "y": y, "owner_household_id": h} for h, (x, y) in homes.items()]}


def rel(a, b):
    return (a.get("relationships") or {}).get(b["id"]) or {}


random.seed(3)

# ---- where people live --------------------------------------------------------------------------------------------------
w = town(person("a", 30, "h1"))
check("a household's home is its owned building", nb.home_position(w, "h2") == (25, 0))
w["buildings"][1]["owner_household_id"] = None
w["households"]["h2"]["home_id"] = "b_h2"
check("or the building the household names", nb.home_position(w, "h2") == (25, 0))
check("unknown homes are unknown", nb.home_position(w, "nowhere") is None and nb.home_position(w, None) is None)

# ---- children --------------------------------------------------------------------------------------------------------------
lia = person("lia", 7, "h1", ["drawing", "football"])
mo = person("mo", 8, "h2", ["football", "drawing"])
ned = person("ned", 7, "h2", [])
old = person("old", 15, "h3", ["football"])
farkid = person("farkid", 7, "far", ["football"])
sib = person("sib", 7, "h1", [])
w = town(lia, mo, ned, old, farkid, sib)
tied = nb.seed_neighbour_ties(w, lia)
check("a child gets friends among the children of about their age next door", set(tied) == {"mo", "ned"}, str(tied))
check("not the one eight years older, not the one a mile away, not their own sibling", not ({"old", "farkid", "sib"} & set(tied)))
check("the ties are mutual", rel(lia, mo) and rel(mo, lia) and rel(ned, lia))
check("with real friendship, familiarity and trust, labelled as neighbours", rel(lia, mo)["friendship"] >= 10 and rel(lia, mo)["familiarity"] >= 14
      and rel(lia, mo)["trust"] >= 6 and "neighbour" in rel(lia, mo)["labels"], str(rel(lia, mo)))
check("and a little history, so they read as people who know each other", rel(lia, mo)["interaction_count"] >= 3)
check("shared hobbies make for a closer friend", rel(lia, mo)["friendship"] > rel(lia, ned)["friendship"], f"{rel(lia, mo)['friendship']} vs {rel(lia, ned)['friendship']}")
check("they remember it", any("Mo lives nearby" in m["text"] and "neighbour" in m["tags"] for m in lia["memories"]) and any("Lia lives nearby" in m["text"] for m in mo["memories"]))
check("the relationship state reflects it", rel(lia, mo)["state"] in ("acquaintance", "friend"), rel(lia, mo)["state"])
check("they were flagged", lia["_neighbours_seeded"] == 5000)
again = nb.seed_neighbour_ties(w, lia)
check("running it again adds nothing new", again == [], str(again))

# a limit
kids = [person(f"k{i}", 7, f"h{2 + i % 2}", []) for i in range(8)]
w = town(person("main", 7, "h1", []), *kids)
nb.seed_neighbour_ties(w, w["characters"]["main"])
check("no more than three friends", len(nb._friends(w["characters"]["main"])) == nb.MAX_KID_FRIENDS, str(len(nb._friends(w["characters"]["main"]))))
youngest = person("y", 5, "h1", [])
peers = [person("p4", 4, "h2", []), person("p5", 5, "h2", []), person("p6", 6, "h2", []), person("p8", 8, "h3", []), person("p9", 9, "h3", [])]
w = town(youngest, *peers)
got = nb.seed_neighbour_ties(w, youngest)
check("a five-year-old doesn't befriend the nine-year-old (age gap over three)", "p9" not in got and len(got) == 3, str(got))

# existing history and family are left alone
a, b = person("a", 7, "h1", []), person("b", 7, "h2", [])
w = town(a, b)
rel_ab = {"friendship": 60, "familiarity": 70, "trust": 50, "interaction_count": 40, "labels": ["best friend"], "kinship": None}
a["relationships"]["b"] = dict(rel_ab)
b["relationships"]["a"] = dict(rel_ab)
nb.seed_neighbour_ties(w, a)
check("a pair that already has real history is untouched", a["relationships"]["b"]["friendship"] == 60 and a["relationships"]["b"]["labels"] == ["best friend"])
c1, c2 = person("c1", 8, "h1", []), person("c2", 8, "h2", [])
c1["relationships"]["c2"] = {"kinship": "cousin"}
w = town(c1, c2)
nb.seed_neighbour_ties(w, c1)
check("family is left alone", c1["relationships"]["c2"].get("friendship", 0) in (0, None) and "neighbour" not in c1["relationships"]["c2"].get("labels", []))
d1, d2 = person("d1", 8, "h1", []), person("d2", 8, "h2", [])
d1["relationships"]["d2"] = {"friendship": 80, "familiarity": 5, "trust": 90, "interaction_count": 2}
w = town(d1, d2)
nb.seed_neighbour_ties(w, d1)
check("nothing is ever lowered", d1["relationships"]["d2"]["friendship"] == 80 and d1["relationships"]["d2"]["trust"] == 90)

# ---- grown-ups --------------------------------------------------------------------------------------------------------------------
mum = person("mum", 36, "h1")
dad2 = person("dad2", 40, "h2")
mum3 = person("mum3", 33, "h3")
kid2 = person("kid2", 9, "h2")
farmum = person("farmum", 36, "far")
w = town(mum, dad2, mum3, kid2, farmum)
tied = nb.seed_neighbour_ties(w, mum)
check("grown-ups know the other grown-ups nearby, not the children, not the far away", set(tied) == {"dad2", "mum3"}, str(tied))
check("as acquaintances: they know each other but are not friends", rel(mum, dad2)["familiarity"] >= 6 and rel(mum, dad2)["friendship"] < 10
      and "neighbour" in rel(mum, dad2)["labels"], str(rel(mum, dad2)))
check("nearer neighbours are better known", rel(mum, dad2)["familiarity"] >= rel(mum, mum3)["familiarity"] - 1.5)
crowd = [person(f"x{i}", 40, "h2") for i in range(1)] + [person(f"y{i}", 40, "h3") for i in range(1)]
homes = {f"hh{i}": (i * 3, 0) for i in range(12)}
people = [person(f"adult{i}", 40, f"hh{i}") for i in range(12)]
w = town(*people, homes=homes)
nb.seed_neighbour_ties(w, w["characters"]["adult0"])
check("a grown-up knows at most five", len([o for o in w["characters"]["adult0"]["relationships"]]) == nb.MAX_ADULT_ACQUAINTANCES)

# ---- who is skipped -----------------------------------------------------------------------------------------------------------------------
npc = person("npc", 40, "h1", is_workplace_npc=True)
homeless = person("homeless", 40, None)
dead = person("dead", 40, "h2", alive=False)
real = person("real", 40, "h3")
w = town(npc, homeless, dead, real)
check("no ties for workplace NPCs or people with no household", nb.seed_neighbour_ties(w, npc) == [] and nb.seed_neighbour_ties(w, homeless) == [])
check("nor to the dead", nb.seed_neighbour_ties(w, real) == [])
unknown = person("u", 7, "elsewhere")
w = town(unknown, person("v", 7, "h1", []))
check("nor for a household whose home can't be found", nb.seed_neighbour_ties(w, unknown) == [])

# ---- the job -----------------------------------------------------------------------------------------------------------------------------------
l2, m2 = person("l2", 7, "h1", ["a"]), person("m2", 7, "h2", ["a"])
w = town(l2, m2)
nb.tick_seed_neighbours(w)
check("the job gives a street to whoever has none yet", "m2" in l2["relationships"] and "l2" in m2["relationships"])
friend_before = l2["relationships"]["m2"]["friendship"]
l2["relationships"]["m2"]["friendship"] += 5
nb.tick_seed_neighbours(w)
check("... once", l2["relationships"]["m2"]["friendship"] == friend_before + 5)
newcomer = person("n2", 7, "h2", ["a"])
w["characters"]["n2"] = newcomer
nb.tick_seed_neighbours(w)
check("a newcomer later is tied to the children already there", "l2" in newcomer["relationships"] and "n2" in l2["relationships"])

# ---- the real world ------------------------------------------------------------------------------------------------------------------------------
import db
live = db.load_world("default")                                  # a private snapshot: the live world is not touched
people = [c for c in live["characters"].values() if c.get("household_id") and c.get("alive") is not False and not c.get("is_workplace_npc")]
hh = {c["household_id"] for c in people}
print(f"   live world: {len(people)} people in {len(hh)} households: {[(c['name'], c.get('age')) for c in people]}")
if len(hh) >= 2:
    before = {(c["id"], oid): dict(r) for c in people for oid, r in (c.get("relationships") or {}).items()}
    tied_live = {c["name"]: [live["characters"][i]["name"] for i in nb.seed_neighbour_ties(live, c)] for c in people}
    print(f"   would be newly tied: {tied_live} (people who already know each other are left as they are)")
    check("in the live world nothing is lowered and nobody is tied to their own household", all(
        (live["characters"][cid].get("relationships") or {}).get(oid, {}).get(f, 0) >= (r.get(f, 0) or 0)
        for (cid, oid), r in before.items() if cid in live["characters"] for f in ("familiarity", "friendship", "trust"))
        and all(live["characters"][i]["household_id"] != c["household_id"] for c in people
                for i in [x for x in (c.get("relationships") or {}) if "neighbour" in (c["relationships"][x].get("labels") or [])]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
