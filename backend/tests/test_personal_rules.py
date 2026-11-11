"""
Personal rules from the director's notes (systems/personal_rules.py, llm/personal_rules.py, api/personal_rules.py):
notes pile up -> the model proposes rules in the character's voice -> the director approves / rejects / edits ->
approved rules are in the character's prompt; a rejected one isn't proposed again; the director can write one.

Run inside the backend container:   python tests/test_personal_rules.py
"""
import contextlib
import os
import sys
import time

os.environ["COGNITION_MODE"] = "local"
os.environ["BG_LLM_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from llm.personal_rules import parse, build_prompt, SYSTEM

got = parse("RULE: I keep it casual with family | FROM: 1, 3\nrule: I don't say 'shall' | FROM: 2\nRULE: NONE\nRULE: x | FROM: 9", 3)
check("parse: rules with the notes they came from (out-of-range note numbers dropped)",
      got[0] == {"text": "I keep it casual with family", "from": [0, 2]} and got[1]["from"] == [1] and got[2] == {"text": "x", "from": []}, str(got))
check("parse: NONE -> nothing", parse("NONE", 2) == [])
p = build_prompt("Alex", 34, ["lazy", "witty"], ["says 'mate'"], ["I swear when I'm angry"], ["I am always polite"],
                 [{"utterance": "Shall we dine?", "verdict": "dislike", "comment": "too posh for him", "suggestion": "Food?"}])
check("the prompt has the person, their rules, the turned-down ones and the notes",
      "Traits: lazy, witty" in p and "I swear when I'm angry" in p and "turned down" in p and 'would fit better: "Food?"' in p and "too posh" in p)
check("... and asks for first-person rules, at most 3", "first person" in SYSTEM and "At most 3" in SYSTEM)

import systems.personal_rules as pr
import llm.personal_rules as lpr
from systems.dialogue_feedback import give
from systems import bg_llm

c = {"id": "c1", "name": "Alex", "age": 34, "traits": ["witty"]}
w = {"tick": 1000, "characters": {"c1": c}}
give(c, w, "cv", 10, "Shall we dine?", verdict="dislike", comment="too posh for him")
pr.note_given(c)
pr.service(c, w)
check("one note: not enough to propose on its own", not c.get("_rules_ask") and c.get("_rules_due") == "notes")

calls = []
lpr.propose = lambda prompt, n, cid: calls.append(prompt) or [{"text": "I talk plainly, never posh", "from": [0, 1]},
                                                              {"text": "I always say please", "from": [2]}]
give(c, w, "cv", 20, "Indeed, most delightful.", comment="he'd never say that")
give(c, w, "cv", 30, "Good evening, madam.", suggestion="Hiya!")
pr.note_given(c)
pr.service(c, w)                                   # submits
for _ in range(50):
    if not bg_llm.is_pending(pr._key(c)):
        break
    time.sleep(0.05)
w["tick"] += 5
pr.service(c, w)                                   # collects
prop = pr.rules(c, "proposed")
check("three notes: the model's rules come back as PROPOSED (not in effect yet)", [r["text"] for r in prop] == ["I talk plainly, never posh", "I always say please"]
      and pr.prompt_lines(c) == [], str(c.get("personal_rules")))
check("... each with the notes it came from; the notes are now used", len(prop[0]["from_notes"]) == 2
      and all(n["used"] for n in c["dialogue_feedback"]), str(prop[0]))

pr.decide(c, w, prop[0]["id"], "approve")
pr.decide(c, w, prop[1]["id"], "reject")
check("approved -> in the prompt; rejected -> not", pr.prompt_lines(c) == ["Your own rules for yourself (keep to them): I talk plainly, never posh."], str(pr.prompt_lines(c)))
pr.decide(c, w, prop[0]["id"], "edit", text="I talk plainly -- never posh, never formal")
check("edit changes the wording", "never formal" in pr.prompt_lines(c)[0])

give(c, w, "cv", 40, "Pardon me.", verdict="dislike")
check("asking now works with fewer notes than usual", pr.ask_now(c) and c["_rules_due"] == "asked")
pr.service(c, w)
for _ in range(50):
    if not bg_llm.is_pending(pr._key(c)):
        break
    time.sleep(0.05)
w["tick"] += 5
pr.service(c, w)
check("the next prompt lists the rejected rule so it isn't proposed again", "I always say please" in calls[-1].split("turned down")[1])
check("... and a rule it already has isn't added twice", sum(1 for r in c["personal_rules"] if r["text"].lower().startswith("i always say please")) == 1)

import api.personal_rules as ap
ap.load_world = lambda sim_id="default": w
ap.world_lock = contextlib.nullcontext
ap._save = lambda sim_id, world, cid: None
v = ap.add_rule("c1", ap.TextIn(text="I never talk about money with friends"))
check("the director writes a rule: approved straight away", any(r["text"].startswith("I never talk about money") for r in v["approved"]))
v = ap.decide_rule("c1", v["approved"][0]["id"], ap.DecideIn(action="retire"))
check("retire takes it out of the prompt", v["retired"] and "posh" not in " ".join(pr.prompt_lines(c)))
v = ap.get_rules("c1")
check("GET: rules by status, with the notes behind them", "proposed" in v and v["retired"][0]["notes"] and v["retired"][0]["notes"][0]["utterance"] == "Shall we dine?", str(v["retired"][:1])[:300])

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
