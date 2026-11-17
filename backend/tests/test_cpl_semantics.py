"""
CPL phase 3 (docs/cpl_implementation_plan.md C7-C9): what a conversation means, recorded as it happens --

  * a counteroffer opens a proposal back; accepting it accepts the request on its terms; rejecting it rejects it;
  * an accepted (or conditionally accepted) request is a social contract (C7), made once however often delivered;
  * a claim is asserted until the listener takes it: acknowledged is not confirmed; disputed is recorded (C8);
  * the structured record reaches the AI that reads the finished conversation (C9).

Run inside the backend container:   python tests/test_cpl_semantics.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from core import event_bus
from cpl import config, record, shadow, store, turns
import cpl.conversations  # noqa: F401 -- installs the adapters

config.CPL_MODE = "on"
seen = []
for ev in ("cpl.information_shared", "cpl.information_disputed", "cpl.information_acknowledged", "cpl.argument"):
    event_bus.subscribe(ev, lambda data, world=None, _e=ev: seen.append(_e))


def world():
    return {"tick": 0, "sim_time": 1000.0, "timers": [], "conversations": {}, "social_contracts": {},
            "characters": {k: {"id": k, "name": k.title(), "cognition": {}, "relationships": {}}
                           for k in ("theo", "ana", "mia")}}


class Talk:
    def __init__(self, w, lid):
        self.w, self.legacy = w, {"id": lid, "participants": ["theo", "ana"], "medium": "in_person", "active": True}

    def say(self, who, text, lines=None, act="declare"):
        if lines:
            self.w["characters"][who]["_cpl_turn"] = lines
        shadow.on_line(self.w, self.legacy, who, text, act)
        self.w["characters"][who].pop("_cpl_turn", None)
        self.w["sim_time"] += 5
        event_bus.flush(self.w)

    @property
    def conv(self):
        return record.for_legacy(self.w, self.legacy["id"])


# ── a counteroffer, accepted ─────────────────────────────────────────────────────────────────────────────────────────
w = world()
t = Talk(w, "L1")
t.say("theo", "Could I borrow your car tonight?", "ACT: request")
rid = t.conv["open_items"]["requests"][0]
t.say("ana", "Only if you fill it up.", "ANSWERS: R1 counter\nCONDITION: fill the tank")
blk = turns.context_block(w, w["characters"]["theo"])
check("a counteroffer: the request is under negotiation, and Theo is asked about Ana's terms (P1)",
      w["cpl_requests"][rid]["status"] == "negotiating" and any(l.startswith("P1 Ana asked for: fill the tank")
                                                                 and "needs your answer" in l for l in blk["open"]),
      blk["open"])
t.say("theo", "Deal, I'll fill it up.", "ANSWERS: P1 accept")
k = list(w["social_contracts"].values())
check("Theo accepts the counter: the request is accepted on its terms", w["cpl_requests"][rid]["status"] == "accepted")
check("... and it is a social contract: Ana responsible, under the condition (C7)",
      len(k) == 1 and k[0]["terms"][0]["responsible_party"] == "ana" and "fill the tank" in k[0]["terms"][0]["conditions"]
      and w["cpl_requests"][rid]["contract_id"] == k[0]["id"], k)
check("... everything settled: it winds down (mutual agreement on record)", t.conv["state"] == "resolving"
      and t.conv["outcome_hint"] == "mutual_agreement", (t.conv["state"], t.conv.get("outcome_hint")))
event_bus.emit("cpl.commitment_created", {"commitment_id": "commit_" + rid, "request": {"id": rid},
                                          "conversation_id": t.conv["id"]})
event_bus.flush(w)
check("the same commitment delivered again makes no second contract", len(w["social_contracts"]) == 1)

# ── conditional accept; a rejected counter ───────────────────────────────────────────────────────────────────────────
w = world()
t = Talk(w, "L2")
t.say("theo", "Can you pick up the kids at three?", "ACT: request")
t.say("ana", "Yes, if I can leave work early.", "ANSWERS: R1 conditional\nCONDITION: if I can leave work early")
k = list(w["social_contracts"].values())
check("a conditional yes is a contract with that condition", len(k) == 1
      and "if I can leave work early" in k[0]["terms"][0]["conditions"], k)
w = world()
t = Talk(w, "L3")
t.say("theo", "Lend me fifty?", "ACT: request")
rid = t.conv["open_items"]["requests"][0]
t.say("ana", "Twenty, maybe.", "ANSWERS: R1 counter\nCONDITION: twenty, not fifty")
t.say("theo", "Forget it then.", "ANSWERS: P1 reject")
check("a rejected counter rejects the request, and makes no contract",
      w["cpl_requests"][rid]["status"] == "rejected" and not w["social_contracts"])

# ── claims ───────────────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
t = Talk(w, "L4")
seen.clear()
t.say("theo", "Did you hear Mia got fired?", None, act="gossip")
cl = list(t.conv["claims"].values())[0]
check("gossip is a claim, asserted -- heard is not believed (C8)", cl["status"] == "asserted"
      and "cpl.information_shared" in seen)
t.say("ana", "I doubt that, she just got promoted.", "STANCE: skeptical")
check("Ana is skeptical: the claim is disputed, and that is announced", cl["status"] == "disputed"
      and "cpl.information_disputed" in seen, cl)
w = world()
t = Talk(w, "L5")
t.say("theo", "The bridge is closed, there was an accident!", None, act="urgent_report")
t.say("ana", "Oh no, thanks for telling me.", "STANCE: believing")
cl = list(t.conv["claims"].values())[0]
check("believed: acknowledged (which is not the same as confirmed)", cl["status"] == "acknowledged")
t.say("theo", "Raising the rent is fair -- costs went up.", "ACT: argument\nSTANCE: firm")
check("an argument is announced for the opinions it bears on", "cpl.argument" in seen)

# ── the record reaches the conversation reader ───────────────────────────────────────────────────────────────────────
w = world()
t = Talk(w, "L6")
t.say("theo", "Could I borrow your car tonight?", "ACT: request")
t.say("ana", "Fine, take it.", "ANSWERS: R1 accept")
t.say("ana", "By the way, the bridge is closed.", None, act="urgent_report")
lines = record.lines(w, t.conv)
check("the structured record says who asked what, the answer, the agreement and the claim",
      any("Theo asked for: \"Could I borrow your car tonight?\" -> accepted" in l and "agreement" in l for l in lines)
      and any("Ana claimed" in l and "asserted" in l for l in lines), lines)
from llm.conversation_tags import _ctx_block
blockt = _ctx_block({"structured": lines})
check("... and is put to the conversation reader as given", "recorded as it happened" in blockt and "accepted" in blockt)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
