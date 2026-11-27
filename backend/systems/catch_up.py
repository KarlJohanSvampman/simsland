"""
systems/catch_up.py -- checking in with people, and remembering what you talk about with each of them.

The user (2026-11-27): "whenever two sims haven't seen each other for a few hours or else once per day -- whenever they
see each other first time in a new day -- they should check in with them, ask how they are doing and what their plans
are, what they did yesterday or what they're doing this weekend. I also want a special conversation memory where we
store topics connected to different sims and add to this whenever a new topic comes up, so we can keep track of what
topics we discussed and pick one from there to get an update on."

Check-ins
    c["_talked"][other_id] = sim time they last spoke with each other (either way; set as each line is delivered).
    checkin_due(): someone they know, not spoken to yet today -- or not for CHECKIN_GAP_S. Then the conversation act
    for them (systems/conversation_acts.py) leans hard toward an INQUIRY that is a check-in: how they're doing, their
    plans, what they did yesterday / are doing this weekend (by the day of the week and the time), and news on one
    topic from before.

Topic memory
    c["talk_topics"][other_id] = [{topic, first_ts, last_ts, times, asked_ts}]   newest last, TOPICS_KEPT per person
    note_topic(): from the AI's reading of each finished conversation (its subject and topic tags --
    systems/conversation_archive.py::apply_tags) and from the topic each conversation act carried
    (systems/action_router.py). update_topic() picks the one to ask about: talked about a while ago (UPDATE_AFTER_S),
    not asked about lately; plans and events first.
"""

import re

CHECKIN_GAP_S = 4 * 3600          # "haven't seen each other for a few hours"
TOPICS_KEPT = 15
UPDATE_AFTER_S = 12 * 3600        # a topic is worth an update once it's half a day old
ASKED_COOLDOWN_S = 24 * 3600      # and not asked about again for a day
DAY = 86400

_PLANNY = re.compile(r"\b(plan|planning|weekend|trip|holiday|vacation|exam|test|interview|job|work|school|party|date|"
                     r"birthday|doctor|appointment|move|moving|project|match|game|wedding|visit|course|class)\w*", re.I)
_GENERIC = {"general", "smalltalk", "small talk", "chat", "chatting", "conversation", "something", "talk", ""}


def _now(world):
    from core.clock import now_ts
    return now_ts(world)


def _day(ts):
    return int(ts // DAY)


def knows(c, other):
    """Someone they'd check in with: family, housemates, or anyone they've got to know."""
    rel = (c.get("relationships") or {}).get(other.get("id")) or {}
    if rel.get("kinship") or (c.get("household_id") and c.get("household_id") == other.get("household_id")):
        return True
    return float(rel.get("familiarity", 0) or 0) >= 25 or "neighbour" in (rel.get("labels") or [])


def note_talk(c, other_id, world, now=None):
    c.setdefault("_talked", {})[other_id] = _now(world) if now is None else now


def checkin_due(c, other, world):
    """Why a check-in is due -- "first time today" / "a few hours since you last talked" -- or None."""
    if not knows(c, other):
        return None
    last = (c.get("_talked") or {}).get(other.get("id"))
    now = _now(world)
    if last is None:
        return "first time today"
    if _day(last) != _day(now):
        return "first time today"
    if now - last >= CHECKIN_GAP_S:
        return "a few hours since you last talked"
    return None


def _clean(topic):
    t = re.sub(r"\s+", " ", str(topic or "")).strip().strip(".").strip()
    return t[:80]


def note_topic(c, other_id, topic, world, now=None):
    """A topic came up with other_id: added, or its entry refreshed."""
    t = _clean(topic)
    if t.lower() in _GENERIC or len(t) < 3:
        return None
    now = _now(world) if now is None else now
    topics = c.setdefault("talk_topics", {}).setdefault(other_id, [])
    for e in topics:
        if e["topic"].lower() == t.lower():
            e["last_ts"], e["times"] = now, e.get("times", 1) + 1
            topics.remove(e)
            topics.append(e)
            return e
    e = {"topic": t, "first_ts": now, "last_ts": now, "times": 1, "asked_ts": None}
    topics.append(e)
    del topics[:-TOPICS_KEPT]
    return e


def recent_topics(c, other_id, n=3):
    return [e["topic"] for e in reversed((c.get("talk_topics") or {}).get(other_id) or [])][:n]


def update_topic(c, other_id, world, mark=False):
    """The topic to ask for news on: talked about a while ago, not asked about lately; plans and events first."""
    now = _now(world)
    best = None
    for e in (c.get("talk_topics") or {}).get(other_id) or []:
        if now - (e.get("last_ts") or now) < UPDATE_AFTER_S:
            continue
        if e.get("asked_ts") and now - e["asked_ts"] < ASKED_COOLDOWN_S:
            continue
        rank = (1 if _PLANNY.search(e["topic"]) else 0, e.get("times", 1), e.get("last_ts") or 0)
        if best is None or rank > best[0]:
            best = (rank, e)
    if not best:
        return None
    if mark:
        best[1]["asked_ts"] = now
    return best[1]["topic"]


def checkin_topic(c, other, world):
    """What a check-in asks about, by the day and the hour, plus news on one earlier topic."""
    cal = world.get("calendar") or {}
    weekday = str(cal.get("weekday") or "").lower()
    hour = int(cal.get("hour") or 12)
    parts = ["how they're doing"]
    if weekday in ("friday", "saturday") or (weekday == "thursday" and hour >= 17):
        parts.append("what they're doing this weekend")
    elif weekday in ("monday",) and hour < 14:
        parts.append("how their weekend was")
    elif hour < 12:
        parts.append("what they did yesterday and their plans for today")
    elif hour < 18:
        parts.append("how their day is going and what they have planned")
    else:
        parts.append("how their day was and what's on tomorrow")
    news = update_topic(c, other.get("id"), world)
    if news:
        parts.append(f"any news on {news}")
    return "checking in -- " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]


# ── fed from the conversation code ───────────────────────────────────────────────────────────────────────────────────

def on_line(world, speaker, listener, topic=None, act=None):
    """A line was delivered: they've talked now; the act's topic is remembered on both sides; a check-in's update
    topic is marked asked."""
    if not speaker or not listener:
        return
    now = _now(world)
    note_talk(speaker, listener["id"], world, now)
    note_talk(listener, speaker["id"], world, now)
    if topic and not str(topic).startswith("checking in"):
        note_topic(speaker, listener["id"], topic, world, now)
        note_topic(listener, speaker["id"], topic, world, now)
    if topic and "any news on " in str(topic):
        asked = str(topic).split("any news on ", 1)[1]
        for e in (speaker.get("talk_topics") or {}).get(listener["id"]) or []:
            if e["topic"].lower() == asked.lower():
                e["asked_ts"] = now


def on_conversation_read(world, entry):
    """The AI read a finished conversation: its subject and topic tags go into each pair's topic memory."""
    chars = world.get("characters") or {}
    people = [chars[p] for p in entry.get("participants") or [] if p in chars]
    found = [entry.get("subject")] + list(entry.get("topic_tags") or [])[:3]
    for a in people:
        for b in people:
            if a is b:
                continue
            for t in found:
                if t:
                    note_topic(a, b["id"], t, world)


def summary(c, world):
    """For the inspector / API: who they've talked with about what, newest first."""
    chars = world.get("characters") or {}
    return {(chars.get(oid) or {}).get("name", oid): [e["topic"] for e in reversed(ts)]
            for oid, ts in (c.get("talk_topics") or {}).items()}
