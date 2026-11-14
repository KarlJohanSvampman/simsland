"""
cpl/record.py -- the structured record of a conversation, as lines for a reader (docs/cpl_implementation_plan.md C9):
who asked what and how it was answered, what was agreed, what was claimed and how it was taken, how it ended. Fed to
the AI that reads the finished transcript (llm/conversation_tags.py, via social/discourse.py) as ground truth, so it
doesn't have to guess what the structure already says.
"""


def _name(world, cid):
    return ((world.get("characters") or {}).get(cid) or {}).get("name") or cid


def for_legacy(world, legacy_id):
    """The CPL conversation that followed a legacy one (still on the world until its gc), or None."""
    for conv in (world.get("cpl_conversations") or {}).values():
        if conv.get("legacy_id") == legacy_id:
            return conv
    return None


def lines(world, conv):
    if not conv:
        return []
    out = []
    for q in (conv.get("questions") or {}).values():
        out.append(f"{_name(world, q['asker_id'])} asked {_name(world, q.get('to_id'))}: \"{q['text']}\" -> "
                   + ("answered" if q["status"] == "answered" else q["status"].replace("_", " ")))
    for r in (world.get("cpl_requests") or {}).values():
        if r.get("conversation_id") != conv["id"]:
            continue
        what = "proposed" if r.get("kind") == "proposal" else "asked for"
        last = (r.get("history") or [{}])[-1]
        cond = f" (on condition: {last['condition']})" if last.get("condition") else ""
        out.append(f"{_name(world, r['requester_id'])} {what}: \"{r['action']}\" -> {r['status']}{cond}"
                   + (f" [agreement {r['contract_id']}]" if r.get("contract_id") else ""))
    for cl in (conv.get("claims") or {}).values():
        out.append(f"{_name(world, cl['by'])} claimed: \"{cl['text']}\" -> {cl['status']}"
                   + (" (heard, not confirmed)" if cl["status"] == "acknowledged" else ""))
    if conv.get("reason"):
        out.append(f"it ended: {conv['reason'].replace('_', ' ')}")
    return out
