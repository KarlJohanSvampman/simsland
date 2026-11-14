"""
CPL phase 1 (docs/cpl_implementation_plan.md C1, section 5): a finished conversation is written to the append-only
archive tables -- once, however often it is archived -- and an hour later dropped from the world (open requests stay).

Run inside the backend container (needs Postgres):   python tests/test_cpl_archive.py
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


import db
from core import event_bus, scheduler
from cpl import archive, store
from cpl import conversations as CV

SIM = "cpl_archive_test"
archive.SIM_ID = SIM
with db._conn_lock, db.conn:
    with db.conn.cursor() as cur:
        archive._ensure_tables(cur)
        for t in ("cpl_conversations", "cpl_participants", "cpl_messages", "cpl_requests"):
            cur.execute(f"DELETE FROM {t} WHERE sim_id=%s", (SIM,))

w = {"tick": 0, "sim_time": 5000.0, "timers": [], "characters": {"a": {"id": "a"}, "b": {"id": "b"}}}
c = CV.open_conversation(w, "a", ["b"], channel="in_person", purpose="request", topic="the car")
open_req = store.add_request(w, c, kind="request", requester_id="a", recipient_id="b", action="lend me 20",
                             source_message_id=None, now=5000.0)
done_req = store.add_request(w, c, kind="request", requester_id="a", recipient_id="b", action="borrow the car",
                             source_message_id=None, now=5000.0)
for n, (who, text) in enumerate([("a", "Could I borrow your car?"), ("b", "Sure.")]):
    store.append_message(w, c, {"message_id": f"m{n}", "conversation_id": c["id"], "sender_id": who,
                                "recipient_ids": [], "message_type": "statement", "world_ts": 5000.0 + n,
                                "payload": {}, "content": text})
CV.submit(w, c, {"type": "turn", "by": "b"})
store.set_request_status(w, done_req["id"], "accepted", 5001.0)
CV.submit(w, c, {"type": "turn", "by": "b", "control": "leave"})
event_bus.flush(w)
archive.flush()
archive._on_ended({"conversation_id": c["id"]}, w)          # archived a second time
archive.flush()


def rows(table):
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table} WHERE sim_id=%s", (SIM,))
            return cur.fetchone()[0]


check("the finished conversation is in the archive, once", rows("cpl_conversations") == 1, archive.stats())
check("... its participants, messages and requests too", rows("cpl_participants") == 2 and rows("cpl_messages") == 2
      and rows("cpl_requests") == 2, (rows("cpl_participants"), rows("cpl_messages"), rows("cpl_requests")))
check("nothing failed", archive.stats()["failed"] == 0, archive.stats())
check("a gc timer is set for it", any(t["owner"] == f"cpl:{c['id']}" and t["key"] == "gc" for t in w["timers"]))
w["sim_time"] += archive.GC_AFTER_S + 1
scheduler.fire_due(w)
check("an hour later it is gone from the world", store.get(w, c["id"]) is None)
check("... with its settled request; the open one stays (invariant 9)",
      done_req["id"] not in w["cpl_requests"] and open_req["id"] in w["cpl_requests"])

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
