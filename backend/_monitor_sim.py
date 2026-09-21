"""
Throwaway monitoring script -- NOT part of the app, delete after use.

Polls the live world every 10s and prints any new shared_event / scripted
remote-conversation entries as they appear, so they can be surfaced live
via the Monitor tool without repeatedly polling docker-exec by hand.
Read-only (never calls save_world) -- safe to run alongside the live
backend process.
"""
import time
from db import load_world

world = load_world("default")
seen_event_ids = {e.get("id") for e in world.get("events", [])}
seen_scripted_ids = set(world.get("scripted_conversations", {}).keys())
seen_conv_history_len = {
    cid: len(conv.get("history", []))
    for cid, conv in world.get("conversations", {}).items()
}

print("[monitor] started -- watching for new shared_events / scripted conversations / new lines in remote exchanges", flush=True)

while True:
    time.sleep(10)
    world = load_world("default")
    chars = world.get("characters", {})

    for e in world.get("events", []):
        eid = e.get("id")
        if not eid or eid in seen_event_ids:
            continue
        seen_event_ids.add(eid)
        names = [chars.get(cid, {}).get("name", cid) for cid in e.get("participants", [])]
        sub = (e.get("subcategory") or {}).get("subcategory")
        medium = e.get("medium")
        severity = e.get("severity")
        tag = e.get("type", "")
        if sub:
            tag += f"/{sub}"
        if medium:
            tag += f" via {medium}"
        if severity:
            tag += f" ({severity})"
        print(f"[EVENT] {tag} -- {' & '.join(names) or e.get('participants')}: {e.get('text')}", flush=True)

    scripted = world.get("scripted_conversations", {})
    for conv_id, sc in scripted.items():
        if conv_id not in seen_scripted_ids:
            seen_scripted_ids.add(conv_id)
            names = [chars.get(cid, {}).get("name", cid) for cid in sc.get("participants", [])]
            print(f"[SCRIPTED START] {sc.get('medium')} -- {' & '.join(names)} ({sc.get('tier')}, {len(sc.get('script', []))} lines)", flush=True)

    for cid, conv in world.get("conversations", {}).items():
        if conv.get("medium") not in ("call", "text"):
            continue
        history = conv.get("history", [])
        prev_len = seen_conv_history_len.get(cid, 0)
        if len(history) > prev_len:
            for msg in history[prev_len:]:
                speaker = chars.get(msg.get("speaker"), {}).get("name", msg.get("speaker"))
                print(f"[LINE {conv.get('medium')}] {speaker}: {msg.get('utterance')}", flush=True)
        seen_conv_history_len[cid] = len(history)
        if cid in seen_scripted_ids and cid not in scripted:
            print(f"[SCRIPTED END] conversation {cid} concluded", flush=True)
            seen_scripted_ids.discard(cid)
