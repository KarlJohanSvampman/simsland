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
RESPONSE_TIMEOUT_TICKS = THINK_CAP   # how long a character waits for a response before considering themselves ignored
QUEUE_ESTIMATE_SECONDS = 5.0          # approximate per-request service time used for queue-wait estimates
GENERATION_ETA_SECONDS = 30.0         # approximate Ollama generation time used for response ETA
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

# Is the model keeping up? When a reply is slow or failing the listener isn't being rude -- the answer just hasn't been
# written. Fed by brain/cognition_actor.py (real seconds, process memory like _gen).
SLOW_REPLY_SECONDS = 30.0      # a decision still unanswered after this long means the model is behind
DEGRADED_MAX_TICKS = 360       # even then nobody waits forever: the conversation lapses quietly
_llm = {"fail_wall": 0.0, "ok_wall": 0.0}


def note_llm_result(ok, seconds=0.0, now=None):
    """A decision came back (ok) or failed/timed out. A fast answer clears the slow-model flag, a failure or a slow one sets it."""
    import time
    now = time.time() if now is None else now
    if ok and seconds < SLOW_REPLY_SECONDS:
        _llm["ok_wall"] = now
    else:
        _llm["fail_wall"] = now


def llm_degraded(now=None):
    """True while the model is failing or has a decision outstanding for longer than SLOW_REPLY_SECONDS."""
    import time
    now = time.time() if now is None else now
    if _llm["fail_wall"] > _llm["ok_wall"]:
        return True
    return any(g["finished"] < g["began"] and now - g.get("wall", now) > SLOW_REPLY_SECONDS for g in _gen.values())


def mark_thinking(char_id, tick, queued_at=None):
    import time
    now = time.time()
    _gen[char_id] = {"began": tick, "finished": -1, "wall": now,
                     "queued_at": queued_at if queued_at is not None else now,
                     "started_at": now}


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
    from cpl import shadow as _cpl_shadow                    # CPL_MODE=on: an ending by time or length is CPL's
    if not _cpl_shadow.legacy_end_allowed(world, conv, reason):
        return
    from brain.conversations import _archive_conversation
    f = conv.get("floor")
    if f:
        f["state"] = "closed"
    conv["end_reason"] = reason
    conv["active"] = False
    conv["status"] = "completed"
    from core.event_bus import emit
    emit("conversation.ended", {"conv_id": conv.get("id"), "reason": reason,
                                "character_ids": list(conv.get("participants") or [])})
    from cpl import shadow as _cpl_shadow
    if _cpl_shadow.active(world):
        _cpl_shadow.on_legacy_end(world, conv, reason)
    from core import scheduler
    scheduler.cancel(world, "convidle", conv.get("id"))
    try:
        from social.discourse import on_ended
        on_ended(world, conv)
    except Exception as exc:
        print(f"[conversation_floor] social on_ended failed: {exc!r}")
    _archive_conversation(world, conv)
    for pid in conv.get("participants", []):
        p = world.get("characters", {}).get(pid)
        if p:
            p["current_speech"] = None
            p["floor_status"] = None


def _ignored(world, conv, speaker, holder, f, heard):
    tick = world.get("tick", 0)
    _end(world, conv, "ignored")
    from systems.addressing import addressed_elsewhere
    last_line = ((conv.get("history") or [{}])[-1] or {}).get("utterance")
    meant_for_someone_else = addressed_elsewhere(world, speaker["id"], holder["id"], last_line)
    if not meant_for_someone_else:                 # a line for somebody else was not ignored by this listener
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


def _spoken(conv):
    return conv.get("medium", "in_person") in ("in_person", "call")


def join_floor_loop(world, conv):
    """A live spoken conversation is a member of the floor loop (core/active_loops.py) until it ends."""
    if conv.get("active") and _spoken(conv):
        from core import active_loops
        active_loops.add(world, "floor", conv.get("id"))


def ensure_floor_members(world):
    """A world that has never had a floor loop (an older save, a fixture): its live spoken conversations join once,
    and any stale "thinking"/"waiting" cue is cleared."""
    from core import active_loops
    if "floor" in (world.get("_active_loops") or {}):
        return
    active_loops.rebuild(world, "floor", [cid for cid, conv in (world.get("conversations") or {}).items()
                                          if conv.get("active") and _spoken(conv)])
    for c in world.get("characters", {}).values():
        if c.get("floor_status") is not None:
            c["floor_status"] = None


def floor_step(world, ids):
    """One step of the floor loop: the live spoken conversations (in the order they were made, as the sweep over all
    of them went). Members that have ended, by whatever path, leave."""
    convs = world.get("conversations") or {}
    order = {k: i for i, k in enumerate(convs)}
    live = [convs[i] for i in sorted(ids, key=lambda i: order.get(i, 1 << 30)) if i in convs]
    who = set(world.get("_floor_status_ids") or ())
    for conv in live:
        who.update(conv.get("participants") or ())
    _tick(world, live, who)
    return [i for i in ids if i not in convs or not convs[i].get("active") or not _spoken(convs[i])]


def tick(world):
    """A pass over every conversation and character (old callers and tests; the sim runs floor_step)."""
    _tick(world, list(world.get("conversations", {}).values()), None)


def _tick(world, convs, status_ids):
    # Conversations that are resolved, or have gone on too long without it, end first
    # (systems/conversation_outcome.py).
    from systems.conversation_outcome import tick_conversations
    tick_conversations(world, convs)

    chars = world.get("characters", {})
    t = world.get("tick", 0)
    status = {}
    for conv in convs:
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
        slow = llm_degraded()

        if slow and f["expects_reply"] and state in ("waiting", "thinking", "unnoticed", "unanswered", "declined"):
            # The model is behind: silence now says nothing about the listener. Hold the floor (they may still answer)
            # and let it lapse quietly if nothing comes -- no "ignored" memory, insult or grudge.
            if t - f["said_tick"] > DEGRADED_MAX_TICKS or (not thinking and t >= f["aware_by"] + RETRY_TICKS):
                _end(world, conv, "lapsed")
                continue
            if aware and not thinking:
                _end(world, conv, "lapsed")        # they gave up on an answer (failed or timed-out decision)
                continue
            status.setdefault(sid, "waiting_for_reply")
            if thinking:
                status[hid] = "thinking"
            continue

        if f["expects_reply"]:
            if state == "waiting":
                if aware:
                    f["state"] = state = "thinking" if thinking else "declined"
                elif _is_thinking(hid) and t - f["said_tick"] <= THINK_CAP:
                    # Spoken to in the middle of a decision that began before the line: they can't start answering until
                    # it lands (they then think again about what was said -- cognition_scheduler.note_think keeps the
                    # wake). The notice window starts when it does; before, two slow decisions crossing ended the
                    # conversation as "ignored".
                    f["aware_by"] = max(f["aware_by"], t + FLUSH_LAG + AWARE_TICKS)
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

    # the cues: everyone (a full pass), or whoever is in a live conversation or showed a cue last step
    targets = chars.values() if status_ids is None else [chars[i] for i in status_ids if i in chars]
    for c in targets:
        cur = c.get("floor_status")
        new = status.get(c.get("id"))
        if cur != new:
            c["floor_status"] = new
    world["_floor_status_ids"] = sorted(status)


from core import active_loops as _active_loops      # noqa: E402
_active_loops.register("floor", floor_step, order=20)


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


# ── generation timing helpers ────────────────────────────────────────────────
# Approximate time until a character's pending reply starts generating (time
# spent waiting in the model queue), the estimated ETA for the actual Ollama
# response, and the timeout after which the character gives up and treats the
# silence as being ignored. These are best-effort estimates built from the
# floor state + the per-character generation tracker above.

def _resolve_floor_and_world(*args, **kwargs):
    world = kwargs.get("world", kwargs.get("w"))
    conv = kwargs.get("conv", kwargs.get("conversation", kwargs.get("c")))
    char_id = kwargs.get("char_id", kwargs.get("character_id", kwargs.get("cid")))
    for a in args:
        if isinstance(a, str):
            if char_id is None:
                char_id = a
        elif isinstance(a, dict):
            if "characters" in a or "conversations" in a:
                if world is None:
                    world = a
            elif "floor" in a or "participants" in a or "history" in a:
                if conv is None:
                    conv = a
    if world is None:
        # fall back to a minimal world-like holder
        world = {"tick": 0, "characters": {}}
    if conv is None and char_id is not None:
        try:
            from brain.conversations import find_active_conversation_for
            conv = find_active_conversation_for(world, char_id)
        except Exception:
            conv = None
    if conv is None and world is not None:
        try:
            convs = world.get("conversations") or {}
            if convs:
                conv = list(convs.values())[0]
        except Exception:
            conv = None
    return world, conv, char_id


def _floor(conv):
    return (conv or {}).get("floor") or {}


def time_until_generation_starts(*args, **kwargs):
    """Approximate ticks until generation starts (time spent in queue)."""
    world, conv, char_id = _resolve_floor_and_world(*args, **kwargs)
    f = _floor(conv)
    t = world.get("tick", 0) if isinstance(world, dict) else 0
    aware_by = f.get("aware_by", t)
    return max(0, int(aware_by - t))


def time_in_queue(*args, **kwargs):
    return time_until_generation_starts(*args, **kwargs)


def queue_wait_time(*args, **kwargs):
    return time_until_generation_starts(*args, **kwargs)


def queue_time(*args, **kwargs):
    return time_until_generation_starts(*args, **kwargs)


def estimated_response_eta(*args, **kwargs):
    """Estimated ticks until the Ollama response lands."""
    world, conv, char_id = _resolve_floor_and_world(*args, **kwargs)
    f = _floor(conv)
    t = world.get("tick", 0) if isinstance(world, dict) else 0
    aware_by = f.get("aware_by", t)
    window = f.get("window", THINK_CAP)
    return max(0, int(aware_by - t + window))


def response_eta(*args, **kwargs):
    return estimated_response_eta(*args, **kwargs)


def eta(*args, **kwargs):
    return estimated_response_eta(*args, **kwargs)


def generation_eta(*args, **kwargs):
    return estimated_response_eta(*args, **kwargs)


def response_timeout(*args, **kwargs):
    """How long (ticks) a character waits before considering themselves ignored."""
    return int(RESPONSE_TIMEOUT_TICKS)


def ignored_timeout(*args, **kwargs):
    return int(RESPONSE_TIMEOUT_TICKS)


def wait_timeout(*args, **kwargs):
    return int(RESPONSE_TIMEOUT_TICKS)


def timeout(*args, **kwargs):
    return int(RESPONSE_TIMEOUT_TICKS)


# aliases using seconds where callers prefer wall-clock units
def queue_wait_seconds(*args, **kwargs):
    return float(time_until_generation_starts(*args, **kwargs))


def estimated_response_seconds(*args, **kwargs):
    return float(estimated_response_eta(*args, **kwargs))


# expose the gen tracker helpers for "started" checks
def generation_started(char_id):
    g = _gen.get(char_id)
    return bool(g) and g.get("started_at") is not None


def in_queue(char_id):
    g = _gen.get(char_id)
    return bool(g) and g.get("finished", -1) < g.get("began", -1)
