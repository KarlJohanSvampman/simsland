"""
CPL phase 1, step 3 (docs/cpl_implementation_plan.md section 11): CPL_MODE=on -- CPL decides when a conversation
ends by time or length (cpl/policies.py: the looser defaults, decided), the legacy path's own such endings are held
back, and when CPL ends a conversation the legacy one ends with it.

  * a social simulation runs with it on, without errors;
  * conversations go past the legacy cap of 6 lines (the social policy allows 8 before winding down);
  * legacy time/length endings were held back, and CPL ended conversations itself (legacy ones with them);
  * nothing is left live past its hard cap, and no legacy conversation is open without a live CPL copy;
  * idle and cap timers: a conversation nobody talks in ends on its own.

Run inside the backend container:   python tests/test_cpl_on.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
os.environ["DET_POLICY"] = "social"
os.environ["DET_SETUP"] = "together"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from tests import determinism
from cpl import config, policies, shadow

config.CPL_MODE = "on"
w, errs, _ = determinism.run_sim(3000, start="2026-11-04T09:00:00")
check("a social simulation runs with CPL_MODE=on", not errs, errs)
st = shadow.compare(w)
print(f"   tallies: { {k: v for k, v in st.items() if k != 'pairs'} }")
convs = list((w.get("cpl_conversations") or {}).values())
check("CPL conversations went past the legacy 6-line cap", any(c.get("lines", 0) > 6 for c in convs),
      sorted(c.get("lines", 0) for c in convs))
check("legacy time/length endings were held back for CPL", st.get("held_back", 0) > 0, st)
check("CPL ended conversations itself, the legacy ones with them", st.get("cpl_ended", 0) > 0, st)
check("CPL's own reasons on what it ended", any(c.get("reason") in ("topic_exhausted", "question_answered", "timeout",
                                                                       "abandoned", "no_answer") for c in convs))
now = w.get("sim_time") or 0
over = [c["id"] for c in convs if c["state"] not in ("resolved", "expired")
        and now - (c.get("started_at") or c["created_at"]) > policies.from_key(c["policy_key"])["hard_seconds"]]
check("nothing live past its hard cap", not over, over)
mapped = set((w.get("cpl_legacy_map") or {}))
open_legacy = [cid for cid, c in (w.get("conversations") or {}).items() if c.get("active") and c.get("history")]
check("every open legacy conversation has a live CPL copy", all(cid in mapped for cid in open_legacy),
      [c for c in open_legacy if c not in mapped])

# ── idle and cap on a bare world ─────────────────────────────────────────────────────────────────────────────────────
from core import scheduler
from cpl import conversations as CV

config.CPL_MODE = "off"
b = {"tick": 0, "sim_time": 0.0, "characters": {"a": {"id": "a"}, "b": {"id": "b"}}, "timers": []}
c = CV.open_conversation(b, "a", ["b"], channel="in_person", purpose="social")
CV.submit(b, c, {"type": "turn", "by": "b"})
pol = policies.from_key(c["policy_key"])
b["sim_time"] = pol["idle_s"] + 1
scheduler.fire_due(b)
check("nobody says anything: it ends on the idle timer", c["state"] == "resolved" and c["reason"] in ("timeout", "abandoned"),
      (c["state"], c["reason"]))
c = CV.open_conversation(b, "a", ["b"], channel="in_person", purpose="social")
CV.submit(b, c, {"type": "turn", "by": "b"})
CV.submit(b, c, {"type": "turn", "by": "a", "control": "pause"})
b["sim_time"] += pol["hard_seconds"] + 1
scheduler.fire_due(b)
check("paused, and the hard cap passes: it ends (timeout)", c["state"] == "resolved", (c["state"], c["reason"]))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
