"""
systems/conversation_loops.py -- conversations that go in circles: saying the same thing again, agreeing and then
agreeing again (the user, 2026-11-28: "watch for conversation where both participants, or even just the one, are
saying sort of the same thing and then saying it again as if to confirm").

Live (2026-11-28): 13 of 18 recent conversations of 3+ lines had a line that restated one of the last few -- "clean it
up together, like we said", "I think we can work with that", "let's stick to what we agreed" -- most of them about the
same thing (the mess), because the conversation act (systems/conversation_acts.py) kept choosing the strongest
grievance as the topic, turn after turn, even once it had been agreed.

  * echo: a line whose words mostly repeat one of the last ECHO_LOOKBACK lines (either person's). Counted on the
    conversation (conv["echo_count"]); the speaker's next prompt says it's going in circles; at ECHO_STOP the
    conversation ends ("going_in_circles").
  * settled: one of them offered something (a compromise, a deal, a suggestion, a request) and the other agreed --
    conv["settled_topics"][topic]. The acts drop that topic for the rest of the conversation.
  * conv["topics_here"]: the topics this conversation has been about (the acts don't count a topic as rehashed while
    it is still the one being talked about).

Sooner (the user, 2026-11-28: "can we prevent circular conversation before it writes 19 lines?"): the 22 conversations
ended as going in circles ran 4-19 lines, most of them one "compromise" after another about the chores, each a
paraphrase rather than a repeat. So, as well as the echoes (now ECHO_STOP=2):
  * one topic for line after line (conv["topic_streak"]): at TOPIC_NUDGE lines the speaker is told to land on one
    concrete thing or drop it; at TOPIC_STOP the conversation ends as going in circles.
  * going back to a topic already agreed in this conversation counts as an echo.
  * once something is agreed and nothing new comes up, the conversation ends SETTLED_TAIL lines later ("agreed") --
    a goodbye fits in that, another round of "so we agree" doesn't.
"""

import re

ECHO_SIM = 0.5
ECHO_LOOKBACK = 4
ECHO_STOP = 2
TOPIC_NUDGE = 4
TOPIC_STOP = 6
SETTLED_TAIL = 2
OFFER_ACTS = {"compromise", "negotiate", "suggest", "request"}

_AGREE = re.compile(
    r"\b(yes|yeah|yep|ok(ay)?|sure|deal|agreed|fine|alright|all right|sounds (good|great|like a plan)|that works|"
    r"let'?s do (it|that)|works for me|i can (do|live with) that|you'?re right|good idea|great idea|i'?m in)\b", re.I)
_SHORT = {"that", "this", "with", "have", "just", "what", "your", "about", "would", "there", "their", "they", "them",
          "then", "were", "been", "will", "from", "when", "want", "know", "think", "really", "maybe", "because",
          "could", "should", "going", "still", "also", "something"}


_BUT = re.compile(r"\b(but|though|however|instead|what if|how about|or maybe|rather)\b", re.I)


def agrees(utterance):
    """A yes to what was offered: agreement up front, and no counter-offer straight after it. "Okay, but what if ..."
    and another compromise are not a yes (live: compromise answered with compromise had counted as settled)."""
    head = " ".join(str(utterance or "").split()[:8])
    return bool(_AGREE.search(head)) and not _BUT.search(head)


def _words(text):
    """Content words; a name said to someone at the start ("Daniel, ...") is left out -- it's in every line."""
    t = re.sub(r"^\s*[A-Z][a-z]+,\s*", "", str(text or ""))
    return {_stem(w) for w in re.sub(r"[^a-z' ]", " ", t.lower()).split() if len(w) > 3 and w not in _SHORT}


def _stem(w):
    """clean / cleaning / cleaned, agree / agreed / agreement: one word."""
    w = w.strip("'")
    for suf in ("ment", "ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)].rstrip("e")
    return w.rstrip("e") if len(w) > 4 else w


def similarity(a, b):
    """How much of the shorter line the other repeats (content words), 0-1; 0 for lines too short to judge."""
    wa, wb = _words(a), _words(b)
    if len(wa) < 4 or len(wb) < 4:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def echo_of(utterance, history):
    """The strongest repeat among the last ECHO_LOOKBACK lines: (similarity, line) or (0, None)."""
    best, line = 0.0, None
    for h in (history or [])[-ECHO_LOOKBACK:]:
        s = similarity(utterance, h.get("utterance"))
        if s > best:
            best, line = s, h
    return best, line


def _match(topic, known):
    """A topic and one already noted are the same (case and a little wording aside)."""
    a, b = _words(topic) or {str(topic or "").lower()}, _words(known) or {str(known or "").lower()}
    return bool(a & b) and len(a & b) / min(len(a), len(b)) >= 0.5


def settled(conv, topic):
    return bool(topic) and any(_match(topic, t) for t in (conv or {}).get("settled_topics") or {})


def discussed_here(conv, topic):
    return bool(topic) and any(_match(topic, t) for t in (conv or {}).get("topics_here") or [])


def going_in_circles(conv):
    return bool((conv or {}).get("echo_count")) and (conv.get("history") or [{}])[-1].get("echo")


def _stats(world):
    st = world.setdefault("_conv_loops", {"echoes": 0, "ended": 0, "settled": 0})
    for k in ("ended_topic", "ended_agreed"):
        st.setdefault(k, 0)
    return st


def _end(world, conv, reason, stat):
    _stats(world)[stat] += 1
    try:
        from systems.conversation_outcome import end
        end(world, conv, reason)
        return True
    except Exception as exc:                              # noqa: BLE001
        print(f"[conversation_loops] could not end: {exc!r}")
        return False


def on_line(world, conv, speaker_id, utterance, act=None, topic=None):
    """A line was added to conv (the last history entry): echo? agreement on an offer? the topic noted. Ends the
    conversation when it's circling (ECHO_STOP echoes, TOPIC_STOP lines on one topic) or when it's agreed and done
    (SETTLED_TAIL lines later). Returns "echo" / "settled" / "ended" / None."""
    hist = conv.get("history") or []
    if not hist:
        return None
    line, before = hist[-1], hist[:-1]
    tick = world.get("tick", 0)
    rehash = bool(topic) and settled(conv, topic)          # back to something already agreed here
    new_topic = False
    if topic:
        here = conv.setdefault("topics_here", [])
        if not any(_match(topic, t) for t in here):
            here.append(str(topic)[:80])
            new_topic = True
        streak = conv.get("topic_streak") or {}
        if streak.get("topic") and _match(topic, streak["topic"]):
            streak["lines"] = streak.get("lines", 0) + 1
        else:
            streak = {"topic": str(topic)[:80], "lines": 1}
        conv["topic_streak"] = streak
    result = None
    # agreed to what the other offered: that's settled
    prev = next((h for h in reversed(before) if h.get("speaker") != speaker_id), None)
    if prev and prev.get("conv_act") in OFFER_ACTS and agrees(utterance):
        t = prev.get("conv_topic") or topic
        if t and not settled(conv, t):
            conv.setdefault("settled_topics", {})[str(t)[:80]] = tick
            conv["settled_tail"] = 0
            _stats(world)["settled"] += 1
            result = "settled"
    if result != "settled" and conv.get("settled_topics"):
        if new_topic and not rehash:
            conv.pop("settled_tail", None)                 # moved on to something new
        elif "settled_tail" in conv:
            conv["settled_tail"] += 1
    sim, _ = echo_of(utterance, before)
    if sim >= ECHO_SIM or rehash:
        line["echo"] = round(sim, 2) if sim >= ECHO_SIM else "rehash"
        conv["echo_count"] = conv.get("echo_count", 0) + 1
        _stats(world)["echoes"] += 1
        if conv["echo_count"] >= ECHO_STOP and _end(world, conv, "going_in_circles", "ended"):
            return "ended"
        result = result or "echo"
    if (conv.get("topic_streak") or {}).get("lines", 0) >= TOPIC_STOP and not conv.get("settled_topics"):
        if _end(world, conv, "going_in_circles", "ended_topic"):
            return "ended"
    if conv.get("settled_tail", 0) >= SETTLED_TAIL and _end(world, conv, "agreed", "ended_agreed"):
        return "ended"
    return result


def prompt_line(conv, settled_topics=None):
    """What the speaker is told when this conversation is circling or something is settled."""
    out = []
    conv = conv or {}
    if going_in_circles(conv):
        out.append("This conversation is going in circles -- that was already said. Don't repeat it or confirm it "
                   "again: say something new, or wrap the conversation up.")
    streak = conv.get("topic_streak") or {}
    if streak.get("lines", 0) >= TOPIC_NUDGE and not conv.get("settled_topics"):
        out.append(f"You've gone back and forth about {streak['topic']} for {streak['lines']} lines. Land on one "
                   f"concrete thing now (who does what, when) and say yes to it -- or drop it and talk about something else.")
    st = list((conv.get("settled_topics") or {}).keys())
    if st:
        out.append(f"Already agreed: {'; '.join(st[-3:])}. Don't go over it again -- wrap the conversation up "
                   f"(a quick goodbye is fine) or move on to something new.")
    return out
