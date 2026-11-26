"""
systems/walkout.py

Nobody just walks off in the middle of a conversation without it meaning something.

Live (2026-11-25): Anthony and Alexander argued for five lines, Anthony asked "What's going on?" -- and Alexander had
walked off. The conversation ended "left" and nothing more came of it: no word from Alexander, no thought about why,
and Anthony never asked.

When a two-person conversation ends because one of them went (out of earshot, another building, left the
conversation), and neither of them closed it ("I've got to go", "talk later", "bye"):

  * the one who left (the leaver) is asked, at once, why: tell the other -- a text or a call, now that they're apart --
    or, if they'd rather not, think it through ("this was just going in circles"). Whatever they decide is kept on the
    record (thought, or what they said);
  * the one left behind waits FOLLOW_UP_TICKS for a word from the leaver. If none comes, they are asked to follow up:
    text or call them about it.

world["walkouts"] = [{conv_id, leaver, left, tick, leaver_line, left_line, status, asked_tick, thought, told_tick,
                      follow_up_tick, done_tick, outcome}]
world["walkout_stats"] = {walked_out, closed_properly, told, thought_only, followed_up, expired}
"""

import re

from core import scheduler as _scheduler

OWNER = "walkout"
CHECK_EVERY = 60            # sim seconds between sweeps
FOLLOW_UP_TICKS = 600       # how long the one left behind waits for a word before following up
EXPIRE_TICKS = 6 * 3600     # an unresolved walk-out is let go after this
KEPT = 40

LEFT_REASONS = {"left", "participant_left", "angry_withdrawal"}

# A line that closes a conversation: saying you're going, or goodbye.
_CLOSING = re.compile(
    r"\b(bye|goodbye|good night|goodnight|see (you|ya)|talk (to you )?(later|soon|tomorrow)|catch you|"
    r"(got|gotta|have|need|ought) to (go|run|head|get going|leave)|i'?m (off|heading|going to head)|"
    r"i'?ll (let you go|leave you|go now)|take care|let'?s (talk|pick this up|continue) (about (it|this) )?"
    r"(later|tomorrow|another time)|excuse me|i need (some )?(space|air|a minute|a moment)|i'?m done (talking|with this)|"
    r"we'?ll talk (later|tomorrow|about (it|this) later))", re.I)


def closes(line):
    return bool(_CLOSING.search(str(line or "")))


def _stats(world):
    return world.setdefault("walkout_stats", {"walked_out": 0, "closed_properly": 0, "told": 0, "thought_only": 0,
                                              "followed_up": 0, "expired": 0})


def _name(world, cid):
    return ((world.get("characters") or {}).get(cid) or {}).get("name") or "Someone"


def _first(world, cid):
    return _name(world, cid).split(" ")[0]


def _away(c):
    return (not c or c.get("alive") is False or c.get("off_grid")
            or (c.get("activity") or {}).get("type") == "sleep")


def leaver_of(world, conv):
    """Who went: what the ending recorded, else whoever is asleep / gone, else whoever moved furthest from where they
    stood when it started, else the one who didn't speak last (the other was talking to someone no longer there)."""
    parts = [p for p in conv.get("participants") or []]
    if conv.get("left_by") in parts:
        return conv["left_by"]
    chars = world.get("characters") or {}
    gone = [p for p in parts if _away(chars.get(p))]
    if len(gone) == 1:
        return gone[0]
    start = conv.get("_start_pos") or {}
    moved = {}
    for p in parts:
        c, s = chars.get(p), start.get(p)
        if c and s:
            moved[p] = abs(c.get("x", 0) - s[0]) + abs(c.get("y", 0) - s[1]) + (
                20 if (c.get("_in_building") or None) != s[2] else 0)
    if len(moved) == 2:
        a, b = sorted(moved, key=moved.get, reverse=True)
        if moved[a] > moved[b]:
            return a
    lines = [h for h in conv.get("history") or [] if h.get("utterance")]
    if lines and len(parts) == 2:
        last = lines[-1].get("speaker")
        return next((p for p in parts if p != last), None)
    return None


def note(world, conv, entry=None):
    """A conversation has ended (systems/conversation_archive.py): was someone walked out on?"""
    reason = conv.get("end_reason") or (entry or {}).get("end_reason")
    parts = [p for p in conv.get("participants") or []]
    if reason not in LEFT_REASONS or len(parts) != 2:
        return None
    lines = [h for h in conv.get("history") or [] if h.get("utterance")]
    if conv.get("outcome") or len(lines) < 2:
        return None                               # settled, or a single call that wasn't taken up (owe_answer's job)
    leaver = leaver_of(world, conv)
    if not leaver:
        return None
    left = next(p for p in parts if p != leaver)
    mine = [h for h in lines if h.get("speaker") == leaver]
    theirs = [h for h in lines if h.get("speaker") == left]
    if not mine:
        return None                               # never joined in: an ignored opener, not a walk-out
    stats = _stats(world)
    if closes(mine[-1].get("utterance")) or (theirs and closes(theirs[-1].get("utterance"))):
        stats["closed_properly"] += 1
        return None
    chars = world.get("characters") or {}
    if (chars.get(left) or {}).get("alive") is False:
        return None
    tick = world.get("tick", 0)
    rec = {"conv_id": conv.get("id"), "leaver": leaver, "left": left, "tick": tick,
           "leaver_line": str(mine[-1].get("utterance") or "")[:200],
           "left_line": str((theirs[-1] if theirs else {}).get("utterance") or "")[:200],
           "status": "open", "asked_tick": None, "thought": None, "told_tick": None,
           "follow_up_tick": None, "done_tick": None, "outcome": None}
    recs = world.setdefault("walkouts", [])
    recs.append(rec)
    del recs[:-KEPT]
    stats["walked_out"] += 1
    _ask_leaver(world, rec)
    return rec


def _ask_leaver(world, rec):
    c = (world.get("characters") or {}).get(rec["leaver"])
    if _away(c):
        return                                    # fell asleep / gone off: nothing to ask now
    other = _first(world, rec["left"])
    said = f' Their last words: "{rec["left_line"]}"' if rec["left_line"] else ""
    line = (f"You just walked away from your conversation with {other} in the middle of it, without a word.{said} "
            f"Why did you go? If {other} should know, tell them now -- you're apart, so text them (phone_send_text, the words in action.message) or call "
            f"them (phone_call). "
            f"If you'd rather not tell them, think it through in your thought -- e.g. \"this conversation was just "
            f"going in circles\", or what you had to get to.")
    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "walked_out", {"line": line})
    rec["asked_tick"] = world.get("tick", 0)


def _spoke_to(c, target, since):
    return any(e.get("target") == target and (e.get("tick") or 0) >= since for e in (c or {}).get("speech_log") or [])


def after_decision(c, world, decision):
    """The leaver's answer to being asked (brain/cognition_actor.py): what they thought, and whether they told them."""
    for rec in world.get("walkouts") or []:
        if rec.get("status") != "open" or rec.get("leaver") != c.get("id") or rec.get("asked_tick") is None:
            continue
        decision = decision or {}
        action = decision.get("action") or {}
        speech = decision.get("speech") or {}
        to_them = bool(speech.get("utterance") and speech.get("target") == rec["left"]) or (
            action.get("type") in ("phone_send_text", "phone_call", "text", "call")
            and (action.get("target_id") or action.get("target")) == rec["left"])
        if rec.get("thought") is None and decision.get("thought"):
            rec["thought"] = str(decision["thought"])[:300]
        if to_them:
            _resolve(world, rec, "told")


def _resolve(world, rec, outcome):
    if rec.get("status") != "open":
        return
    rec["status"] = "done"
    rec["outcome"] = outcome
    rec["done_tick"] = world.get("tick", 0)
    if outcome == "told":
        rec["told_tick"] = rec["done_tick"]
    _stats(world)[outcome] = _stats(world).get(outcome, 0) + 1


def _together(world, a, b):
    for conv in (world.get("conversations") or {}).values():
        if conv.get("active") and a in (conv.get("participants") or []) and b in (conv.get("participants") or []):
            return True
    return False


def sweep(world, entry=None):
    chars = world.get("characters") or {}
    t = world.get("tick", 0)
    for rec in world.get("walkouts") or []:
        if rec.get("status") != "open":
            continue
        leaver, left = chars.get(rec["leaver"]), chars.get(rec["left"])
        if not leaver or not left:
            _resolve(world, rec, "expired")
            continue
        if _spoke_to(leaver, rec["left"], rec["tick"] + 1):
            _resolve(world, rec, "told")
            continue
        if rec.get("follow_up_tick") is not None and (_spoke_to(left, rec["leaver"], rec["follow_up_tick"])
                                                     or _together(world, rec["leaver"], rec["left"])):
            _resolve(world, rec, "followed_up")
            continue
        if t - rec["tick"] >= EXPIRE_TICKS:
            _resolve(world, rec, "thought_only" if rec.get("thought") else "expired")
            continue
        if rec.get("asked_tick") is None and not _away(leaver) and t - rec["tick"] < FOLLOW_UP_TICKS:
            _ask_leaver(world, rec)               # was asleep / away when it happened
        if rec.get("follow_up_tick") is None and t - rec["tick"] >= FOLLOW_UP_TICKS and not _away(left):
            _ask_to_follow_up(world, rec)


def _ask_to_follow_up(world, rec):
    c = (world.get("characters") or {}).get(rec["left"])
    who = _first(world, rec["leaver"])
    mins = max(1, (world.get("tick", 0) - rec["tick"]) // 60)
    said = f' You had just said: "{rec["left_line"]}"' if rec["left_line"] else ""
    line = (f"{who} walked off in the middle of your conversation {mins} minutes ago and hasn't said a word since."
            f"{said} Follow up: text {who} (phone_send_text, the words in action.message) or call them (phone_call) to ask what happened, or to finish what you were "
            f"talking about.")
    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "walkout_follow_up", {"line": line})
    rec["follow_up_tick"] = world.get("tick", 0)


def prompt_line(world, c):
    """While a walk-out is open: the leaver remembers they owe an explanation; the other that they were left. While in
    a conversation: going means saying so first."""
    for rec in reversed(world.get("walkouts") or []):
        if rec.get("status") != "open":
            continue
        if rec["leaver"] == c.get("id"):
            return (f"You walked off in the middle of a conversation with {_first(world, rec['left'])} without "
                    f"saying why.")
        if rec["left"] == c.get("id") and rec.get("follow_up_tick") is not None:
            return (f"{_first(world, rec['leaver'])} walked off in the middle of your conversation and hasn't "
                    f"explained -- a text or a call would settle it.")
    for conv in (world.get("conversations") or {}).values():
        if conv.get("active") and c.get("id") in (conv.get("participants") or []) and len(conv.get("history") or []) >= 2:
            return "You're in the middle of a conversation: if you need to go, say so (and why) before you leave."
    return None


def summary(world):
    recs = world.get("walkouts") or []
    return {"stats": dict(_stats(world)),
            "recent": [{"leaver": _name(world, r["leaver"]), "left": _name(world, r["left"]),
                        "status": r["status"], "outcome": r["outcome"], "thought": r["thought"],
                        "leaver_line": r["leaver_line"], "left_line": r["left_line"],
                        "followed_up": r["follow_up_tick"] is not None} for r in recs[-10:]]}


_scheduler.register_recurring(OWNER, sweep, CHECK_EVERY, offset=30)
