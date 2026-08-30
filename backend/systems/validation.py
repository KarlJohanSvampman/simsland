"""
systems/validation.py

Validation-seeking: whenever a character makes a "selective choice"
(what to wear, what to eat, what to buy, which book, which school,
which job to apply to, a behavioral change from self-reflection or
input from others, ...), the choice becomes a world event AND is queued
(c["validation_queue"]) with an expiration -- the character may later
ask someone nearby's opinion on it, or, if nobody's around and the
timer is running low, post about it on social media instead. Expired
entries just fall out of the queue unused, no penalty.

Feedback a character actually receives (an accepted "opinion_on_X"
social_ask, a like/comment on a post, an LLM-projected engagement tick)
is scored via receive_validation() -- diminishing returns for a
character already flooded with validation recently, UNLESS it's a new
personal-best single event. A character who rarely gets any validation
gets a bigger reward when they do. Feeds:
  - systems/lt_needs.py's existing "socialize" long-term need
  - c["popularity"] (accumulates from validation, decays on its own --
    see tick_popularity_decay())
  - c["self_confidence"] / c["emotional_temperature"] (mood)
"""

import random
import uuid

TICKS_PER_HOUR = 3600  # 1 tick = 1 sim-second (core/tick_schedule.py)
DEFAULT_EXPIRES_HOURS = 24
_EXPIRY_WARNING_HOURS = 2  # post about a queued choice instead of losing it once this close

BASE_VALIDATION_POINTS = 10.0
# Points actually awarded taper as recent (rolling 24h) score climbs --
# more validation recently means each new instance is worth less. A new
# personal record bypasses the taper entirely (explicit ask: "unless
# they're breaking a personal record").
DIMINISHING_HALF_LIFE = 40.0
RECORD_BONUS_MULTIPLIER = 1.5

POPULARITY_DECAY_PER_MINUTE = 0.5


# =========================================================
# QUEUEING A CHOICE
# =========================================================

def queue_choice_for_validation(c, world, choice_type, chosen_label, occasion=None,
                                 expires_hours=DEFAULT_EXPIRES_HOURS):
    """Called by any interaction that just resolved a "selective choice"
    (get_dressed today; a future meal/purchase/book/school/job/
    behavior-change interaction the same way). Emits a world event and
    queues the choice for possible validation-seeking later."""
    entry = {
        "id": f"vq_{uuid.uuid4().hex[:8]}",
        "choice_type": choice_type,
        "chosen_label": chosen_label,
        "occasion": occasion,
        "created_tick": world.get("tick", 0),
        "expires_tick": world.get("tick", 0) + expires_hours * TICKS_PER_HOUR,
    }
    c.setdefault("validation_queue", []).append(entry)

    events = world.setdefault("events", [])
    events.append({
        "id": f"choice_{uuid.uuid4().hex[:6]}",
        "type": "choice_made",
        "character_id": c["id"],
        "tick": world.get("tick", 0),
        "choice_type": choice_type,
        "chosen_label": chosen_label,
    })
    del events[:-300]
    return entry


def _prune_expired_queue(c, world):
    tick = world.get("tick", 0)
    c["validation_queue"] = [e for e in c.get("validation_queue", []) if e["expires_tick"] > tick]


def _nearby_characters(c, world):
    chars = world.get("characters", {})
    bid = c.get("building_id")
    if bid:
        return [o for o in chars.values()
                if o["id"] != c["id"] and o.get("building_id") == bid and o.get("alive", True) is not False]
    result = []
    for o in chars.values():
        if o["id"] == c["id"] or o.get("building_id") or o.get("alive", True) is False:
            continue
        if abs(o.get("x", 0) - c.get("x", 0)) + abs(o.get("y", 0) - c.get("y", 0)) <= 6:
            result.append(o)
    return result


def _question_text(entry):
    occasion_note = f" for {entry['occasion']}" if entry.get("occasion") else ""
    return f"What do you think of {entry['chosen_label']}{occasion_note}?"


def _ask_about_choice(c, world, target, entry):
    from systems.proposals import propose_social_ask
    propose_social_ask(c, target, world, f"opinion_on_{entry['choice_type']}", {
        "text": _question_text(entry),
        "choice_type": entry["choice_type"],
        "chosen_label": entry["chosen_label"],
    })


def _post_about_choice(c, world, entry):
    from systems.social_media import create_post
    media = {"kind": "photo", "description": f"{c.get('name', 'Someone')} with {entry['chosen_label']}",
              "subjects": [c["id"]]}
    create_post(c, world, _question_text(entry), media=media, tags=[entry["choice_type"]])


def maybe_seek_validation_from_queue(c, world):
    """Called periodically per character (see brain/agent_loop.py). If
    there's a queued choice and someone's nearby, may ask them about it.
    If nothing's nearby but an entry is about to expire, posts about
    the most urgent one on social media instead of losing it unused."""
    _prune_expired_queue(c, world)
    queue = c.get("validation_queue", [])
    if not queue:
        return

    nearby = _nearby_characters(c, world)
    # Small per-tick chance, not per-check -- this runs every tick per
    # character (see brain/agent_loop.py), same order of magnitude as
    # offgrid.py::maybe_go_offgrid's per-tick rolls (e.g. 0.004), not a
    # "roll once when conditions align" probability, which at 1 tick =
    # 1 second would fire almost immediately.
    if nearby and random.random() < 0.003:
        entry = random.choice(queue)
        _ask_about_choice(c, world, random.choice(nearby), entry)
        c["validation_queue"] = [e for e in queue if e["id"] != entry["id"]]
        return

    tick = world.get("tick", 0)
    urgent = min(queue, key=lambda e: e["expires_tick"])
    if not nearby and urgent["expires_tick"] - tick < _EXPIRY_WARNING_HOURS * TICKS_PER_HOUR:
        _post_about_choice(c, world, urgent)
        c["validation_queue"] = [e for e in queue if e["id"] != urgent["id"]]


# =========================================================
# VALIDATION-REFRESH -- post if nothing's landed in a while
# =========================================================

_CHECKIN_PROMPTS = [
    "Anyone up for hanging out soon?",
    "Feeling a little out of the loop lately.",
    "What's everyone up to?",
    "Been a minute since I posted -- what's new with you all?",
]


def check_validation_refresh(c, world):
    """If it's been longer than c["validation_refresh_time"] hours since
    ANY validation was received, post a general bid for attention --
    not tied to a specific queued choice."""
    tick = world.get("tick", 0)
    refresh_ticks = c.get("validation_refresh_time", 48) * TICKS_PER_HOUR
    if tick - c.get("last_validation_received", 0) < refresh_ticks:
        return
    from systems.social_media import create_post
    create_post(c, world, random.choice(_CHECKIN_PROMPTS), tags=["check_in"])
    # Reset the clock on the post attempt itself, not on receiving
    # validation -- otherwise this would fire every tick until someone
    # actually responds.
    c["last_validation_received"] = tick


# =========================================================
# RECEIVING VALIDATION -- scoring, popularity, mood
# =========================================================

def receive_validation(c, world, points=BASE_VALIDATION_POINTS, source="social"):
    """Call whenever a character actually receives validation: an
    accepted "opinion_on_X" social_ask, a like, a comment, a new
    follower, LLM-projected post engagement landing. Diminishing
    returns based on recent (rolling 24h) score, unless this single
    event is a new personal record -- then it gets a bonus instead."""
    tick = world.get("tick", 0)

    recent = _recent_score(c, world)
    taper = DIMINISHING_HALF_LIFE / (DIMINISHING_HALF_LIFE + recent)
    awarded = points * taper

    record = c.get("validation_personal_record", 0.0)
    is_record = points > record
    if is_record:
        awarded = points * RECORD_BONUS_MULTIPLIER
        c["validation_personal_record"] = points

    c.setdefault("validation_score_24h", []).append({"tick": tick, "points": round(awarded, 2)})
    _prune_score_window(c, world)

    c["last_validation_received"] = tick
    c["popularity"] = round(c.get("popularity", 0.0) + awarded, 2)

    # Mood/confidence impact scales the OPPOSITE way from the points
    # taper -- a character who rarely gets validation feels it more when
    # they finally do; one already flooded with it barely registers one
    # more instance, unless it's a record.
    mood_scale = 1.0 if is_record else max(0.15, taper)
    c["self_confidence"] = round(min(1.0, c.get("self_confidence", 0.6) + 0.01 * mood_scale), 4)
    c["emotional_temperature"] = round(min(100, c.get("emotional_temperature", 20) + 3 * mood_scale), 2)

    try:
        from systems.lt_needs import satisfy_lt_need
        satisfy_lt_need(c, "socialize", world)
    except Exception:
        pass

    return {"awarded": round(awarded, 2), "is_record": is_record}


def _recent_score(c, world):
    _prune_score_window(c, world)
    return sum(e["points"] for e in c.get("validation_score_24h", []))


def _prune_score_window(c, world):
    cutoff = world.get("tick", 0) - 24 * TICKS_PER_HOUR
    c["validation_score_24h"] = [e for e in c.get("validation_score_24h", []) if e["tick"] >= cutoff]


# =========================================================
# POPULARITY DECAY
# =========================================================

def tick_popularity_decay(world):
    """Called once per sim-minute (see sim_loop.py) -- popularity drains
    on its own; holding a high score takes ongoing validation, same as
    a real social-media-driven reputation."""
    for c in world.get("characters", {}).values():
        pop = c.get("popularity", 0.0)
        if pop > 0:
            c["popularity"] = round(max(0.0, pop - POPULARITY_DECAY_PER_MINUTE), 2)
