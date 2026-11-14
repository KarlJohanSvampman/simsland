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


_NEEDS_READING = {"conflict", "persuasion", "negotiation", "gossip", "emotional"}


def skippable(world, legacy_id):
    """Phase 5 (C9): a conversation whose structure already says everything the reader would add -- every line carried
    CPL's lines, two people, no claims about others, nothing to read between the lines (no conflict, persuasion,
    negotiation, gossip, feelings) -- needs no AI reading. CPL_MODE=on only."""
    from cpl import config
    if config.mode(world) != "on":
        return False
    conv = for_legacy(world, legacy_id)
    if not conv or conv.get("claims") or conv.get("purpose") in _NEEDS_READING:
        return False
    if len(conv.get("participants") or {}) != 2:
        return False
    return conv.get("lines", 0) >= 1 and conv.get("structured_lines", 0) >= conv.get("lines", 0)


def minimal_tags(world, legacy_id):
    """What the reader would have said, from the structure: the subject, and nothing else to apply."""
    conv = for_legacy(world, legacy_id) or {}
    return {"subject": conv.get("topic") or "a short exchange", "tags": [], "interaction_tags": [], "issues": [],
            "skipped": "structured", "structured": lines(world, conv)}
