"""
Claims about people and how they travel (social/rumours.py; systems/rumors.py hands posts to it): the listener's own
judgement of how credible it is, corroboration, distortion kept apart from the original, and telling the subject.

Run:   python tests/test_rumors.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from core import event_bus
from systems import rumors as rm
from systems import relationship_ledger as rl
from social import rumours as R, standing

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, traits=(), age=35, rel=None):
    return {"id": cid, "name": cid.title(), "age": age, "traits": list(traits), "memories": [], "relationships": rel or {},
            "active_intentions": [], "alive": True, "x": 1, "y": 1}


def town(**lia_rel):
    sam, zed = person("sam"), person("zed")
    lia = person("lia", rel={"sam": {"trust": 40, "friendship": 30}, **lia_rel})
    ann = person("ann")
    return sam, lia, zed, ann, {"tick": 100000, "characters": {c["id"]: c for c in (sam, lia, zed, ann)}, "definitions": {}}


check("remark kinds are as before", rm.remark_kind("lie", None) == "slander" and rm.remark_kind("gossip", None) == "meanness"
      and rm.remark_kind("speak", {"valence": "help"}) == "compliment" and rm.remark_kind("ask", None) is None)

# ---- credibility: trust, existing views, evidence, susceptibility -----------------------------------------------------
sam, lia, zed, ann, w = town()
r = R.create(w, "zed", "never pays his share", originator_id="sam", polarity=-1)
base = R.credibility(w, lia, "sam", "zed", -1, r)
check("a trusted friend's word counts", base > 0.5, str(base))
lia["relationships"]["zed"] = {"standing": {"score": 60, "confidence": 0.5, "history": []}}
check("thinking well of the subject resists ill said of them", R.credibility(w, lia, "sam", "zed", -1, r) < base - 0.15)
check("... and doesn't resist praise", R.credibility(w, lia, "sam", "zed", 1, r) >= base)
lia["relationships"].pop("zed")
r["information_status"] = "false"
check("a claim known to be false is hard to believe", R.credibility(w, lia, "sam", "zed", -1, r) < base - 0.2)
r["information_status"] = "unverified"
check("a stranger's word counts for little", R.credibility(w, ann, "sam", "zed", -1, r) < 0.4)
kid = person("kid", age=7)
w["characters"]["kid"] = kid
check("a child believes more easily", R.credibility(w, kid, "sam", "zed", -1, r) > R.credibility(w, ann, "sam", "zed", -1, r))

# ---- transmission ----------------------------------------------------------------------------------------------------
sam, lia, zed, ann, w = town()
t = R.transmit(w, "sam", "lia", "zed", "never pays his share", tone=-2)
rumour = R.get(w, t["rumour_id"])
check("passing it on makes a rumour about the subject, with the originator", rumour["subject_id"] == "zed"
      and rumour["originator_id"] == "sam" and rumour["information_status"] == "unverified")
check("... a transmission with the listener's own reading", t["receiver_id"] == "lia" and 0 < t["confidence_after_transmission"] <= 1
      and t["interpretation"] in ("believes it", "half believes it", "doubts it"))
check("... which lowers how she regards him, by as much as she believes it", standing.score(lia, "zed") < 0,
      str(standing.score(lia, "zed")))
check("... and she remembers who told her", any("Sam told me that Zed" in m["text"] for m in lia["memories"]))
first_conf = lia["known_rumours"][rumour["id"]]["confidence"]
lia["relationships"]["ann"] = {"trust": 50}
t2 = R.transmit(w, "ann", "lia", "zed", "he never pays", tone=-2, same_as=rumour["id"])
check("hearing it from a second trusted person: more sure", lia["known_rumours"][rumour["id"]]["confidence"] > first_conf)
check("... the words as told are kept beside the original claim", t2["claim_as_told"] == "he never pays"
      and rumour["claim"] == "never pays his share")
check("she knows it", rumour in R.known_by(w, "lia"))

# ---- telling the subject -----------------------------------------------------------------------------------------------
R.tell_subject(w, rumour, "lia")
event_bus.flush(w)
led = rl.get_ledger(w, "sam", "zed", create=False)
check("told to Zed's face, it reaches the (originator, subject) ledger", led is not None and led["entries"], str(led))
check("... and Zed thinks less of Sam", standing.score(zed, "sam") < 0)

# ---- posts go the same way ----------------------------------------------------------------------------------------------
sam, lia, zed, ann, w = town()
rm._on_remark({"speaker_id": "sam", "listener_id": "lia", "subject_id": "zed", "kind": "meanness",
               "text": "Zed is a fraud", "via": "post", "ref": {"type": "post", "id": "p1"}}, w)
rm._on_remark({"speaker_id": "sam", "listener_id": "lia", "subject_id": "zed", "kind": "meanness",
               "text": "Zed is a fraud", "via": "post", "ref": {"type": "post", "id": "p1"}}, w)
r = next(iter(w["rumors"].values()))
check("a post read is a transmission; read twice it counts once", len(r["transmissions"]) == 1)
check("... remembered as read", any("I read that Sam posted about Zed" in m["text"] for m in lia["memories"]))

# ---- praise makes a stranger a name you know ------------------------------------------------------------------------------
l, s = person("l"), person("s")
rm._shift_listener(l, "s", +1, 6)
check("a believed compliment about a stranger gives a little familiarity", l["relationships"]["s"]["familiarity"] == rm.HEARD_OF_FAMILIARITY)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
