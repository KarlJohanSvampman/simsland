"""
systems/dialogue_feedback.py -- the director's notes on lines of dialogue (VR Conversations timeline,
frontend/src/vrConversations.js; text by dictation or the pointer keyboard, frontend/src/vrKeyboard.js).

On any line said: like or dislike it, say why (a comment), and/or suggest what would have fit the character better.
Kept on the character who SAID the line, one note per line (saying it again edits it), newest last:

    c["dialogue_feedback"] = [{id, conv_id, tick, utterance, verdict: "like" | "dislike" | None, comment, suggestion,
                               created_tick, updated_tick, used: False}]

"used" is for what comes next: notes like these turned into the character's own personal rules (so the same kind of
line doesn't come out of them again), and Director's Cut. Nothing reads them into prompts yet.
"""

import time
import uuid

KEPT = 500
TEXT_MAX = 1000
VERDICTS = ("like", "dislike", None)


def _same(e, conv_id, tick, utterance):
    return e.get("conv_id") == conv_id and e.get("tick") == tick and (e.get("utterance") or "") == (utterance or "")


def find(c, conv_id, tick, utterance):
    return next((e for e in c.get("dialogue_feedback") or [] if _same(e, conv_id, tick, utterance)), None)


def give(c, world, conv_id, tick, utterance, **changes):
    """Set any of verdict / comment / suggestion on the note for this line (made if there isn't one). A field left out
    is left as it is; "" clears a comment or suggestion; verdict=None clears the verdict. Returns the note, or None when
    it ends up empty (and is removed)."""
    if "verdict" in changes and changes["verdict"] not in VERDICTS:
        raise ValueError(f"verdict must be like, dislike or none, not {changes['verdict']!r}")
    log = c.setdefault("dialogue_feedback", [])
    e = find(c, conv_id, tick, utterance)
    now = world.get("tick", 0)
    if e is None:
        e = {"id": f"fb_{uuid.uuid4().hex[:8]}", "conv_id": conv_id, "tick": tick, "utterance": utterance,
             "verdict": None, "comment": "", "suggestion": "", "created_tick": now, "created_ts": time.time(), "used": False}
        log.append(e)
    for k in ("verdict", "comment", "suggestion"):
        if k in changes:
            v = changes[k]
            e[k] = (str(v).strip()[:TEXT_MAX] if v is not None else "") if k != "verdict" else v
    e["updated_tick"] = now
    if not e["verdict"] and not e["comment"] and not e["suggestion"]:
        log.remove(e)
        return None
    del log[:-KEPT]
    return e


def remove(c, fb_id):
    before = len(c.get("dialogue_feedback") or [])
    c["dialogue_feedback"] = [e for e in c.get("dialogue_feedback") or [] if e.get("id") != fb_id]
    return len(c["dialogue_feedback"]) < before
