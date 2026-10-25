"""
What is posted about someone online (systems/online_posts.py): readers weigh it, the subject learns of it by reading.

Run inside the backend container:   python tests/test_online_posts.py
"""

import os
import random
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from systems import online_posts as op
from systems import relationship_ledger as rl
from systems import social_media as sm

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, rel=None, **extra):
    d = {"id": cid, "name": cid.title() + " Smith", "age": 35, "traits": [], "memories": [], "relationships": rel or {},
         "active_intentions": [], "alive": True, "x": 1, "y": 1}
    d.update(extra)
    return d


def town(tick=100000):
    sam = person("sam")
    zed = person("zed")
    lia = person("lia", rel={"sam": {"trust": 90, "friendship": 80, "familiarity": 40}})
    w = {"tick": tick, "characters": {c["id"]: c for c in (sam, zed, lia)}, "definitions": {}}
    return sam, zed, lia, w


def post(sam, w, text="Zed Smith is a fraud", **kw):
    with mock.patch("systems.social_media._project_engagement"), mock.patch("systems.social_media._notify_mentioned_characters"):
        return sm.create_post(sam, w, text, **kw)


random.seed(4)
sam, zed, lia, w = town()

# ---- what makes a post a remark -------------------------------------------------------------------------------------------
p = post(sam, w, "Zed Smith is a fraud", tags=["rumor"])
check("a rumor-tagged post naming someone is a remark about them (meanness, no standing opinion)", p["remark"]["kinds"] == {"zed": "meanness"}, str(p.get("remark")))
sam["opinions"] = {"person:zed": [{"stance": 0.6}]}
p2 = post(sam, w, "Heard Zed Smith got the job", tags=["rumor"])
check("... or a compliment if the author thinks well of them", p2["remark"]["kinds"] == {"zed": "compliment"}, str(p2.get("remark")))
sam["opinions"] = {}
p3 = post(sam, w, "Zed Smith has been lying to everyone", intent={"valence": "deceive"})
check("a declared intent decides the kind", p3["remark"]["kinds"] == {"zed": "slander"})
p4 = post(sam, w, "Had lunch with Zed Smith today")
check("an ordinary mention is not a remark", "remark" not in p4)
p5 = post(sam, w, "Rumor has it something is up", tags=["rumor"])
check("a rumor naming nobody is not one either", "remark" not in p5)
check("the post itself is still created as before", p4 in w["social_posts"] and p4["about_character_ids"] == ["zed"])

# ---- a reader weighs it -----------------------------------------------------------------------------------------------------------
sam, zed, lia, w = town()
p = post(sam, w, "Zed Smith is a fraud", tags=["rumor"])
random.seed(1)
sm.view_post(lia, w, p["id"])
event_bus.flush(w)
check("reading it emits a remark that makes it a rumor about the subject", any(r["subject"] == "zed" and r["source"] == "sam" for r in (w.get("rumors") or {}).values()), str(w.get("rumors")))
check("the reader remembers having read it", any("I read that Sam Smith posted about Zed Smith" in m["text"] for m in lia["memories"]), str([m["text"] for m in lia["memories"]]))
rumor = next(iter(w["rumors"].values()))
check("a trusting reader believes it and becomes a carrier", "lia" in rumor["believers"], str(rumor))
check("nothing is written on (author, subject) yet: the subject has not read it", rl.get_ledger(w, "sam", "zed", create=False) is None)
sm.view_post(lia, w, p["id"])
event_bus.flush(w)
check("reading it again doesn't count twice", len(w["rumors"]) == 1 and len(rumor["believers"]) == 1)
sm.view_post(sam, w, p["id"])
event_bus.flush(w)
check("the author reading their own post changes nothing", len(rumor["believers"]) == 1)

# ---- the subject reads it ---------------------------------------------------------------------------------------------------------
sm.view_post(zed, w, p["id"])
event_bus.flush(w)
led = rl.get_ledger(w, "sam", "zed", create=False)
check("when the subject reads it, it reaches the ledger on the post channel", led is not None and any(e.get("channel") == "post" for e in led["entries"]), str(led and led["entries"]))
check("an intent entry is logged and a perceived one registered", led and led["summary"]["neg_total"] > 0, str(led and led["summary"]))
check("the post notes it was delivered, once", p["remark"]["delivered"] == ["zed"])
check("they remember reading it", any("I read a post where Sam Smith posted about me" in m["text"] for m in zed["memories"]))
n = len(led["entries"])
sm.view_post(zed, w, p["id"])
event_bus.flush(w)
check("not delivered a second time", len(rl.get_ledger(w, "sam", "zed", create=False)["entries"]) == n)

# ---- praise reaches them as a positive entry -----------------------------------------------------------------------------------------
sam, zed, lia, w = town()
sam["opinions"] = {"person:zed": [{"stance": 0.8}]}
p = post(sam, w, "Zed Smith is such a good friend", tags=["rumor"])
sm.view_post(zed, w, p["id"])
event_bus.flush(w)
led = rl.get_ledger(w, "sam", "zed", create=False)
check("a kind post that the subject reads is a positive entry and no grudge", led and led["summary"]["pos_total"] > 0 and not zed.get("grudges"), str(led and led["summary"]))

# ---- browsing ------------------------------------------------------------------------------------------------------------------------------
sam, zed, lia, w = town()
others = [post(sam, w, f"Nice weather number {i}") for i in range(6)]
about = post(sam, w, "Zed Smith is a fraud", tags=["rumor"])
for i, q in enumerate(others + [about]):
    q["tick"] = 100000 - 1000 + i
read = op.browse(lia, w, count=3)
check("browsing reads a few posts", len(read) == 3 and all("lia" in q["views"] for q in read))
read_zed = op.browse(zed, w, count=2)
check("the post about the reader comes first", read_zed[0]["id"] == about["id"], str([q["id"] for q in read_zed]))
event_bus.flush(w)
check("so browsing is how a subject learns of it", rl.get_ledger(w, "sam", "zed", create=False) is not None)
own = post(zed, w, "My own post")
check("one's own posts are not browsed", own["id"] not in [q["id"] for q in op.browse(zed, w, count=20)])
old = post(sam, w, "Ancient post")
old["tick"] = 100000 - op.POST_LIFETIME_TICKS - 10
check("old posts are skipped", old["id"] not in [q["id"] for q in op.browse(lia, w, count=20)])

# finishing a browse activity does it
sam, zed, lia, w = town()
p = post(sam, w, "Zed Smith is a fraud", tags=["rumor"])
w["tick"] += 10
op._on_activity_completed({"character_id": "zed", "activity_type": "computer_social_media"}, w)
event_bus.flush(w)
check("finishing a social-media session reads the feed", "zed" in p["views"] and p["remark"]["delivered"] == ["zed"])
p2 = post(sam, w, "Zed Smith again", tags=["rumor"])
op._on_activity_completed({"character_id": "lia", "activity_type": "computer_cooking"}, w)
check("other activities don't", "lia" not in p2["views"])

# ---- coming across it -----------------------------------------------------------------------------------------------------------------
sam, zed, lia, w = town()
p = post(sam, w, "Zed Smith is a fraud", tags=["rumor"])
with mock.patch("systems.online_posts.random.random", return_value=0.5):
    op.tick_post_discovery(w)
check("usually not found on any one check", not p["remark"]["delivered"])
with mock.patch("systems.online_posts.random.random", return_value=0.0):
    zed["activity"] = {"type": "sleep"}
    op.tick_post_discovery(w)
    check("not while asleep", not p["remark"]["delivered"])
    zed["activity"] = None
    op.tick_post_discovery(w)
check("but eventually they come across it", p["remark"]["delivered"] == ["zed"] and "zed" in p["views"])
p_old = post(sam, w, "Zed Smith is a fraud still", tags=["rumor"])
p_old["tick"] = w["tick"] - op.POST_LIFETIME_TICKS - 5
with mock.patch("systems.online_posts.random.random", return_value=0.0):
    op.tick_post_discovery(w)
check("old posts are no longer found", not p_old["remark"]["delivered"])

# ---- the job that carries rumors also looks for posts -----------------------------------------------------------------------------------
from systems import rumors
sam, zed, lia, w = town()
p = post(sam, w, "Zed Smith is a fraud", tags=["rumor"])
with mock.patch("systems.online_posts.random.random", return_value=0.0):
    rumors.tick_rumors(w)
check("the rumors job runs the discovery check", p["remark"]["delivered"] == ["zed"])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
