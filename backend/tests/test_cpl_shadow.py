"""
CPL phase 1, step 2 (docs/cpl_implementation_plan.md section 11): CPL_MODE=shadow -- CPL follows the legacy
conversation path in a running simulation and changes nothing outside its own entities.

  * conversations, lines and the legacy endings all reach CPL;
  * when a legacy conversation ends, CPL's copy is recorded and closed: nothing is left live behind it, and no
    cpl:<id> timer outlives its conversation;
  * the tallies (cpl/shadow.py::compare) say how CPL's lifecycle stood at each legacy ending;
  * with CPL_MODE=off nothing of CPL exists at all.

(That the legacy outcome is identical with the shadow on is checked by the determinism runs: CPL_MODE=shadow vs off.)

Run inside the backend container:   python tests/test_cpl_shadow.py
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
from cpl import config, shadow, store

config.CPL_MODE = "off"
w0, errs0, _ = determinism.run_sim(600, start="2026-11-04T09:00:00")
check("CPL_MODE=off: no CPL state at all", not any(k.startswith("cpl") for k in w0), [k for k in w0 if k.startswith("cpl")])

config.CPL_MODE = "shadow"
w, errs, _ = determinism.run_sim(2400, start="2026-11-04T09:00:00")
check("the simulation runs with the shadow on", not errs, errs)
st = shadow.compare(w)
print(f"   shadow: {st}")
check("conversations and their lines reach CPL", st["opened"] > 0 and st["lines"] >= st["opened"], st)
check("every legacy ending is seen", st["legacy_ended"] > 0 and st["legacy_ended"] >= st["cpl_still_live"] + st["cpl_ended_first"], st)
mapped = w.get("cpl_legacy_map") or {}
legacy_live = {cid for cid, c in (w.get("conversations") or {}).items() if c.get("active")}
check("only conversations the legacy path still has open are live in CPL",
      all(lid in legacy_live for lid in mapped), {k: v for k, v in mapped.items() if k not in legacy_live})
dead = {cid for cid, c in (w.get("cpl_conversations") or {}).items() if c.get("state") in ("resolved", "expired")}
orphans = [t for t in w.get("timers") or [] if t["owner"].startswith("cpl:") and t["owner"][4:] in dead]
check("no timer outlives its conversation", not orphans, orphans[:3])
ended = [c for c in (w.get("cpl_conversations") or {}).values() if c.get("state") in ("resolved", "expired")]
check("ended conversations carry their reason and an outcome",
      ended and all(c.get("reason") and c.get("outcome") and c.get("resolved_at") for c in ended))
seqs_ok = all([m["sequence_number"] for m in c["messages"]] == sorted({m["sequence_number"] for m in c["messages"]})
              for c in (w.get("cpl_conversations") or {}).values())
check("messages are numbered in order, without duplicates", seqs_ok)
check("CPL's own counter makes the ids (no uuids: reproducible)",
      all(cid.startswith("cv_") and cid[3:].isdigit() for cid in w.get("cpl_conversations") or {}))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
