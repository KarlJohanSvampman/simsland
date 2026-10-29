"""
systems/worry_breakdown.py -- when worry takes everything: a breakdown episode.

(docs/worry_system_plan.md, step 4. Focus budget and cases: systems/worry_cases.py; required focus, aborts and
relief: systems/worry_relief.py.)

A character whose worries are at their heaviest -- focus at the floor MAX_LOAD leaves (the plan said "<= 5%", which
a load cap of 80 can never reach) for BREAKDOWN_AFTER_TICKS, or who has given up on BREAKDOWN_ABORTS demanding
activities within BREAKDOWN_ABORT_WINDOW -- falls apart for 10-30 simulated minutes:

  * They do not freeze. Every 1-3 simulated minutes (a "beat") they take one of their own intentions at random
    and pair it with an activity that does NOT fit it, and say or do something about it out loud: cry, snap, mutter,
    sigh (systems/expressions.py: one-way, so it never starts a conversation, and the relationship ledger sees it).
    A short-tempered character may lash out at whoever is near.
  * Normal intention dispatch is suspended and nobody asks their model what to do; a survival need (toilet, water,
    food) can still take over.
  * When it ends, a share of the worry load is relieved (BREAKDOWN_RELIEF_PCT), they remember it, whoever saw it is
    worried about them (a worry case and, for people they are close to, a check_in_on intention) and a worry about
    the episode itself may stay with them. Then BREAKDOWN_COOLDOWN_TICKS must pass before the next one.

State: c["_breakdown"] while an episode runs; c["focus_state"]["breakdown_cooldown_until"], ["low_since"],
["abort_ticks"] between them.
"""

import random

from systems import worry_cases as wc
from systems.worry_cases import HOUR

MINUTE = 60
BREAKDOWN_AT = 100 - wc.MAX_LOAD            # focus at the floor: worries at their maximum
BREAKDOWN_AFTER_TICKS = 90 * MINUTE         # ... for this long (it was three minutes: one bad moment and they were gone)
BREAKDOWN_ABORTS = 3                        # or this many given-up activities ...
BREAKDOWN_ABORT_WINDOW = 2 * HOUR           # ... within this long
EPISODE_TICKS = (10 * MINUTE, 30 * MINUTE)
BEAT_TICKS = (1 * MINUTE, 3 * MINUTE)
BREAKDOWN_COOLDOWN_TICKS = 18 * HOUR
BREAKDOWN_RELIEF_PCT = 30
MIN_AGE = 3
LASH_OUT_TRAITS = {"hot_tempered", "short_tempered", "aggressive", "impulsive", "spiteful", "impatient"}
LASH_OUT_CHANCE = 0.5
RECENT_BREAKDOWN_TICKS = 3 * HOUR
CLOSE_ENOUGH_TO_CHECK_IN = 1.0

# what a breakdown does with its hands: nothing that needs another person, nothing vital, nothing that is somebody's job
ALLOWED_CATEGORIES = {"leisure", "internal", "emotional", "chore", "creative", "appearance", "maintenance"}
EXCLUDED = {"fight", "argue", "sleep", "nap", "work_shift", "doomscroll"}

_BEAT_TEXT = {
    "cry": ["I can't do this. I just can't.", "It's too much.", "Why is everything going wrong?"],
    "snap": ["Leave me alone!", "I can't deal with any of this right now!", "Stop asking me for things!"],
    "mutter": ["I can't think straight...", "Everything keeps piling up...", "I don't know what I'm doing anymore..."],
    "sigh": ["I give up.", "What's the point.", "I can't keep this up."],
}
_BEAT_ACT = {"cry": "vent", "snap": "yell", "mutter": "mutter", "sigh": "sigh"}
_BEAT_VOLUME = {"cry": "medium", "snap": "high", "mutter": "low", "sigh": "low"}


def in_breakdown(c):
    return bool(c.get("_breakdown"))


def _state(c):
    return c.setdefault("focus_state", {})


# ---------------------------------------------------------------------------
# when
# ---------------------------------------------------------------------------

def note_abort(c, world):
    """Called when they give up on an activity (systems/worry_relief.py)."""
    state = _state(c)
    tick = world.get("tick", 0)
    state["abort_ticks"] = [t for t in state.get("abort_ticks", []) if tick - t <= BREAKDOWN_ABORT_WINDOW] + [tick]


def should_break_down(c, world, avail):
    tick = world.get("tick", 0)
    state = _state(c)
    if in_breakdown(c) or tick < state.get("breakdown_cooldown_until", 0):
        return None
    if c.get("alive") is False or c.get("off_grid") or (c.get("age") or 30) < MIN_AGE:
        return None
    if (c.get("activity") or {}).get("type") in ("sleep", "nap") or c.get("posture") == "incapacitated":
        return None
    # sustained at the floor
    if avail <= BREAKDOWN_AT:
        since = state.setdefault("low_since", tick)
        if tick - since >= BREAKDOWN_AFTER_TICKS:
            return "overwhelmed"
    else:
        state.pop("low_since", None)
    recent = [t for t in state.get("abort_ticks", []) if tick - t <= BREAKDOWN_ABORT_WINDOW]
    if len(recent) >= BREAKDOWN_ABORTS:
        return "gave_up_too_often"
    return None


def tick_breakdown(c, world, avail):
    """Called every sim-minute for a worried character: start, advance or end an episode."""
    tick = world.get("tick", 0)
    b = c.get("_breakdown")
    if b:
        if tick >= b["end"] or c.get("alive") is False:
            end_breakdown(c, world)
        elif tick >= b["next_beat"]:
            beat(c, world)
        return
    why = should_break_down(c, world, avail)
    if why:
        start_breakdown(c, world, why)


# ---------------------------------------------------------------------------
# the episode
# ---------------------------------------------------------------------------

def start_breakdown(c, world, why):
    tick = world.get("tick", 0)
    c["_breakdown"] = {"start": tick, "end": tick + random.randint(*EPISODE_TICKS), "next_beat": tick, "beats": 0,
                       "why": why, "witnesses": []}
    state = _state(c)
    state.pop("low_since", None)
    state["abort_ticks"] = []
    state["breakdowns"] = state.get("breakdowns", 0) + 1
    c["current_intention"] = None
    # nobody is waiting on a decision from someone who is falling apart
    cog = c.setdefault("cognition", {})
    cog["pending"] = None
    cog["wake_reason"] = None
    cog["next_think_tick"] = tick + (c["_breakdown"]["end"] - tick) + 1
    beat(c, world)


def _own_intentions(c):
    return [i for i in c.get("active_intentions", []) if i.get("type") != "relieve_worry"]


def _pick_activity(c, world, intention):
    """An activity that doesn't fit the intention, that they could actually do right now."""
    from systems.activities import ACTIVITIES
    age = c.get("age") or 30
    try:
        from systems.action_registry import ACTION_TYPE_MIN_AGE
    except Exception:
        ACTION_TYPE_MIN_AGE = {}
    itype = str((intention or {}).get("type", ""))
    pool = [a for a, spec in ACTIVITIES.items()
            if spec.get("category") in ALLOWED_CATEGORIES and a not in EXCLUDED and age >= ACTION_TYPE_MIN_AGE.get(a, 0)
            and a not in itype and itype not in a]
    random.shuffle(pool)
    return pool


def _near(c, world):
    seen = [p.get("id") for p in (c.get("perception") or {}).get("visible_people", [])]
    return [world["characters"][i] for i in seen if i in world.get("characters", {}) and world["characters"][i].get("alive") is not False]


def beat(c, world):
    """One 1-3 minute step of the episode: a random intention, a mismatched activity, something said aloud."""
    from systems.expressions import express
    tick = world.get("tick", 0)
    b = c["_breakdown"]
    b["beats"] += 1
    b["next_beat"] = tick + random.randint(*BEAT_TICKS)

    intentions = _own_intentions(c)
    intention = random.choice(intentions) if intentions else None
    people = _near(c, world)
    for p in people:
        if p["id"] not in b["witnesses"]:
            b["witnesses"].append(p["id"])

    # what they do
    started = None
    if (c.get("activity") or {}).get("type") not in ("use_toilet", "vomit", "sleep"):
        from systems.activities import start_activity
        from systems.occupancy import interrupt_activity
        for activity in _pick_activity(c, world, intention)[:6]:
            if c.get("activity"):
                interrupt_activity(c, world)
                c["is_moving"] = False
                c["move_target"] = None
            if start_activity(c, world, activity):
                started = activity
                break
    b["last_activity"] = started

    # what they say
    traits = set(c.get("traits") or [])
    kind = random.choice(["cry", "snap", "mutter", "sigh"])
    target = None
    if people and (traits & LASH_OUT_TRAITS) and random.random() < LASH_OUT_CHANCE:
        kind, target = "snap", random.choice(people)["id"]
    text = random.choice(_BEAT_TEXT[kind])
    if intention and kind in ("mutter", "snap") and random.random() < 0.5:
        topic = str(intention.get("type", "")).split(":")[-1].replace("_", " ").strip()
        if topic:
            text = f"I can't even think about {topic} right now. {text}" if kind == "mutter" else f"Don't talk to me about {topic}!"
    if kind == "cry" and not started and not c.get("activity"):
        from systems.activities import start_activity
        start_activity(c, world, "cry")
    intent = {"source": "breakdown"}
    if target:
        intent["valence"] = "hurt"                       # lashing out at someone is an insult as far as they are concerned
    express(c, world, {"utterance": text, "speech_act": _BEAT_ACT[kind], "volume": _BEAT_VOLUME[kind], "target": target,
                       "intent": intent})


def end_breakdown(c, world):
    from systems.worry_relief import ease_case
    tick = world.get("tick", 0)
    b = c.pop("_breakdown", None) or {}
    state = _state(c)
    state["breakdown_cooldown_until"] = tick + BREAKDOWN_COOLDOWN_TICKS
    state["last_breakdown"] = tick
    for case in wc.active_cases(c):
        ease_case(c, case, BREAKDOWN_RELIEF_PCT, world, "breakdown", "breakdown")
    wc.update_focus(c, world)
    minutes = max(1, round((tick - b.get("start", tick)) / MINUTE))
    try:
        from brain.memory import store_memory
        store_memory(c, f"I fell apart for about {minutes} minutes. Everything was too much. I feel emptied out now, "
                        f"but a bit lighter.", importance=0.7, tags=["worry_case", "breakdown"], tick=tick, source="internal")
    except Exception:
        pass
    from systems.worry_producers import on_own_breakdown, on_witnessed_breakdown
    on_own_breakdown(c, world)
    for oid in b.get("witnesses", []):
        observer = world.get("characters", {}).get(oid)
        if observer and observer.get("alive") is not False:
            on_witnessed_breakdown(observer, c, world, minutes)
    try:
        from brain.cognition_scheduler import wake_character
        wake_character(c, world, "worry_overload", {"activity": "carry on"})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# while it lasts
# ---------------------------------------------------------------------------

def survival_only(c, world):
    """Idle moment during an episode: a survival need may still take over; nothing else is dispatched."""
    from systems.strategy import resolve_strategy
    from systems.activities import start_activity
    for intention in c.get("active_intentions", []):
        if intention.get("category") != "survival":
            continue
        activity = resolve_strategy(c, world, intention)
        if activity and start_activity(c, world, activity):
            c["current_intention"] = intention
            return True
    return False


def recently_broke_down(c, world):
    last = (c.get("focus_state") or {}).get("last_breakdown")
    return last is not None and world.get("tick", 0) - last < RECENT_BREAKDOWN_TICKS
