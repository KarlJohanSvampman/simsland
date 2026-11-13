"""
systems/conversation_outcome.py -- a conversation is about something, and ends once that is settled.

Live (2026-11-01): Kathleen asked Susan to play a dozen ways across seventeen conversations; when Susan finally said
"Yeah, yeah! I wanna play too!" nothing came of it, and the talk just went on (or died). Now:

  - The first line that asks something (a question, a request, an invitation -- conversation_floor.expects_reply) is the
    conversation's PURPOSE.
  - The other person's answer settles it: yes ("yeah!", "sure", "let's go"), no ("sorry, I can't", "not now") or later
    ("after dinner", "at 4", "in an hour", "maybe later"). That is the OUTCOME. The one who asked gets one line to close
    ("great, see you then!"), then the conversation ends as "resolved" -- after CLOSE_GRACE_TICKS at the latest.
  - Whatever happens, a conversation ends after MAX_LINES lines or MAX_TICKS sim-seconds ("timed_out"): no endless
    chatter, and no new lines piled onto one that has run its course. Ending this way is not an insult (unlike
    "ignored" in conversation_floor.py).

An outcome about playing (the asker wants to play with the other, or the question is about playing) also settles the
asker's play_with_friend intention: no -> dropped; later -> both children get a plan (c["_play_plans"]) that
systems/kids_play.py turns into an urge to play when the time comes; yes -> nothing to do, they are together and
kids_play.settle_play_urges() sees them play.
"""

import re

MAX_LINES = 6                 # a conversation longer than this ends, settled or not
MAX_TICKS = 240               # 4 sim-minutes
NO_REPLY_TICKS = 60           # a minute without a line: nobody is answering any more
EARSHOT_TILES = 6.0           # in person, further apart than this and they have parted
CLOSE_GRACE_TICKS = 20        # after the answer, the asker's closing line (or this long) and it's over
LATER_DEFAULT_MINUTES = 60    # "later" with no time given

_FILLERS = {"hey", "hi", "hello", "oh", "um", "uh", "well", "so", "hmm", "ah", "and", "but"}

_DECLINE = re.compile(r"^(?:no\b|nope|nah|sorry\b|i can'?t|i cannot|i can not|not now|not today|not right now|"
                      r"maybe another|maybe not|i don'?t (?:want|feel)|i'?m busy|i am busy|i have to|i'?d rather not)")
_ACCEPT = re.compile(r"^(?:yeah|yes|yep|yup|yay|sure|okay|ok\b|of course|definitely|totally|absolutely|alright|"
                     r"all right|let'?s|sounds (?:good|great|fun|awesome|like fun)|i'?d love|i would love|why not|"
                     r"great idea|good idea|cool\b|deal\b|count me in|i'?m in\b|me too|i wanna\b.*\btoo\b)")
_ACCEPT_ACTS = {"accept", "agree", "confirm"}
_DECLINE_ACTS = {"decline", "refuse", "reject"}
_PLAY = re.compile(r"\b(?:play|playing|game|games|hang out|hangout)\b", re.I)

# A time in the answer -> minutes from now (or a clock time)
_CLOCK = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|o'?clock)\b|\bat\s+(\d{1,2})(?::(\d{2}))?\b", re.I)
_IN = re.compile(r"\bin\s+(?:(\d+)|an?|half an?)\s*(minute|min|hour|hr)s?\b", re.I)
_PHRASES = (
    (re.compile(r"\btomorrow\b", re.I), ("tomorrow", 10 * 60)),
    (re.compile(r"\b(?:after|before) dinner\b|\btonight\b|\bthis evening\b", re.I), ("clock", 19 * 60)),
    (re.compile(r"\bafter lunch\b", re.I), ("clock", 13 * 60 + 30)),
    (re.compile(r"\bafter school\b", re.I), ("clock", 16 * 60 + 30)),
    (re.compile(r"\bthis afternoon\b", re.I), ("clock", 15 * 60)),
    (re.compile(r"\bthis weekend\b|\bsometime this week\b|\bsome ?time\b", re.I), ("tomorrow", 11 * 60)),
    (re.compile(r"\bin a (?:bit|while|minute|sec(?:ond)?)\b|\bsoon\b", re.I), ("in", 15)),
    (re.compile(r"\blater\b|\bafterwards?\b", re.I), ("in", LATER_DEFAULT_MINUTES)),
)


# ── reading an answer ─────────────────────────────────────────────────────────

def _core(utterance, names):
    """The answer without its run-up: 'Hey, Kathleen, yeah!' -> 'yeah!'."""
    words = re.findall(r"[A-Za-z0-9':]+|[^\sA-Za-z0-9':]", (utterance or "").lower())
    i = 0
    while i < len(words) and (words[i] in _FILLERS or words[i] in names or not re.match(r"[a-z0-9']", words[i])):
        i += 1
    return " ".join(words[i:]).replace(" ,", ",").replace(" !", "!").replace(" .", ".").replace(" ?", "?")


def _when(text, world):
    """The tick something later was agreed for, or None if the answer names no time."""
    cal = world.get("calendar") or {}
    tick = world.get("tick", 0)
    now_min = cal.get("minute_of_day")
    if now_min is None and cal.get("hour") is not None:
        now_min = cal["hour"] * 60 + (cal.get("minute") or 0)

    def at_clock(minute_of_day):
        if now_min is None:
            return tick + LATER_DEFAULT_MINUTES * 60
        delta = minute_of_day - now_min
        if delta <= 0:
            delta += 24 * 60
        return tick + delta * 60

    m = _IN.search(text)
    if m:
        n = int(m.group(1)) if m.group(1) else (30 if "half" in m.group(0).lower() else 1)
        unit = 60 if m.group(2).lower().startswith("h") else 1
        return tick + n * unit * 60
    m = _CLOCK.search(text)
    if m:
        h = int(m.group(1) or m.group(4))
        mi = int(m.group(2) or m.group(5) or 0)
        suffix = (m.group(3) or "").lower()
        if suffix == "pm" and h < 12:
            h += 12
        elif not suffix.startswith(("am", "pm")) and 1 <= h <= 7:
            h += 12                                    # "at 4" means the afternoon
        if 0 <= h < 24 and 0 <= mi < 60:
            return at_clock(h * 60 + mi)
    for pattern, (kind, value) in _PHRASES:
        if pattern.search(text):
            if kind == "in":
                return tick + value * 60
            if kind == "clock":
                return at_clock(value)
            if now_min is None:
                return tick + 24 * 3600
            return tick + (24 * 60 - now_min + value) * 60
    return None


def read_answer(utterance, speech_act, world, names=()):
    """(verdict, at_tick): verdict "yes" | "no" | "later" | None (not an answer to the question)."""
    text = _core(utterance, set(names))
    act = (speech_act or "").lower()
    if re.match(r"^no (?:problem|worries)\b", text):
        return "yes", None                             # "No problem, let's go!" is a yes
    if act in _DECLINE_ACTS or _DECLINE.match(text):
        when = _when(text, world) if re.search(r"\blater\b|\btomorrow\b|\bafter\b|\bat \d|\bin (?:an?|\d)", text) else None
        return ("later", when) if when else ("no", None)
    if act in _ACCEPT_ACTS or _ACCEPT.match(text):
        when = _when(text, world)           # "Yeah! But first, can I get some water?" names no time: a yes for now
        return ("later", when) if when else ("yes", None)
    if re.match(r"^(?:maybe later|later|another time|some other time|in (?:an?|half|\d)|at \d|after |tomorrow|tonight)\b", text):
        return "later", _when(text, world) or world.get("tick", 0) + LATER_DEFAULT_MINUTES * 60
    return None, None


# ── the hooks ─────────────────────────────────────────────────────────────────

def _names(world, conv):
    out = set()
    for pid in conv.get("participants") or []:
        c = (world.get("characters") or {}).get(pid) or {}
        for n in (c.get("first_name"), (c.get("name") or "").split(" ")[0]):
            if n:
                out.add(n.lower())
    return out


def on_message(world, conv, speaker_id, utterance, speech_act, tick):
    """After each line (brain/conversations.py::add_message)."""
    from systems.conversation_floor import classify, expects_reply
    if len(conv.get("history") or []) <= 1:
        record_gaps(world, conv)
    purpose = conv.get("purpose")
    kind, _ = classify(utterance, speech_act)
    if conv.get("outcome"):
        if purpose and speaker_id == purpose.get("by"):
            if not expects_reply(utterance, speech_act, kind):
                end(world, conv, "resolved")       # the closing line after the answer: that's the conversation done
                return
            # "Great! What game?" -- not a closing line but the next question. Ending here left it hanging: the answer to
            # it opened a new conversation, with that answer as its purpose. It becomes this conversation's purpose.
            conv.pop("outcome", None)
            conv.pop("resolved_tick", None)
            purpose = conv["purpose"] = None
        else:
            return
    if purpose is None:
        if expects_reply(utterance, speech_act, kind):
            asker = (world.get("characters") or {}).get(speaker_id) or {}
            other = next((p for p in conv.get("participants") or [] if p != speaker_id), None)
            wants_play = any(i.get("type") == "play_with_friend" and i.get("target_id") == other
                             for i in asker.get("active_intentions") or [])
            conv["purpose"] = {"by": speaker_id, "to": other, "line": utterance, "tick": tick,
                               "about_play": bool(wants_play or _PLAY.search(utterance or ""))}
        return
    if speaker_id == purpose.get("by"):
        return                                         # still the asker: no answer yet
    verdict, at_tick = read_answer(utterance, speech_act, world, _names(world, conv))
    if not verdict:
        return
    conv["outcome"] = {"verdict": verdict, "at_tick": at_tick, "by": speaker_id, "line": utterance, "tick": tick}
    conv["resolved_tick"] = tick
    _apply(world, conv)


def tick(world):
    """End what is settled or has run too long -- over every conversation (old callers, tests)."""
    tick_conversations(world, list((world.get("conversations") or {}).values()))


def tick_conversations(world, convs):
    """End what is settled or has run too long, among `convs` (the floor loop passes its live conversations)."""
    t = world.get("tick", 0)
    for conv in convs:
        if not conv.get("active") or conv.get("medium", "in_person") not in ("in_person", "call"):
            continue
        if conv.get("outcome") and t >= conv.get("resolved_tick", t) + CLOSE_GRACE_TICKS:
            end(world, conv, "resolved")
        elif _someone_left(world, conv):
            end(world, conv, "left")
        elif t - (conv.get("last_update") or t) >= NO_REPLY_TICKS and conv.get("history"):
            end(world, conv, "no_response")
        elif len(conv.get("history") or []) >= MAX_LINES or t - (conv.get("started_at") or t) >= MAX_TICKS:
            end(world, conv, "timed_out")


def record_gaps(world, conv):
    """How far apart everyone was when the conversation started (taken at its first line)."""
    start = conv.setdefault("_start_gaps", {})
    chars = world.get("characters") or {}
    people = [chars.get(p) for p in conv.get("participants") or [] if chars.get(p)]
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            key = f"{a.get('id')}|{b.get('id')}"
            if key not in start:
                start[key] = {"gap": abs(a.get("x", 0) - b.get("x", 0)) + abs(a.get("y", 0) - b.get("y", 0)),
                              "same_building": (a.get("_in_building") or None) == (b.get("_in_building") or None)}
    return start


def _someone_left(world, conv):
    """One conversation is one sitting: once someone has gone (out of earshot, another building, off-grid, asleep,
    or -- on the phone -- off it) it is over, not paused to pick up later."""
    chars = world.get("characters") or {}
    people = [chars.get(p) for p in conv.get("participants") or []]
    if any(p is None or p.get("off_grid") or p.get("alive") is False
           or (p.get("activity") or {}).get("type") == "sleep" for p in people):
        return True
    if conv.get("medium", "in_person") != "in_person":
        return False
    # Measured against how far apart they were when it started: a talk called across the house (or begun from the
    # doorway) isn't over the moment it starts -- someone has to actually walk off. Ending those at once made every
    # line its own conversation.
    start = record_gaps(world, conv)
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            key = f"{a.get('id')}|{b.get('id')}"
            gap = abs(a.get("x", 0) - b.get("x", 0)) + abs(a.get("y", 0) - b.get("y", 0))
            where = [(a.get("_in_building") or None), (b.get("_in_building") or None)]
            first = start.get(key) or {"gap": gap, "same_building": where[0] == where[1]}
            if gap > max(EARSHOT_TILES, first["gap"] + 3):
                return True
            if first["same_building"] and where[0] != where[1]:
                return True
    return False


def end(world, conv, reason):
    """Close the conversation (conversation_floor._end) and let its people get on with something else."""
    from systems.conversation_floor import _end
    _end(world, conv, reason)
    chars = world.get("characters") or {}
    participants = conv.get("participants") or []
    for pid in participants:
        c = chars.get(pid)
        act = (c or {}).get("activity") or {}
        if c and act.get("type") in ("socialize", "speak") and act.get("target_id") in participants:
            c["activity"] = None
    if reason == "timed_out":
        for pid in participants:
            c = chars.get(pid)
            if c:
                from brain.cognition_scheduler import wake_character
                wake_character(c, world, "activity_finished", {"activity": "conversation"})


# ── what an answer about playing does ─────────────────────────────────────────

def _clock_text(world, at_tick):
    cal = world.get("calendar") or {}
    now_min = cal.get("minute_of_day")
    if now_min is None:
        return "later"
    minutes = (now_min + (at_tick - world.get("tick", 0)) // 60)
    day = "tomorrow " if minutes >= 24 * 60 else ""
    minutes %= 24 * 60
    return f"{day}at {minutes // 60:02d}:{minutes % 60:02d}"


def _apply(world, conv):
    purpose, outcome = conv.get("purpose") or {}, conv.get("outcome") or {}
    if not purpose.get("about_play"):
        return
    from brain.memory import store_memory
    chars = world.get("characters") or {}
    asker, other = chars.get(purpose.get("by")), chars.get(purpose.get("to"))
    if not asker or not other:
        return
    tick = world.get("tick", 0)
    verdict = outcome.get("verdict")
    if verdict == "no":
        asker["active_intentions"] = [i for i in asker.get("active_intentions") or []
                                      if not (i.get("type") == "play_with_friend" and i.get("target_id") == other["id"])]
        store_memory(asker, f"{other.get('name', 'They')} didn't want to play right now.", importance=0.3,
                     tags=["play"], tick=tick, source="internal", people=[other["id"]])
    elif verdict == "later" and outcome.get("at_tick"):
        when = _clock_text(world, outcome["at_tick"])
        for a, b in ((asker, other), (other, asker)):
            a["active_intentions"] = [i for i in a.get("active_intentions") or []
                                      if not (i.get("type") == "play_with_friend" and i.get("target_id") == b["id"])]
            plans = [p for p in a.get("_play_plans") or [] if p.get("with") != b["id"]]
            plans.append({"with": b["id"], "at_tick": outcome["at_tick"], "agreed_tick": tick})
            a["_play_plans"] = plans
            store_memory(a, f"{b.get('name', 'They')} and I agreed to play {when}.", importance=0.4,
                         tags=["play", "plan"], tick=tick, source="internal", people=[b["id"]])
