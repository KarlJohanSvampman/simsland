"""
systems/conversation_health.py -- is a conversation two people talking, or one person talking at another?

Live (2026-11-25, the user): counting lines hid the real problem. A conversation could run to a dozen lines with the
person addressed answering once or twice and the other going on alone ("What's really going on here?" again and again,
Alexander silent for 900 seconds; Christopher talking to his dad six times after one reply). Every finished two-person
conversation is scored here (systems/conversation_archive.py calls note()):

    kind   "unanswered"   nobody ever replied
           "one_sided"    after the first reply, only the opener spoke (2+ lines)
           "lopsided"     after the first reply, the opener said at least three times as much (3+ lines)
           "short"        a reply, then it ended with nothing more from either side
           "balanced"     both kept talking
    plus who stopped answering and how it ended.

world["_conv_health"] = {"counts": {kind: n}, "recent": [score, ...]}   (RECENT_KEPT newest)
GET /admin/conversation_health shows it (api/admin.py).
"""

RECENT_KEPT = 60
_KINDS = ("unanswered", "one_sided", "lopsided", "short", "balanced")


def score(entry):
    """The balance of one archived conversation (systems/conversation_archive.py's entry), or None if it isn't a
    two-person talk."""
    lines = [l for l in entry.get("lines") or [] if l.get("utterance")]
    people = entry.get("participants") or []
    if len(people) != 2 or not lines:
        return None
    opener = lines[0].get("speaker")
    other = next((p for p in people if p != opener), None)
    first = next((i for i, l in enumerate(lines) if l.get("speaker") == other), None)
    out = {"id": entry.get("id"), "opener": opener, "other": other, "lines": len(lines),
           "end_reason": entry.get("end_reason"), "started_tick": entry.get("started_tick")}
    if first is None:
        out.update(kind="unanswered", opener_after=len(lines) - 1, other_after=0)
        return out
    after = lines[first + 1:]
    a = sum(1 for l in after if l.get("speaker") == opener)
    b = sum(1 for l in after if l.get("speaker") == other)
    out.update(opener_after=a, other_after=b)
    if a >= 2 and b == 0:
        out["kind"] = "one_sided"
    elif a >= 3 and b * 3 <= a:
        out["kind"] = "lopsided"
    elif a == 0 and b == 0:
        out["kind"] = "short"
    else:
        out["kind"] = "balanced"
    if out["kind"] in ("one_sided", "lopsided"):
        out["quiet"] = other                     # who stopped answering
    return out


def note(world, entry):
    s = score(entry)
    if not s:
        return None
    h = world.setdefault("_conv_health", {"counts": {}, "recent": []})
    h["counts"][s["kind"]] = h["counts"].get(s["kind"], 0) + 1
    h["recent"] = (h.get("recent") or [])[-(RECENT_KEPT - 1):] + [s]
    return s


def summary(world):
    h = world.get("_conv_health") or {"counts": {}, "recent": []}
    counts = {k: h["counts"].get(k, 0) for k in _KINDS}
    answered = sum(v for k, v in counts.items() if k != "unanswered")
    bad = counts["one_sided"] + counts["lopsided"]
    return {"counts": counts, "answered": answered,
            "one_sided_share": round(bad / answered, 3) if answered else None,
            "recent_lopsided": [r for r in h.get("recent") or [] if r.get("kind") in ("one_sided", "lopsided")][-10:]}


# ── in the moment ────────────────────────────────────────────────────────────────────────────────────────────────

def unanswered_run(conv, speaker_id):
    """How many lines in a row speaker_id has said at the end of this conversation with nobody else answering."""
    n = 0
    for h in reversed(conv.get("history") or []):
        if not h.get("utterance"):
            continue
        if h.get("speaker") != speaker_id:
            break
        n += 1
    return n


def last_line_from(conv, speaker_id):
    for h in reversed(conv.get("history") or []):
        if h.get("utterance") and h.get("speaker") == speaker_id:
            return h
    return None


OWE_TICKS = 120      # how long a line spoken to someone keeps them owing an answer


def owes_answer(world, c):
    """(conversation, the line) when someone in a live two-person conversation said something to c and c hasn't
    answered yet -- within OWE_TICKS. None otherwise."""
    try:
        from brain.conversations import find_active_conversation_for
        conv = find_active_conversation_for(world, c.get("id"))
    except Exception:
        return None
    if not conv or len(conv.get("participants") or []) != 2 or conv.get("medium", "in_person") not in ("in_person", "call"):
        return None
    lines = [h for h in conv.get("history") or [] if h.get("utterance")]
    if not lines or lines[-1].get("speaker") == c.get("id"):
        return None
    if world.get("tick", 0) - (lines[-1].get("tick") or 0) > OWE_TICKS:
        return None
    return conv, lines[-1]
