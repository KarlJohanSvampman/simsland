"""
Intentions and expectations as one priority list, with what is only for when there is time kept apart, and no randomness while
anything is open (systems/todo.py, systems/unresolved.py, brain/context_builder.py::_sec_todo, brain/agent_loop.py, systems/offgrid.py).

Run inside the backend container:   python tests/test_todo.py
"""

import os
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from brain.context_builder import _sec_todo
from systems import todo
from systems.unresolved import has_unresolved

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def intent(t, category, priority, **kw):
    d = {"type": t, "category": category, "priority": priority, "strength": 1}
    d.update(kw)
    return d


def char(*items, **extra):
    c = {"id": "a", "name": "Anna", "age": 36, "active_intentions": list(items), "expectations": {}}
    c.update(extra)
    return c


# ---- tiers -------------------------------------------------------------------------------------------------------------------------
check("survival, health and schedule matters are pressing", all(todo.tier(intent("x", k, 10)) == "pressing" for k in ("survival", "health", "schedule")))
check("an expectation (it is a schedule matter) is pressing", todo.tier(intent("expectation:make_dinner", "schedule", 50)) == "pressing")
check("leisure, identity and impulse are for when there is time, however high", all(todo.tier(intent("x", k, 95)) == "when_free" for k in ("leisure", "identity", "impulse")))
check("a social, household or chore matter is pressing when it is important", todo.tier(intent("socialize", "social", 100)) == "pressing" and todo.tier(intent("clean", "chores", 75)) == "pressing")
check("... or has gone unanswered through a check-in", todo.tier(intent("gossip", "social", 20, stage=1)) == "pressing")
check("... and otherwise waits", todo.tier(intent("gossip", "social", 20)) == "when_free" and todo.tier(intent("tidy", "chores", 40)) == "when_free")
check("worry relief is a need", todo.tier(intent("relieve_worry", "identity", 76)) == "pressing")

c = char(intent("exercise", "leisure", 72), intent("feed_child_k", "health", 85, child_id="k"), intent("expectation:go_to_work", "schedule", 60),
        intent("compliment_looks", "impulse", 78), intent("take_nap", "health", 66), intent("creative_outlet", "leisure", 67))
lst = todo.todo_list(c)
check("the pressing ones come first, most pressing first", [i["type"] for i in lst["pressing"]] == ["feed_child_k", "take_nap", "expectation:go_to_work"], str([i["type"] for i in lst["pressing"]]))
check("the rest is kept apart, in its own order", [i["type"] for i in lst["when_free"]] == ["exercise", "creative_outlet", "compliment_looks"], str([i["type"] for i in lst["when_free"]]))
check("a decayed intention is not on the list", not todo.todo_list(char(intent("x", "health", 80, strength=0)))["pressing"])

# ---- the prompt -------------------------------------------------------------------------------------------------------------------------------
lines = _sec_todo(c, {})
check("the prompt gives a numbered list of what has to be seen to", lines[0].startswith("What you have to see to, most pressing first: 1.") and "2." in lines[0] and "3." in lines[0], str(lines))
check("then what is for when there is time, not before", lines[1].startswith("When you have the time (not before the above):"), str(lines))
quiet = _sec_todo(char(intent("exercise", "leisure", 72), intent("seek_solitude", "leisure", 52, reason="you want some time alone")), {})
check("with nothing pressing, it says so", quiet[0].startswith("Nothing pressing right now. You have time for: ") and "time alone" in quiet[0], str(quiet))
check("a character with nothing at all gets no section", _sec_todo(char(), {}) is None)
many = _sec_todo(char(*[intent(f"s{n}", "health", 60 + n) for n in range(10)]), {})
check("the list shown is short (four at most)", "4." in many[0] and "5." not in many[0], many[0])

# ---- nothing is left to chance while anything is open ----------------------------------------------------------------------------------------------------
check("an intention open: unresolved", has_unresolved(char(intent("exercise", "leisure", 72))))
check("an expectation pending: unresolved", has_unresolved(char(expectations={"go_to_work": {"status": "pending"}})))
check("a satisfied expectation and no intentions: nothing open", not has_unresolved(char(expectations={"go_to_work": {"status": "satisfied"}})))
check("a decayed intention does not count", not has_unresolved(char(intent("x", "leisure", 50, strength=0))))

from systems import curiosity, idle_quirks
started = []
with mock.patch.object(curiosity, "_find_notable_target", return_value={"id": "t", "x": 1, "y": 1}), mock.patch.object(curiosity, "_start_investigation", lambda c, w, t: started.append(t)), \
        mock.patch.object(curiosity.random, "random", return_value=0.0):
    busy = char(intent("exercise", "leisure", 72), curiosity=100, alive=True)
    curiosity.tick_curiosity(busy, {"tick": 10 ** 6})
    check("a character with something open does not go off to investigate by chance", not started)
    free = char(curiosity=100, alive=True)
    curiosity.tick_curiosity(free, {"tick": 10 ** 6})
    check("one with nothing open still may", len(started) == 1)

# the agent loop: the quirks are only for the idle with nothing open; and for when there is time waits for the pressing
import inspect
src = inspect.getsource(brain.agent_loop.update_agent)
check("the idle quirks are gated on there being nothing open", "not has_unresolved(c, world) and maybe_delay_or_quirk(c, world)" in src)
check("what is for when there is time does not run by itself while something pressing is open", "pressing_open and _todo_tier(intention) == \"when_free\"" in src)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
