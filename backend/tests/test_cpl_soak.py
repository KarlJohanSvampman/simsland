"""
CPL soak (docs/cpl_implementation_plan.md phase 2 acceptance): a long social run with CPL_MODE=on, then the invariants
that must hold over all of it --

  * no conversation is live past its hard cap (spec invariant 15);
  * no message is stored twice; sequence numbers run in order;
  * nothing stays RESOLVED/EXPIRED on the world much past the gc delay, and no cpl:<id> timer belongs to a
    conversation that no longer exists;
  * every request of an ended conversation is settled or deliberately left open (invariant 9).

A sim day (about a minute). Run inside the backend container:   python tests/test_cpl_soak.py
"""

import os
import sys
from collections import Counter

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
from cpl import archive, config, policies

TICKS = int(os.getenv("SOAK_TICKS", "86400"))         # a sim day
config.CPL_MODE = "on"
w, errs, _ = determinism.run_sim(TICKS, start="2026-11-04T08:00:00")
check(f"{TICKS} ticks with CPL on, no errors", not errs, errs)
convs = w.get("cpl_conversations") or {}
st = w.get("cpl_shadow") or {}
print(f"   {st.get('opened', 0)} conversations opened, {st.get('lines', 0)} lines, on the world now: {len(convs)}; "
      f"reasons: {dict(Counter(c.get('reason') for c in convs.values()))}")
now = w.get("sim_time") or 0
over = [cid for cid, c in convs.items() if c["state"] not in ("resolved", "expired")
        and now - (c.get("started_at") or c["created_at"]) > policies.from_key(c["policy_key"])["hard_seconds"]]
check("no conversation is live past its hard cap", not over, over)
dup = [cid for cid, c in convs.items() if len({m["message_id"] for m in c["messages"]}) != len(c["messages"])]
check("no message stored twice", not dup, dup)
order = [cid for cid, c in convs.items() if [m["sequence_number"] for m in c["messages"]]
         != sorted(m["sequence_number"] for m in c["messages"])]
check("sequence numbers in order", not order, order)
stale = [cid for cid, c in convs.items() if c["state"] in ("resolved", "expired")
         and now - (c.get("resolved_at") or now) > archive.GC_AFTER_S + 120]
check("finished conversations are cleared off the world after the gc delay", not stale, stale[:5])
orphan = [t for t in w.get("timers") or [] if t["owner"].startswith("cpl:") and t["owner"][4:] not in convs]
check("no timer for a conversation that no longer exists", not orphan, orphan[:3])
loose = [r["id"] for r in (w.get("cpl_requests") or {}).values()
         if r.get("conversation_id") not in convs and r.get("status") not in ("open", "deferred", "negotiating",
                                                                               "conditional")]
check("settled requests of cleared conversations are gone; only open ones outlive them", not loose, loose[:5])

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
