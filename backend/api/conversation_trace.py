"""
/admin/convtrace/{id} -- a character's conversations for VR "Conversations" (frontend/src/vrConversations.js), most
recent first: the ones going on now (world["conversations"]) and the finished ones they keep (c["conversation_log"],
systems/conversation_archive.py). Each: who, how (in person / call / text), when it started and ended (None while
it's going on) and why it ended, subject / tone / topic, every line said (tick, who, the words, speech act), and --
for one going on in person -- whether the others are really within sight and earshot now
(systems/conversation_reach.py).
"""

from fastapi import APIRouter, HTTPException

from db import load_world

router = APIRouter(prefix="/admin/convtrace", tags=["convtrace"])


def _lines(raw, names):
    out = []
    for h in raw or []:
        if not h.get("utterance"):
            continue
        sp = h.get("speaker")
        out.append({"tick": h.get("tick"), "speaker": sp, "speaker_name": names.get(sp, sp), "utterance": h.get("utterance"),
                    "speech_act": h.get("speech_act")})
    return out


@router.get("/{char_id}")
def convtrace(char_id: str, sim_id: str = "default", limit: int = 40):
    world = load_world(sim_id)
    chars = world.get("characters") or {}
    c = chars.get(char_id)
    if not c:
        raise HTTPException(404, f"no character '{char_id}'")
    names = {k: v.get("name") for k, v in chars.items()}
    rows, seen = [], set()
    for conv in (world.get("conversations") or {}).values():
        if not conv.get("active") or char_id not in (conv.get("participants") or []) or conv.get("_archived"):
            continue
        lines = _lines(conv.get("history"), names)
        if not lines:
            continue
        reach = None
        if (conv.get("medium") or "in_person") == "in_person":
            from systems.conversation_reach import check_pair
            reach = {}
            for oid in conv["participants"]:
                if oid != char_id and oid in chars and chars[oid].get("x") is not None:
                    r = check_pair(world, c, chars[oid])
                    reach[names.get(oid, oid)] = {"ok": r["ok"], "issues": r["issues"], "distance": r["distance"]}
        rows.append({"id": conv["id"], "active": True, "medium": conv.get("medium", "in_person"),
                     "with": [names.get(p, p) for p in conv["participants"] if p != char_id],
                     "started_tick": conv.get("started_at"), "ended_tick": None, "end_reason": None,
                     "subject": conv.get("subject"), "topic": conv.get("topic"), "tone": conv.get("tone"),
                     "type": conv.get("conversation_type"), "lines": lines, "reach_now": reach})
        seen.add(conv["id"])
    for e in reversed(c.get("conversation_log") or []):
        cid = e.get("id") or e.get("conv_id")
        if cid in seen:
            continue
        seen.add(cid)
        nm = dict(names, **(e.get("names") or {}))
        tags = e.get("tags") or {}
        rows.append({"id": cid, "active": False, "medium": e.get("medium", "in_person"),
                     "with": [w.get("name") or w.get("id") for w in e.get("with") or []] or
                             [nm.get(p, p) for p in e.get("participants") or [] if p != char_id],
                     "started_tick": e.get("started_tick"), "ended_tick": e.get("ended_tick"), "end_reason": e.get("end_reason"),
                     "subject": e.get("subject") or (tags.get("subject") if isinstance(tags, dict) else None),
                     "topic": e.get("topic"), "tone": e.get("tone") or (tags.get("tone") if isinstance(tags, dict) else None),
                     "lines": _lines(e.get("lines"), nm)})
    rows.sort(key=lambda r: (r["ended_tick"] is None, r["ended_tick"] or (r["lines"][-1]["tick"] if r["lines"] else 0)), reverse=True)
    return {"tick": world.get("tick", 0), "name": c.get("name"), "conversations": rows[:max(1, min(60, limit))]}
