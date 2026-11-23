"""
core/client_view.py: the browser gets a summary of each logged conversation; the full entry is fetched when its modal
opens (GET /api/conversation/{id}?participants=..., api/events.py -- which now finds an entry by its "id" too).

Run inside the backend container:   python tests/test_client_view.py
"""
import json, os, sys
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from core.client_view import client_value, client_character
entry = {"id": "conv_1", "with": [{"id": "d", "name": "Daniel"}], "initiator": "r", "medium": "in_person",
         "started_tick": 1, "ended_tick": 9, "end_reason": "resolved",
         "lines": [{"tick": 2, "speaker": "r", "utterance": "Daniel, we need to talk " * 5}] * 11,
         "tags": {"subject": "dinner", "opening": "complaint", "tags": ["family"], "issues": [{"subject": "x" * 400}],
                  "confrontation": {"type": "argument", "outcome": "unresolved", "summary": "y" * 300},
                  "agreement": {"title": "Dishes", "terms": [{"responsible": "r", "obligation": "z" * 200}]}}}
s = client_value("conversation_log", [entry])[0]
check("no lines go to the page, just how many", "lines" not in s and s["line_count"] == 11)
check("what the list shows is kept (who, when, how it ended, subject, chips)",
      s["id"] == "conv_1" and s["with"][0]["name"] == "Daniel" and s["end_reason"] == "resolved"
      and s["tags"]["subject"] == "dinner" and s["tags"]["confrontation"] == {"type": "argument", "outcome": "unresolved"}
      and s["tags"]["agreement"] == {"title": "Dishes"}, s)
check("the heavy readings stay behind", "issues" not in s["tags"] and s["summary_only"] is True)
check("much smaller", len(json.dumps(s)) * 5 < len(json.dumps(entry)), (len(json.dumps(s)), len(json.dumps(entry))))
c = {"id": "r", "name": "Rachel", "conversation_log": [entry], "memories": [1], "_step": {"x": 1}}
cc = client_character(c, skip=("_step",))
check("a whole character: the log summarized, skipped keys left out, the rest untouched",
      "lines" not in cc["conversation_log"][0] and "_step" not in cc and cc["memories"] == [1])
check("other fields pass through as they are", client_value("memories", [1, 2]) == [1, 2])

import types
if "db" not in sys.modules:                  # api/events.py imports db (a live database) -- not needed for this lookup
    _db = types.ModuleType("db")
    _db.load_world = _db.read_world = lambda *a, **k: {}
    sys.modules["db"] = _db
import api.events as ev
ev.load_world = lambda sim_id: {"characters": {"r": c}, "conversations": {}}
full = ev.get_conversation("conv_1", participants="r")
check("the modal's fetch finds the entry by its id, with every line", full.get("ok") and len(full.get("lines") or []) == 11, full.get("error"))

print("all passed" if not failures else f"FAILED: {len(failures)}")
sys.exit(1 if failures else 0)
