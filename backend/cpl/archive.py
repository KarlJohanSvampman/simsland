"""
cpl/archive.py -- finished conversations to the append-only archive tables (docs/cpl_implementation_plan.md C1, 5;
schema: scripts/migrations/cpl_001_archive.sql, created here if missing).

    on `cpl.conversation_ended`: a copy of the conversation (participants, messages, its requests) is queued, and a
    background thread writes it -- INSERT ... ON CONFLICT DO NOTHING, so a conversation archived twice is written once.
    The step never waits on Postgres. The live state stays the world's; these rows are history and metrics only.

    The finished conversation itself stays on the world for GC_AFTER_S (what was just said is still context), then a
    `gc` timer drops it, with its settled requests (open, deferred or negotiating ones stay: invariant 9).
"""

import json
import os
import queue
import threading

from core.event_bus import subscribe

GC_AFTER_S = 3600.0
SIM_ID = os.getenv("SIM_ID", "default")
_q = queue.Queue()
_thread = None
_stats = {"queued": 0, "written": 0, "failed": 0}
_tables_ok = False

_SCHEMA = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "migrations", "cpl_001_archive.sql")


def _snapshot(world, conv):
    reqs = [dict(r) for r in (world.get("cpl_requests") or {}).values() if r.get("conversation_id") == conv["id"]]
    return json.loads(json.dumps({"conv": conv, "requests": reqs}, default=str))


def _on_ended(data, world):
    from cpl import store
    from core import scheduler
    from core.clock import now_ts
    conv = store.get(world, data.get("conversation_id")) if world is not None else None
    if conv is None:
        return
    _q.put((SIM_ID, _snapshot(world, conv)))
    _stats["queued"] += 1
    _ensure_thread()
    scheduler.schedule_at(world, f"cpl:{conv['id']}", "gc", now_ts(world) + GC_AFTER_S, {})


def gc(world, conversation_id):
    """Drop a finished conversation from the world (it is in the archive), and its settled requests."""
    from cpl import store
    from cpl.model.enums import FINAL
    conv = store.get(world, conversation_id)
    if conv is None or conv.get("state") not in {s.value for s in FINAL}:
        return False
    del world["cpl_conversations"][conversation_id]
    reqs = world.get("cpl_requests") or {}
    for rid in [rid for rid, r in reqs.items() if r.get("conversation_id") == conversation_id
                and r.get("status") not in ("open", "deferred", "negotiating", "conditional")]:
        del reqs[rid]
    m = world.get("cpl_legacy_map") or {}
    for k in [k for k, v in m.items() if v == conversation_id]:
        del m[k]
    return True


def _ensure_thread():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_writer, name="cpl-archive", daemon=True)
        _thread.start()


def _ensure_tables(cur):
    global _tables_ok
    if not _tables_ok:
        cur.execute(open(_SCHEMA).read())
        _tables_ok = True


def write(sim_id, snap):
    """One finished conversation, in one transaction (idempotent)."""
    import db
    from psycopg2.extras import execute_values, Json
    c = snap["conv"]
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            _ensure_tables(cur)
            cur.execute("""INSERT INTO cpl_conversations (sim_id, conversation_id, channel, primary_purpose,
                               current_topic, status, resolution_reason, initiator_id, created_at, started_at,
                               last_activity_at, resolved_at, context_summary, outcome)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (sim_id, c["id"], c.get("channel") or "in_person", c.get("purpose"), c.get("topic"),
                         c.get("state"), c.get("reason"), c.get("initiator_id"), c.get("created_at"),
                         c.get("started_at"), c.get("last_activity_at"), c.get("resolved_at"),
                         Json(c.get("context") or {}), Json(c.get("outcome") or {})))
            parts = [(sim_id, c["id"], pid, p.get("role"), p.get("status"), p.get("joined_at"), p.get("left_at"),
                      p.get("left_reason"), p.get("last_seen_seq")) for pid, p in (c.get("participants") or {}).items()]
            if parts:
                execute_values(cur, "INSERT INTO cpl_participants VALUES %s ON CONFLICT DO NOTHING", parts)
            msgs = [(sim_id, m["message_id"], c["id"], m["sequence_number"], m.get("sender_id"),
                     m.get("message_type") or "statement", Json(m.get("payload") or {}), m.get("content"),
                     m.get("world_ts"), "delivered") for m in c.get("messages") or [] if m.get("message_id")]
            if msgs:
                execute_values(cur, "INSERT INTO cpl_messages VALUES %s ON CONFLICT DO NOTHING", msgs)
            reqs = [(sim_id, r["id"], r.get("conversation_id"), r.get("source_message_id"), r.get("requester_id"),
                     r.get("recipient_id"), r.get("kind"), r.get("status"), r.get("deadline"),
                     Json(r.get("history") or [])) for r in snap.get("requests") or []]
            if reqs:
                # a request's later status (accepted after a deferral, ...) replaces the earlier row
                execute_values(cur, """INSERT INTO cpl_requests VALUES %s ON CONFLICT (sim_id, request_id) DO UPDATE
                                       SET request_status = EXCLUDED.request_status, history = EXCLUDED.history""", reqs)


def _writer():
    while True:
        sim_id, snap = _q.get()
        try:
            write(sim_id, snap)
            _stats["written"] += 1
        except Exception as exc:
            _stats["failed"] += 1
            print(f"[cpl.archive] could not archive {snap.get('conv', {}).get('id')}: {exc!r}")
        finally:
            _q.task_done()


def flush(timeout=10.0):
    """Wait for the queue to drain (tests, shutdown)."""
    import time
    end = time.monotonic() + timeout
    while _q.unfinished_tasks and time.monotonic() < end:
        time.sleep(0.02)


def stats():
    return dict(_stats, pending=_q.qsize())


subscribe("cpl.conversation_ended", _on_ended)
