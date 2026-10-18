"""
systems/conversation_floor.py

Who has the "ball" in a two-person conversation, and how long anyone waits.

Before this, a conversation was just a history list and a round-robin
`turn_owner` nothing enforced. Both characters were free to speak whenever
their own (slow, parallel) LLM call happened to land, which produced exchanges
like: Theo asks "can we go outside and play?", Marcus answers, then Marcus
asks "Hey Theo, what's up?" -- both sides acting on stale context -- and
nobody was ever left waiting for an answer that didn't come.

conv["floor"] is the live state of the exchange:

    holder       who is expected to act next (the ball is with them)
    from         who put it there
    kind         confirm | binary_question | question | statement
    expects_reply  a question/greeting/request wants an answer; a plain remark
                 or an answer only leaves room for a comment
    state        waiting   - spoken, listener hasn't visibly noticed yet
                 thinking  - listener is generating a reply (the "thinking it
                             over" cue; no timeout while they do)
                 unnoticed - nobody reacted: speaker may repeat louder
                 unanswered- listener heard but said nothing: speaker may
                             follow up once
                 open      - no reply required; holder may comment, else the
                             ball passes on and the conversation lapses
    attempts     how many times the speaker has tried to get this answered
    aware        the holder began deciding what to do after the line

Timers (world ticks, 1 tick = 1 simulated second at 1x):
    notice window  3 ticks (+1 for the wake to land): a holder who has not
                   started responding by then did not register being spoken to
    a repeated line is louder; a second failed attempt ends the conversation
    reply window   5 ticks for a confirmation / yes-no question, longer for
                   something that needs thought -- the wait for a follow-up
                   after an answer, and the speaker's grace to retry

Ignoring someone who clearly spoke to you emits `conversation_ignored`
(heard: True/False) and the conversation ends; the consumers of that event
(insult -> grudge -> ledger) live elsewhere.

Only two-person, in-person/call conversations are managed; groups and
text/email keep the old behaviour.
"""

import re

AWARE_TICKS = 3            # time a listener gets to start responding
FLUSH_LAG = 1              # a heard line wakes the listener one tick later
THINK_CAP = 60             # a generation longer than this counts as no answer
RETRY_TICKS = 8            # how long the speaker has to try again
SIMPLE_WINDOW = 5
MIN_COMPLEX_WINDOW = 10
MAX_COMPLEX_WINDOW = 25
STALE_TICKS = 120          # a floor this old never blocks anyone

_REPLY_ACTS = {
    "ask", "question", "greet", "request", "propose", "invite", "suggest", "offer",
    "call", "summon", "apologize", "accuse", "insult", "threaten", "challenge", "flirt",
    "confront", "compliment", "thank",
}
_CONFIRM_ACTS = {"confirm", "agree", "acknowledge", "accept", "decline", "thank", "greet", "farewell"}
_BINARY_START = re.compile(
    r"^(is|are|am|do|does|did|can|could|will|would|shall|should|have|has|had|was|were|wanna|want|may|might)\b",
    re.I,
)

# Per-character generation tracking. Written from agent worker threads, read by
# tick() on the main thread -- the world copy a worker mutates may be thrown
# away (slow decisions are abandoned), so this lives in process memory.
_gen = {}


def mark_thinking(char_id, tick):
    _gen[char_id] = {"began": tick, "finished": -1}


def clear_thinking(char_id, tick):
    g = _gen.get(char_id)
    if g:
        g["finished"] = tick


def _began(char_id):
    return _gen.get(char_id, {}).get("began", -1)


def _is_thinking(char_id):
    g = _gen.get(char_id)
    return bool(g) and g["finished"] < g["began"]


# ── classification ────────────────────────────────────────────────────────────

def classify(utterance, speech_act):
    text = (utterance or "").strip()
    words = len(text.split())
    act = (speech_act or "").lower()
    if "?" in text:
        if words <= 12 and _BINARY_START.match(text.lstrip("\"'* ")):
            return "binary_question", words
        return "question", words
    if act in _CONFIRM_ACTS or words <= 5:
        return "confirm", words
    return "statement", words


def expects_reply(utterance, speech_act, kind):
    if kind in ("binary_question", "question"):
        return True
    return (speech_act or "").lower() in _REPLY_ACTS


def reply_window(kind, words):
    if kind in ("confirm", "binary_question"):
        return SIMPLE_WINDOW
    return max(MIN_COMPLEX_WINDOW, min(MAX_COMPLEX_WINDOW, 6 + int(words * 0.5)))


# ── conversation hook ─────────────────────────────────────────────────────────

def _managed(conv):
    return (conv.get("medium", "in_person") in ("in_person", "call")
            and len(conv.get("participants", [])) == 2)


def on_message(world, conv, speaker_id, utterance, speech_act, tick):
    """Called from brain/conversations.py::add_message() once per real message
    (after turn_owner has moved on): puts the ball with the other person."""
    if not _managed(conv):
        return
    old = conv.get("floor")
    attempts = 1
    if old and old.get("state") != "closed":
        if old.get("holder") == speaker_id:
            conv["accepted"] = True          # the other party answered: the conversation is on
        elif old.get("from") == speaker_id and old.get("expects_reply"):
            attempts = old.get("attempts", 1) + 1
    kind, words = classify(utterance, speech_act)
    reply = expects_reply(utterance, speech_act, kind)
    window = reply_window(kind, words)
    conv["floor"] = {
        "holder": conv.get("turn_owner"),
        "from": speaker_id,
        "kind": kind,
        "words": words,
        "expects_reply": reply,
        "state": "waiting" if reply else "open",
        "attempts": attempts,
        "said_tick": tick,
        "aware_by": tick + FLUSH_LAG + AWARE_TICKS,
        "window": window,
        "deadline": tick + FLUSH_LAG + window,
        "aware": False,
        "passes": 0,
    }


def blocks(world, conv, speaker_id):
    """True when speaker_id should hold their tongue: the ball is with someone
    else who is still within their time to respond."""
    f = conv.get("floor") if conv else None
    if not f or f.get("state") == "closed" or not _managed(conv):
        return False
    if world.get("tick", 0) - f.get("said_tick", 0) > STALE_TICKS:
        return False
    if f.get("holder") == speaker_id:
        return False
    if f.get("from") == speaker_id and f.get("state") in ("unnoticed", "unanswered"):
        return False                          # allowed to try again
    return True


def repeat_volume(world, speaker_id, target_id):
    """A line that repeats an unanswered one is said louder."""
    from brain.conversations import find_conversation
    conv = find_conversation(world, [speaker_id, target_id])
    f = conv.get("floor") if conv else None
    if f and f.get("from") == speaker_id and f.get("state") in ("unnoticed", "unanswered"):
        return "high"
    return None


# ── per-tick state machine ────────────────────────────────────────────────────

def _doing(c):
    act = (c or {}).get("activity") or {}
    t = act.get("type")
    if t:
        return "busy with " + str(t).replace("_", " ")
    if (c or {}).get("is_moving"):
        return "walking somewhere"
    return "nothing in particular"


def _name(c):
    return (c or {}).get("name") or "They"


def _end(world, conv, reason):
    from brain.conversations import _archive_conversation
    f = conv.get("floor")
    if f:
        f["state"] = "closed"
    conv["end_reason"] = reason
    conv["active"] = False
    _archive_conversation(world, conv)
    for pid in conv.get("participants", []):
        p = world.get("characters", {}).get(pid)
        if p:
            p["current_speech"] = None
            p["floor_status"] = None


def _ignored(world, conv, speaker, holder, f, heard):
    tick = world.get("tick", 0)
    _end(world, conv, "ignored")
    try:
        from brain.memory import store_memory
        what = "asked" if f.get("expects_reply") else "told"
        text = (f"{_name(holder)} heard me out and ignored me." if heard
                else f"I {what} {_name(holder)} something and they didn't even react.")
        store_memory(speaker, text, importance=0.5, tags=["ignored", "conversation"],
                     people=[holder["id"]], emotional_impact=-0.3, source="conversation", tick=tick)
    except Exception:
        pass
    from core.event_bus import emit
    emit("conversation_ignored", {
        "conv_id": conv.get("id"), "speaker_id": speaker["id"], "ignorer_id": holder["id"],
        "heard": heard, "attempts": f.get("attempts", 1), "kind": f.get("kind"),
        "utterance": ((conv.get("history") or [{}])[-1] or {}).get("utterance"),
    })


def _wake_speaker(world, speaker, holder, reason):
    from brain.cognition_scheduler import wake_character
    wake_character(speaker, world, reason, {"holder_name": _name(holder), "doing": _doing(holder)})


def tick(world):
    chars = world.get("characters", {})
    t = world.get("tick", 0)
    status = {}
    for conv in world.get("conversations", {}).values():
        f = conv.get("floor")
        if not conv.get("active") or not f or f.get("state") == "closed" or not _managed(conv):
            continue
        holder = chars.get(f.get("holder"))
        speaker = chars.get(f.get("from"))
        if not holder or not speaker or holder.get("alive") is False:
            _end(world, conv, "participant_gone")
            continue
        hid, sid = holder["id"], speaker["id"]
        began = _began(hid)
        aware = began > f["said_tick"]      # strictly after: a think already under way heard nothing
        thinking = aware and _is_thinking(hid)
        if aware and not f["aware"]:
            f["aware"] = True
        state = f["state"]

        if f["expects_reply"]:
            if state == "waiting":
                if aware:
                    f["state"] = state = "thinking" if thinking else "declined"
                elif t >= f["aware_by"]:
                    f["state"] = state = "unnoticed"
                    f["retry_until"] = t + RETRY_TICKS
                    _wake_speaker(world, speaker, holder, "floor_unnoticed")
            if state == "thinking" and (not thinking or t - began > THINK_CAP):
                f["state"] = state = "declined"
            if state == "declined":
                if f["attempts"] >= 2:
                    _ignored(world, conv, speaker, holder, f, heard=True)
                    continue
                f["state"] = state = "unanswered"
                f["retry_until"] = t + min(RETRY_TICKS, max(SIMPLE_WINDOW, f["window"]))
                _wake_speaker(world, speaker, holder, "floor_unanswered")
            if state in ("unnoticed", "unanswered") and t >= f.get("retry_until", t):
                _ignored(world, conv, speaker, holder, f, heard=(state == "unanswered"))
                continue
            if state in ("unnoticed", "unanswered") and f["attempts"] >= 2 and t >= f["aware_by"] and not aware:
                _ignored(world, conv, speaker, holder, f, heard=False)
                continue
        else:
            # Nothing was asked: the other person may add something, and if
            # they don't the ball passes on; once everyone has passed the
            # conversation simply lapses (not an insult).
            if thinking:
                f["deadline"] = max(f["deadline"], t + 1)
            elif t >= f["deadline"]:
                f["passes"] += 1
                if f["passes"] >= 2:
                    _end(world, conv, "lapsed")
                    continue
                f["from"], f["holder"] = hid, sid
                f["deadline"] = t + SIMPLE_WINDOW
                f["said_tick"] = t
                conv["turn_owner"] = sid
                f["aware"] = False

        # cues for display
        if f["state"] == "thinking":
            status[hid] = "thinking"
        if f["state"] in ("waiting", "thinking", "unnoticed", "unanswered"):
            status.setdefault(sid, "waiting_for_reply")

    for c in chars.values():
        cur = c.get("floor_status")
        new = status.get(c.get("id"))
        if cur != new:
            c["floor_status"] = new


# ── prompt context ────────────────────────────────────────────────────────────

def context_line(c, conv, world):
    """One sentence telling this character where the ball is."""
    f = conv.get("floor")
    if not f or f.get("state") == "closed" or not _managed(conv):
        return None
    chars = world.get("characters", {})
    holder = chars.get(f.get("holder"))
    speaker = chars.get(f.get("from"))
    if not holder or not speaker:
        return None
    lead = "You're both engaged in this conversation. " if conv.get("accepted") else ""
    me = c["id"]
    if f["holder"] == me:
        if f["expects_reply"]:
            extra = ""
            if f["attempts"] > 1:
                extra = f" They have already had to repeat themselves, and are getting impatient with you."
            short = " A short answer is enough." if f["kind"] in ("confirm", "binary_question") else ""
            return (f"{lead}{_name(speaker)} is waiting on YOU -- answer what they actually just said.{short}{extra} "
                    f"Ignoring someone who spoke to you is rude; if you don't want to talk, say so or leave.")
        if f.get("passes"):
            return (f"{lead}It has gone quiet between you and {_name(speaker)}; pick the conversation back up "
                    f"if there's more to say, or let it end.")
        return (f"{lead}{_name(speaker)} has finished speaking; if you have a comment, answer or follow-up, "
                f"now is the time -- otherwise there's no need to say anything.")
    if f["from"] == me:
        st = f["state"]
        who = _name(holder)
        if st == "waiting":
            return f"{lead}You just spoke to {who}; give them a moment to respond -- do not repeat or add to it yet."
        if st == "thinking":
            return f"{lead}{who} heard you and seems to be thinking it over. Wait for their answer."
        if st == "unnoticed":
            return (f"{lead}{who} hasn't reacted at all -- they're {_doing(holder)} and may not have heard you. "
                    f"You can say it again differently and louder, or call their name -- or let it go. "
                    f"Another try with no answer ends the conversation.")
        if st == "unanswered":
            return (f"{lead}{who} heard you but said nothing back (they're {_doing(holder)}). "
                    f"You can prompt them once more, or react to being brushed off.")
        return f"{lead}You've said your piece; see whether {who} adds anything before you speak again."
    return f"{lead}{_name(holder)} has the floor right now; it isn't your turn."
