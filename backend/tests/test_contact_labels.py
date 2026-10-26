"""
Contacts whose relationship carries labels (neighbour, introduced, ...) or a `last_contact` of None must not break the
action menu or target resolution (brain/context_builder.py::build_available_actions, brain/action_resolver.py).

Run inside the backend container:   python tests/test_contact_labels.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from brain import action_resolver as ar
from brain.context_builder import build_available_actions
from tests import determinism

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


check("a list of labels is normalised like a phrase", ar._normalize(["neighbour", "introduced"]) == "neighbour introduced")
check("the score of a description against a list of labels works", ar._score("my neighbour", [["neighbour", "friend"]]) > 0.5)

w = determinism.fixture("2026-11-04T08:00:00")
people = [c for c in w["characters"].values() if not c.get("is_workplace_npc") and not c.get("is_service_worker")]
me, a, b = people[0], people[1], people[2]
me.setdefault("relationships", {})
for other, last in ((a, None), (b, 5.0)):
    rel = me["relationships"].setdefault(other["id"], {})
    rel.update({"familiarity": 30, "friendship": 20, "labels": ["neighbour", "introduced"], "last_contact": last})

try:
    actions = build_available_actions(me, w)
    ok = True
except Exception as exc:                                   # noqa: BLE001
    actions, ok = None, False
    print("   ", repr(exc))
check("building the action menu with labelled contacts and a None last_contact does not raise", ok)
contacts = (actions or {}).get("known_contacts", [])
check("the contacts are listed, labels joined into a string", any(c["relationship"] == "neighbour, introduced" for c in contacts), str(contacts[:3]))
check("those never contacted sort last", contacts and contacts[-1]["id"] != b["id"] or len(contacts) < 2, str(contacts))

from systems.action_registry import ACTION_SPECS
char_action = next(k for k, v in ACTION_SPECS.items() if v.get("target") == "character")
pool = {"nearby_characters": [{"id": "x1", "name": "Sam Jones", "relationship": ["neighbour", "introduced"]},
                              {"id": "x2", "name": "Pat Lee", "relationship": "stranger"}]}
try:
    res = ar.resolve_target(me, w, char_action, "the neighbour", pool)
    resolved = True
except Exception as exc:                                   # noqa: BLE001
    res, resolved = None, False
    print("   ", repr(exc))
check("resolving a target among people whose relationship is a list of labels does not raise", resolved)
check("and the labels count as text to match", res and res["ranked"] and res["ranked"][0][0] == "x1", str(res))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
