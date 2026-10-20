"""
core/event_log.py

A durable, queryable log of every event that passes through core/event_bus.py, plus
per-handler timing and a replay helper -- step 0 of the move to an event-driven
architecture (docs/distributed_architecture_plan.md): the old system becomes
observable before anything in it is changed, and handlers can be debugged by replaying
what really happened against a snapshot.

  record(type, data)       called by event_bus.emit() for every event (cheap: no
                           serialisation on the emitting thread)
  recent(limit, type)      newest first, from the in-process ring
  stream_range(...)        the Redis Stream copy (survives restarts, MAXLEN-trimmed)
  handler_stats()          per event type and handler: calls, errors, total/max seconds
  export_jsonl(...)        one JSON event per line, oldest first (feed to replay)
  replay(world, events)    run the live handlers over recorded events, in order

Each event: {"seq", "ts", "tick", "type", "data"}; `seq` is per process, ordering is by seq.
"""

import json
import queue
import threading
import time
from collections import deque

STREAM_KEY = "simsland:events"
STREAM_MAXLEN = 100_000
RING_SIZE = 5000
DATA_MAX_CHARS = 6000
FLUSH_INTERVAL_SECONDS = 0.5

_lock = threading.Lock()
_seq = 0
_tick = 0
_ring = deque(maxlen=RING_SIZE)
_outbox = queue.SimpleQueue()
_handler_stats = {}          # (type, handler) -> [calls, errors, total, max]
_enabled = True
_writer_started = False


def set_tick(tick):
    global _tick
    _tick = tick


def enable(flag=True):
    global _enabled
    _enabled = bool(flag)


def record(event_type, data):
    global _seq
    if not _enabled:
        return
    with _lock:
        _seq += 1
        entry = {"seq": _seq, "ts": time.time(), "tick": _tick, "type": event_type, "data": data}
        _ring.append(entry)
    _outbox.put(entry)
    _ensure_writer()


def _serialise(entry):
    try:
        text = json.dumps(entry["data"], default=str)
    except Exception:
        text = json.dumps({"_unserialisable": True})
    truncated = len(text) > DATA_MAX_CHARS
    return {"seq": entry["seq"], "ts": f"{entry['ts']:.3f}", "tick": entry["tick"], "type": entry["type"],
            "data": text[:DATA_MAX_CHARS], "truncated": int(truncated)}


def _ensure_writer():
    global _writer_started
    if _writer_started:
        return
    with _lock:
        if _writer_started:
            return
        _writer_started = True
    threading.Thread(target=_writer_loop, name="event-log-writer", daemon=True).start()


def _writer_loop():
    try:
        from core.cache import r
    except Exception:
        return
    while True:
        time.sleep(FLUSH_INTERVAL_SECONDS)
        batch = []
        try:
            while len(batch) < 500:
                batch.append(_outbox.get_nowait())
        except queue.Empty:
            pass
        if not batch:
            continue
        try:
            pipe = r.pipeline(transaction=False)
            for entry in batch:
                pipe.xadd(STREAM_KEY, _serialise(entry), maxlen=STREAM_MAXLEN, approximate=True)
            pipe.execute()
        except Exception:
            pass          # Redis unavailable: the in-process ring still has them


def recent(limit=100, event_type=None, since_seq=None):
    with _lock:
        items = list(_ring)
    if event_type:
        items = [e for e in items if e["type"] == event_type]
    if since_seq is not None:
        items = [e for e in items if e["seq"] > since_seq]
    return items[-limit:][::-1]


def stream_range(count=200, event_type=None):
    """Newest-first from the Redis Stream (survives restarts)."""
    try:
        from core.cache import r
        rows = r.xrevrange(STREAM_KEY, count=count * (4 if event_type else 1))
    except Exception:
        return []
    out = []
    for sid, f in rows:
        f = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in f.items()}
        if event_type and f.get("type") != event_type:
            continue
        try:
            data = json.loads(f.get("data", "{}"))
        except Exception:
            data = {"_raw": f.get("data")}
        out.append({"id": sid.decode() if isinstance(sid, bytes) else sid, "seq": int(f.get("seq", 0)),
                    "ts": float(f.get("ts", 0)), "tick": int(f.get("tick", 0)), "type": f.get("type"),
                    "data": data, "truncated": bool(int(f.get("truncated", 0)))})
        if len(out) >= count:
            break
    return out


def export_jsonl(limit=1000, event_type=None):
    """Oldest first, one JSON object per line -- the input format for replay."""
    rows = stream_range(limit, event_type) or [dict(e, data=e["data"]) for e in recent(limit, event_type)]
    lines = []
    for e in reversed(rows):
        try:
            lines.append(json.dumps({"seq": e["seq"], "ts": e["ts"], "tick": e["tick"], "type": e["type"],
                                     "data": e["data"]}, default=str))
        except Exception:
            continue
    return "\n".join(lines)


# ── handler timing ────────────────────────────────────────────────────────────

def note_handled(event_type, handler, seconds, ok):
    name = getattr(handler, "__qualname__", None) or getattr(handler, "__name__", repr(handler))
    key = (event_type, f"{getattr(handler, '__module__', '')}.{name}")
    with _lock:
        s = _handler_stats.setdefault(key, [0, 0, 0.0, 0.0])
        s[0] += 1
        s[1] += 0 if ok else 1
        s[2] += seconds
        if seconds > s[3]:
            s[3] = seconds


def handler_stats(top=None):
    with _lock:
        rows = [{"event": k[0], "handler": k[1], "calls": v[0], "errors": v[1],
                 "total_ms": round(v[2] * 1000, 2), "avg_ms": round(1000 * v[2] / v[0], 3) if v[0] else 0.0,
                 "max_ms": round(v[3] * 1000, 2)} for k, v in _handler_stats.items()]
    rows.sort(key=lambda r: -r["total_ms"])
    return rows[:top] if top else rows


# ── replay ────────────────────────────────────────────────────────────────────

def parse_jsonl(text):
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def replay(world, events, only_types=None):
    """Run the live subscribers over `events` (oldest first) against `world`, without
    re-logging them. Returns {"events", "handled", "errors": [...], "by_type": {...}} so a
    handler bug can be reproduced from a snapshot plus the events that hit it."""
    from core import event_bus
    was = _enabled
    enable(False)
    summary = {"events": 0, "handled": 0, "errors": [], "by_type": {}}
    try:
        for ev in events:
            etype = ev.get("type")
            if only_types and etype not in only_types:
                continue
            summary["events"] += 1
            summary["by_type"][etype] = summary["by_type"].get(etype, 0) + 1
            for name, ok, err in event_bus.dispatch(etype, ev.get("data") or {}, world):
                summary["handled"] += 1
                if not ok:
                    summary["errors"].append({"seq": ev.get("seq"), "type": etype, "handler": name, "error": err})
    finally:
        enable(was)
    return summary
