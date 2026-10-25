"""
systems/memory_acknowledgement.py -- "I remember you" (docs/relationship_impact_plan.md, section 9).

Bringing up something you remember about a person -- their dog's name, the thing they were nervous about last week -- is a
small kindness. While a character is in a conversation, the prompt lists a few memories that involve the other person, each
with its id. If the character's reply draws on one, the model lists the ids on a `USES:` line. The ids are then checked, and
if they hold up, the line goes into the relationship ledger as a `personal_acknowledgement` (positive) with `memory_refs`,
and the pair panel shows which memories were drawn on.

Checks, in order -- the model is never taken at its word:
  1. the id must be one of the speaker's own memories, and the listener must be among the people it is about;
  2. it must be a kind of memory that is fit to bring up (not a grudge, a rumor, something heard about them, a secret);
  3. the line must actually have something of it in it (a shared word of 4+ letters, or a name from the memory);
  4. the line is not meant to hurt or deceive (those are other kinds, and using a memory to wound is not kindness);
  5. the pair has not had one in the last COOLDOWN_TICKS, so it can't be farmed.
Magnitude grows with how much the memory mattered (3 to 8).
"""

import re

HOUR = 3600
COOLDOWN_TICKS = HOUR // 2
MAX_OFFERED = 4
MAX_REFS = 3
MIN_IMPORTANCE = 0.3
UNFIT_TAGS = {"grudge", "conflict", "gossip", "rumor", "heard_about_me", "secret", "private", "introduction", "worry"}
ID_RE = re.compile(r"mem_[0-9a-f]{8}")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']{4,}")
STOPWORDS = {"that", "this", "with", "have", "from", "they", "them", "what", "when", "were", "your", "about", "just", "like",
             "will", "would", "there", "their", "been", "some", "than", "then", "into", "over", "very", "much", "really"}


def parse_ids(text):
    """Memory ids written anywhere in a USES line, in order, without repeats."""
    seen = []
    for m in ID_RE.findall(text or ""):
        if m not in seen:
            seen.append(m)
    return seen


def conversation_partner(c, world):
    for conv in (world.get("conversations") or {}).values():
        parts = conv.get("participants", [])
        if c.get("id") in parts and len(parts) == 2:
            return next((p for p in parts if p != c.get("id")), None)
    return None


def _fit(m, other_id):
    if other_id not in (m.get("people") or []) or not m.get("text") or m.get("kind", "memory") != "memory":
        return False
    if (m.get("importance", 0) or 0) < MIN_IMPORTANCE:
        return False
    return not (set(m.get("tags") or []) & UNFIT_TAGS)


def candidates(c, other_id, limit=MAX_OFFERED):
    """The memories of `c` that are about `other_id` and fit to bring up, most important first."""
    mems = [m for m in (c.get("memories") or []) if m.get("id") and _fit(m, other_id)]
    return sorted(mems, key=lambda m: (-(m.get("importance", 0) or 0), -(m.get("tick", 0) or 0)))[:limit]


def context_lines(c, world):
    """For the prompt: memories about the person c is talking with, each with its id."""
    other_id = conversation_partner(c, world)
    other = (world.get("characters") or {}).get(other_id) if other_id else None
    if not other:
        return None
    mems = candidates(c, other_id)
    if not mems:
        return None
    lines = [f"Things you remember about {other.get('name', 'them')} (bringing one up shows you remember them; if your reply "
             f"draws on one, list its id on a USES line):"]
    for m in mems:
        lines.append(f"- [{m['id']}] {m['text'][:140]}")
    return lines


def _words(text):
    return {w.lower() for w in WORD_RE.findall(text or "")} - STOPWORDS


def _backed(utterance, memory):
    """The line has something of the memory in it."""
    return bool(_words(utterance) & _words(memory.get("text")))


def validate(speaker, listener_id, ids, utterance):
    """The memories among `ids` that hold up (checks 1-3 in the module doc)."""
    by_id = {m.get("id"): m for m in (speaker.get("memories") or [])}
    ok = []
    for i in ids[:MAX_REFS * 2]:
        m = by_id.get(i)
        if m and _fit(m, listener_id) and _backed(utterance, m):
            ok.append(m)
        if len(ok) >= MAX_REFS:
            break
    return ok


def acknowledge(speaker, listener, ids, utterance, world, *, intent=None, channel="speech", audience="hearing", volume="medium",
                ref=None):
    """Called from the speech path (a worker thread: emit only). Returns the validated memories, or []."""
    if not ids or not listener or (intent or {}).get("valence") in ("hurt", "deceive"):
        return []
    tick = world.get("tick", 0)
    last = (speaker.get("_acknowledged") or {}).get(listener["id"])
    if last is not None and tick - last < COOLDOWN_TICKS:
        return []
    mems = validate(speaker, listener["id"], ids, utterance)
    if not mems:
        return []
    speaker.setdefault("_acknowledged", {})[listener["id"]] = tick
    magnitude = round(min(8.0, 3.0 + 5.0 * max((m.get("importance", 0) or 0) for m in mems)), 2)
    from systems.relationship_ledger import emit_impact
    emit_impact(speaker, "personal_acknowledgement", target_id=listener["id"], magnitude=magnitude, channel=channel,
                audience=audience, volume=volume, text=utterance, memory_refs=[m["id"] for m in mems],
                ref=dict(ref or {}, memories=[{"id": m["id"], "text": m["text"][:140]} for m in mems]))
    return mems
