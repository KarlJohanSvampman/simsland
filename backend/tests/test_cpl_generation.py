"""
CPL phase 5 (docs/cpl_implementation_plan.md section 10): how turns are generated, and what it costs.

  * mode A (no model call) only for a factual question the character can answer from their own state, with nothing
    emotional about it; the spec's warning case ("are you home? you were supposed to pick up the kids") is B; an
    upset character or a strained relationship is B; a request waiting on them is C;
  * the mode-A answer comes from their state and answers the question's label;
  * the compact turn prompt carries who they are, who they talk to, what is open and the last lines;
  * a conversation the structure fully covers skips the AI reading (C9), and only in "on" mode;
  * the metrics count turns by mode, model calls, and how conversations ended.

Run inside the backend container:   python tests/test_cpl_generation.py
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
from cpl import config, generation as G, metrics, record, shadow, turns
import cpl.conversations  # noqa: F401

config.CPL_MODE = "on"


def world():
    chars = {k: {"id": k, "name": k.title(), "cognition": {}, "building_id": "house_1", "household_id": "h1",
                 "relationships": {}, "activity": None, "body": {"hunger": 20}, "personality_traits": ["warm", "tidy"]}
             for k in ("theo", "ana")}
    chars["ana"]["relationships"]["theo"] = {"trust": 0.8, "labels": ["spouse"]}
    return {"tick": 0, "sim_time": 1000.0, "timers": [], "conversations": {}, "characters": chars,
            "households": {"h1": {"id": "h1", "home_id": "house_1"}}}


def ask(w, lid, text, lines="ACT: question", act="question"):
    legacy = {"id": lid, "participants": ["theo", "ana"], "medium": "in_person", "active": True, "topic": "tonight"}
    w["characters"]["theo"]["_cpl_turn"] = lines
    shadow.on_line(w, legacy, "theo", text, act)
    w["characters"]["theo"].pop("_cpl_turn", None)
    event_bus.flush(w)
    return legacy, turns.context_block(w, w["characters"]["ana"])


w = world()
legacy, blk = ask(w, "L1", "Where are you?")
check("'Where are you?' from her husband, nothing else going on: mode A (no model call)",
      G.choose_mode(w, w["characters"]["ana"], blk) == "A")
d = G.structured_decision(w, w["characters"]["ana"], blk)
check("... answered from her state, answering Q1", d and d["speech"]["utterance"] == "I'm at home."
      and d["speech"]["cpl"].startswith("ANSWERS: Q1 answer") and d["speech"]["target"] == "theo", d)

w = world()
_, blk = ask(w, "L2", "Are you home? You were supposed to pick up the kids!")
check("the spec's warning case -- 'you were supposed to pick up the kids' -- is B, not A",
      G.choose_mode(w, w["characters"]["ana"], blk) == "B")
w = world()
w["characters"]["ana"]["emotion"] = {"primary": "angry"}
_, blk = ask(w, "L3", "What are you doing?")
check("she's angry: B", G.choose_mode(w, w["characters"]["ana"], blk) == "B")
w = world()
w["characters"]["ana"]["relationships"]["theo"]["trust"] = 0.1
_, blk = ask(w, "L4", "Have you eaten?")
check("they don't get on: B", G.choose_mode(w, w["characters"]["ana"], blk) == "B")
w = world()
_, blk = ask(w, "L5", "Could you lend me the car?", "ACT: request", act="request")
check("a request waiting on her: C (the full context matters)", G.choose_mode(w, w["characters"]["ana"], blk) == "C")
w = world()
_, blk = ask(w, "L6", "So what do you think about the election?")
check("an opinion question: B", G.choose_mode(w, w["characters"]["ana"], blk) == "B")

# ── the compact prompt ───────────────────────────────────────────────────────────────────────────────────────────────
w = world()
_, blk = ask(w, "L7", "Have you eaten?")
cp = turns.compact_prompt(w, w["characters"]["ana"], blk)
check("the compact prompt: who she is, who she talks to, what is open, the last line",
      "You are Ana (warm, tidy)." in cp and "Talking with Theo (spouse" in cp and "Q1 Theo asked" in cp
      and 'Theo: "Have you eaten?"' in cp, cp)
check("... and it is short", len(cp) < 800, len(cp))

# ── skipping the AI reading ──────────────────────────────────────────────────────────────────────────────────────────
w = world()
legacy, blk = ask(w, "L8", "Where are you?")
w["characters"]["ana"]["_cpl_turn"] = "ANSWERS: Q1 answer"
shadow.on_line(w, legacy, "ana", "I'm at home.", "answer")
w["characters"]["ana"].pop("_cpl_turn")
check("every line structured, two people, nothing to read between the lines: no AI reading needed",
      record.skippable(w, "L8"))
tags = record.minimal_tags(w, "L8")
check("... the structure stands in for it", tags["skipped"] == "structured" and any("answered" in l for l in tags["structured"]))
legacy, _ = ask(w, "L9", "Did you hear Bo got fired?", "ACT: statement", act="gossip")
check("a conversation with a claim in it is still read", not record.skippable(w, "L9"))
config.CPL_MODE = "shadow"
check("in shadow mode nothing is skipped", not record.skippable(w, "L8"))
config.CPL_MODE = "on"

# ── metrics ──────────────────────────────────────────────────────────────────────────────────────────────────────────
w = world()
metrics.note_turn(w, "A")
metrics.note_turn(w, "B", compact=True)
metrics.note_turn(w, "C")
metrics.note_ended(w, "question_answered")
metrics.note_ended(w, "timeout")
r = metrics.report(w)
check("metrics: turns by mode, model calls, the share without a model, endings",
      r["turns"] == {"A": 1, "B": 1, "C": 1} and r["model_calls"] == 2 and r["compact_turns"] == 1
      and r["share_without_model"] == 0.333 and r["share_timeout_or_abandoned"] == 0.5, r)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
