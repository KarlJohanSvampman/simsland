"""
Social discourse, standing & confrontation (social/): standing vs frustration vs initiative, issues with positions,
confrontations inside conversations (escalation, sides, outcomes), agreements, and converting an older save.

Run:   python tests/test_social.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
os.environ["BG_LLM_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
import core.event_handlers  # noqa: F401
import social.tick  # noqa: F401
from core import event_bus
from social import standing, frustration, initiative, issues as I, confrontations as X, contracts as K, discourse, migrate
from brain.conversations import create_conversation, add_message
from systems import conversation_archive as ca
from systems.grievances import add_grievance
from systems.room_assignment import refresh_character_room


def fresh():
    w = make_world()
    w["tick"] = 200000
    for cid in ("kathleen", "robert", "joseph", "susan"):
        w["characters"][cid].update(relationships={}, memories=[], grievances=[], conversation_log=[], activity=None,
                                    traits=[], off_grid=False)
    k, r, j = (w["characters"][x] for x in ("kathleen", "robert", "joseph"))
    for c, x in ((k, 58), (r, 59), (j, 60)):
        c.update(x=x, y=4, building_id="starter_house_2")
        refresh_character_room(c, w)
    return w, k, r, j


# ---- standing: directional, resistant, repeated behaviour counts more ---------------------------------------------
w, k, r, j = fresh()
standing.change(k, "robert", w, "insult")
check("standing is directional: Kathleen's view of Robert moved, not his of her",
      standing.score(k, "robert") < 0 and standing.score(r, "kathleen") == 0)
one = standing.score(k, "robert")
standing.change(k, "robert", w, "insult")
check("the same again within the week counts for more", standing.score(k, "robert") - one < one, f"{one} {standing.score(k, 'robert')}")
k["relationships"]["joseph"] = {"standing": {"score": 40, "confidence": 1.0, "history": []}}
d_small = standing.change(k, "joseph", w, "incompetence")
check("an established view barely moves for a small thing", -3 < d_small < 0, str(d_small))
check("... but a big one still lands", standing.change(k, "joseph", w, "physical_aggression") < -15)

# ---- frustration is not standing; an apology without change makes it worse next time ---------------------------------
w, k, r, j = fresh()
k["relationships"]["robert"] = {"standing": {"score": 70, "confidence": 0.8, "history": []}}
frustration.raise_(k, "robert", w, 30, issue_id="dishes")
check("she can think highly of him and be fed up with him",
      standing.score(k, "robert") == 70 and frustration.value(k, "robert", w, "dishes")["score"] > 20)
check("issue frustration feeds the general level at half", 0 < frustration.value(k, "robert", w)["score"]
      < frustration.value(k, "robert", w, "dishes")["score"])
frustration.calm(k, "robert", w, 20, issue_id="dishes", kind="apology")
before = frustration.value(k, "robert", w, "dishes")["score"]
frustration.raise_(k, "robert", w, 10, issue_id="dishes", kind="repeat")
check("sorry -- and then the same again: it lands harder", frustration.value(k, "robert", w, "dishes")["score"] - before > 10,
      f"{before} -> {frustration.value(k, 'robert', w, 'dishes')['score']}")
i0 = frustration.value(k, "robert", w)["intensity"]
w["tick"] += 2 * 86400
check("how worked up she is fades by itself", abs(frustration.value(k, "robert", w)["intensity"] - max(0, i0 - 30)) < 0.5, str(i0))

# ---- initiative: brushed off again and again, she stops trying -------------------------------------------------------
w, k, r, j = fresh()
w0 = initiative.get(k, "robert")["willingness"]
for _ in range(4):
    initiative.answered(k, "robert", w, "rejected")
check("repeated rejection wears willingness down and avoidance up",
      initiative.get(k, "robert")["willingness"] < w0 - 25 and initiative.get(k, "robert")["avoidance"] >= 20)
check("... and she notices the pattern", initiative.rebuffs(k, "robert") >= 3)

# ---- a grievance is evidence on a persistent issue -----------------------------------------------------------------
w, k, r, j = fresh()
add_grievance(k, "robert", "left_mess", w)
add_grievance(k, "robert", "left_mess", w)
iss = I.between(w, "kathleen", "robert")
check("grievances about the same thing are one issue, with evidence", len(iss) == 1 and len(iss[0]["evidence"]) == 2
      and iss[0]["category"] == "household_responsibility", str([(i["subject"], len(i["evidence"])) for i in iss]))
check("... her position is on it, and she's frustrated about it",
      I.position(iss[0], "kathleen")["stance"] == "opposed" and frustration.value(k, "robert", w, iss[0]["id"])["score"] > 0)
check("... and it's in her issue log", any(x["id"] == iss[0]["id"] for x in k["issue_log"]))

# ---- a line that confronts starts a confrontation inside the conversation ---------------------------------------------
conv = create_conversation(w, ["kathleen", "robert"], topic="general")


def say(who, text, social, to=None):
    w["tick"] += 3
    add_message(w, conv, who["id"], text, "declare", "general", w["tick"])
    discourse.on_line({"conversation_id": conv["id"], "speaker_id": who["id"], "target_id": (to or {}).get("id"),
                       "utterance": text, "social": social, "listeners": ["joseph"]}, w)


say(k, "You left the kitchen a mess again.", {"intent": "criticise", "issue": "the mess left lying around",
                                               "position": "He never cleans up after himself", "escalation": "hold"}, r)
conf = X.get(w, conv.get("related_confrontation_id"))
check("criticism starts a confrontation, about the existing issue", conf and conf["issue_id"] == iss[0]["id"]
      and conf["confrontation_type"] == "criticism" and conf["initiator_id"] == "kathleen")
check("... her position is recorded, and Robert has now heard it", I.position(I.get(w, conf["issue_id"]), "kathleen")["position"]
      == "He never cleans up after himself" and "robert" in I.position(I.get(w, conf["issue_id"]), "kathleen")["said_to"])
say(r, "I did the dishes yesterday!", {"intent": "defend", "position": "I do my share", "escalation": "escalate"}, k)
say(k, "Once!", {"intent": "criticise", "escalation": "escalate"}, r)
say(r, "Get off my back.", {"intent": "provoke", "escalation": "escalate"}, k)
check("escalation is weighed: a few pushes take it up a stage or two, not all the way",
      1 <= conf["stage_idx"] <= 2, conf["stage"])
for _ in range(2):
    say(k, "No, you listen.", {"intent": "criticise", "escalation": "escalate"}, r)
    say(r, "Whatever.", {"intent": "provoke", "escalation": "hold"}, k)
check("it doesn't turn hostile without one side pushing three times in a row", conf["stage_idx"] <= 2, conf["stage"])
for _ in range(4):
    say(k, "You always do this!", {"intent": "criticise", "escalation": "escalate"}, r)
check("... three in a row from her and it does", conf["stage_idx"] == 3, conf["stage"])
say(j, "Hey, both of you, calm down.", {"intent": "mediate", "side": "mediator", "escalation": "de-escalate"}, k)
check("a third person joins as mediator", conf["participants"]["joseph"]["role"] == "mediator")
X.on_hostile_act(w, "robert", "kathleen", "shove")
check("words can't make it physical; a shove does", conf["stage"] == "physical_intimidation" and conf["aggressor"] == "robert")

# ---- the AI's reading of the conversation ends it; aftermath --------------------------------------------------------
event_bus.flush(w)
from systems.conversation_outcome import end
end(w, conv, "left")
entry = w["conversation_archive"][conv["id"]]
s_before = standing.score(k, "robert")
ca.apply_tags(w, entry, {
    "subject": "the kitchen mess", "opening": "criticism", "tags": ["chores"], "interaction_tags": ["criticism"],
    "tone": "hostile", "relates_to": None,
    "issues": [{"same_as": iss[0]["id"], "subject": "the mess", "category": "household_responsibility",
                "raised_by": "Kathleen", "between": ["Kathleen", "Robert"],
                "positions": {"Robert": {"position": "I do my share already", "stance": "opposed", "confidence": 0.8}},
                "status": "open"}],
    "confrontation": {"type": "criticism", "initiator": "Kathleen", "target": "Robert", "issue": "the mess",
                      "problem_statement": "he leaves the kitchen a mess", "desired_outcome": "that he cleans up",
                      "outcome": "relationship_deterioration", "ended_by": "Robert", "summary": "he shoved past her",
                      "sides": {"Joseph": "mediator"}},
    "agreement": None, "violations": [], "initiative_response": None, "standing_events": [],
    "about_others": [], "told_about_themselves": []})
event_bus.flush(w)
check("a shove means it ended as a physical fight", conf["status"] == "resolved" and conf["resolution"]["outcome"] == "physical_fight",
      str(conf.get("resolution")))
check("... Robert's own position is on the issue now", I.position(I.get(w, conf["issue_id"]), "robert")["position"] == "I do my share already")
check("... the issue stays open (nothing was settled)", I.get(w, conf["issue_id"])["status"] in ("open", "reopened"))
check("... her view of him dropped", standing.score(k, "robert") < s_before)
check("... and her try at raising it counts as a hostile response", initiative.get(k, "robert")["recent_responses"][-1]["outcome"] == "hostile")
check("... it's on the record as a fight, filed under the issue", w.get("fight_log") and
      w["fight_log"][-1]["id"] in I.get(w, conf["issue_id"])["fight_ids"])
check("the archived conversation carries the subject, tags and its confrontation",
      entry["subject"] == "the kitchen mess" and entry["confrontation_id"] == conf["id"] and conf["issue_id"] in entry["issue_ids"])

# ---- sides: anger spills onto whoever took the other side -------------------------------------------------------------
w, k, r, j = fresh()
conv = create_conversation(w, ["kathleen", "robert", "joseph"], topic="general")
say(k, "Robert promised to fix the car.", {"intent": "remind_obligation", "issue": "fixing the car", "escalation": "hold"}, r)
c2 = X.get(w, conv["related_confrontation_id"])
say(j, "Leave him alone, he's been busy.", {"intent": "defend", "side": "target", "escalation": "escalate"}, k)
check("a third person joining on Robert's side is a defender on the target's side",
      c2["participants"]["joseph"]["role"] == "defender" and c2["participants"]["joseph"]["side"] == "target")
sj = standing.score(k, "joseph")
X.end(w, c2, "unresolved")
check("Kathleen thinks less of Joseph for taking his side", standing.score(k, "joseph") < sj)
check("... and is frustrated with him over it", frustration.value(k, "joseph", w, c2["issue_id"])["score"] > 0)
check("Robert thinks better of Joseph for it", standing.score(r, "joseph") > 0)

# ---- an agreement, and a disputed violation --------------------------------------------------------------------------
w, k, r, j = fresh()
conv = create_conversation(w, ["kathleen", "robert"], topic="general")
say(k, "Can we split the chores?", {"intent": "negotiate", "issue": "the chores", "escalation": "hold"}, r)
c3 = X.get(w, conv["related_confrontation_id"])
end(w, conv, "resolved")
entry = w["conversation_archive"][conv["id"]]
ca.apply_tags(w, entry, {"subject": "splitting chores", "opening": "request", "tags": [], "interaction_tags": ["negotiation"],
                         "tone": "friendly", "relates_to": None, "issues": [],
                         "confrontation": {"type": "negotiation", "initiator": "Kathleen", "target": "Robert",
                                           "outcome": "contract_established", "summary": "they split the chores"},
                         "agreement": {"title": "chores", "renegotiates": None,
                                       "terms": [{"responsible": "Robert", "obligation": "do the dishes", "frequency": "daily"},
                                                 {"responsible": "Kathleen", "obligation": "do the laundry", "frequency": "weekly"}]},
                         "violations": [], "initiative_response": None, "standing_events": [], "about_others": [],
                         "told_about_themselves": []})
ks = K.between(w, ["kathleen", "robert"])
check("an agreement becomes an active contract with terms per person", len(ks) == 1 and ks[0]["state"] == "active"
      and {t["responsible_party"] for t in ks[0]["terms"]} == {"kathleen", "robert"})
check("... the negotiation ended well and the issue is resolved", c3["resolution"]["outcome"] == "contract_established"
      and I.get(w, c3["issue_id"])["status"] == "resolved")
check("... both of them are told what was agreed", any("agreed to do the dishes" in l for l in K.context_lines(w, k, "robert")))
K.violation(w, ks[0], "robert", "didn't do the dishes", observed_by=["kathleen"], disputed=True)
event_bus.flush(w)
check("a disputed violation is on the record as disputed", ks[0]["violation_records"][-1]["disputed"] and ks[0]["state"] == "disputed")
g = [x for x in k["grievances"] if x["event_type"] == "contract_violated"]
check("... and weighs half", g and g[-1]["details"].get("disputed") is True)
K.renegotiate(w, ks[0]["id"], [{"responsible_party": "robert", "obligation": "do the dishes on weekdays"}], by="robert")
check("renegotiation keeps the previous version", len(ks[0]["revision_history"]) == 1 and ks[0]["state"] == "active"
      and ks[0]["terms"][0]["obligation"] == "do the dishes on weekdays")
K.expect(w, k, "joseph", "return the ladder")
check("an expectation nobody agreed to is told as such", any("never actually agreed" in l for l in K.context_lines(w, k, "joseph")))

# ---- the confront action: opened, then it's theirs to say -------------------------------------------------------------
w, k, r, j = fresh()
event_bus.emit("confront_requested", {"initiator_id": "kathleen", "target_id": "robert", "type": "behavioural_request",
                                      "problem": "the music at night"})
event_bus.flush(w)
c4 = X.active_between(w, "kathleen", "robert")
check("choosing to confront opens one, of the chosen kind, about the chosen thing", c4 and c4["confrontation_type"] ==
      "behavioural_request" and "music" in c4["problem_statement"])
w["tick"] += X.NEVER_SPOKEN_TICKS + 1
X.tick(w)
check("never actually said: it ends unresolved", c4["status"] == "resolved" and c4["resolution"]["outcome"] == "unresolved")

# ---- converting an older save -------------------------------------------------------------------------------------------
w, k, r, j = fresh()
w.pop("_social_version", None)
w["arguments"] = {"arg_1": {"id": "arg_1", "parties": ["kathleen", "robert"], "type": "lying_accusation",
                            "subject": "where he was", "initiator": "kathleen", "opened_tick": 100, "status": "open",
                            "conversation_ids": ["cX"], "fight_ids": [], "events": []}}
k["argument_log"] = [dict(w["arguments"]["arg_1"])]
k["relationships"]["robert"] = {"agitation": {"value": 50, "tick": w["tick"]}, "friendship": 20}
w["conversation_archive"] = {"cX": {"id": "cX", "participants": ["kathleen", "robert"], "argument_id": "arg_1"}}
w["rumors"] = {"rumor_1": {"id": "rumor_1", "source": "joseph", "subject": "robert", "kind": "meanness", "polarity": -1,
                           "text": "he gambles", "tick": 100, "believers": ["kathleen"], "told_to_subject": False}}
migrate.migrate(w)
iss = I.between(w, "kathleen", "robert")
check("an old argument becomes an issue (lying -> dishonesty) with its conversations", len(iss) == 1 and
      iss[0]["category"] == "dishonesty" and "cX" in iss[0]["conversation_ids"] and "arguments" not in w)
check("... the archive entry points at the issue", iss[0]["id"] in w["conversation_archive"]["cX"]["issue_ids"])
check("old agitation becomes how worked up she is", frustration.value(k, "robert", w)["intensity"] == 50)
check("standing is stored, seeded from the old values", k["relationships"]["robert"]["standing"]["score"] == 20)
check("old rumours get the new shape", w["rumors"]["rumor_1"]["subject_id"] == "robert"
      and "rumor_1" in k["known_rumours"])
check("only once", migrate.migrate(w) is False)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
