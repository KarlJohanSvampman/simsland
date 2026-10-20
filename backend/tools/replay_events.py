"""
Replay recorded bus events against a world snapshot -- reproduce a handler bug from the
events that hit it, or check what a recorded burst of events does to a saved world.

    # in the backend container
    curl -s "localhost:8000/admin/event_log/export?limit=2000" > /tmp/events.jsonl
    python tools/replay_events.py --world /tmp/world_backup.json --events /tmp/events.jsonl
    python tools/replay_events.py --world ... --events ... --types heard_speech,speech_spoken

The snapshot is a world JSON as written under backups/ (static map data and definitions are
filled in from the running world). Nothing is saved: the replay runs on an in-memory copy.
"""

import argparse
import hashlib
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")


def _digest(value):
    return hashlib.md5(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True, help="world snapshot JSON")
    ap.add_argument("--events", required=True, help="events JSONL (from /admin/event_log/export)")
    ap.add_argument("--types", help="comma separated event types to replay (default: all)")
    ap.add_argument("--sim", default="default")
    args = ap.parse_args()

    from db import load_world, _STATIC_WORLD_KEYS
    from core.definitions import load_definitions
    import core.event_handlers  # noqa: F401  (registers every subscription)
    from core import event_log

    world = json.load(open(args.world, encoding="utf-8"))
    live = load_world(args.sim)
    for k in set(_STATIC_WORLD_KEYS):
        if k in live:
            world[k] = live[k]
    world["definitions"] = load_definitions(args.sim)

    events = event_log.parse_jsonl(open(args.events, encoding="utf-8").read())
    before = {k: _digest(v) for k, v in world.items() if k not in set(_STATIC_WORLD_KEYS) | {"definitions"}}
    chars_before = {cid: _digest(c) for cid, c in world.get("characters", {}).items()}

    only = set(args.types.split(",")) if args.types else None
    summary = event_log.replay(world, events, only)

    changed = [k for k, v in before.items() if _digest(world.get(k)) != v]
    chars_changed = [cid for cid, d in chars_before.items() if _digest(world["characters"].get(cid)) != d]
    print(json.dumps({"summary": {k: summary[k] for k in ("events", "handled")},
                      "by_type": summary["by_type"], "errors": summary["errors"][:20],
                      "world_keys_changed": changed, "characters_changed": chars_changed}, indent=2, default=str))


if __name__ == "__main__":
    main()
