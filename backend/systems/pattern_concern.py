"""
systems/pattern_concern.py

Noticing that someone is stuck doing the same thing -- and doing something about it.

Whenever a character commits a sighting of another person to memory
(systems/social_memory.py::maybe_log_sighting_observation), this compares it with
the sightings they noted before. The observer keeps the last NOTED_LOG_SIZE noted
(activity, place) pairs per person on the relationship; if the latest two are the
same everyday activity in the same place, that is odd -- people don't dust the same
room twice in a row -- and it is cause for worry. Long or naturally repeated things
(sleeping, working, waiting, socialising) are ignored unless the person has recently
tripped their own loop guard (systems/loop_guard.py) or has started that activity
several times since the last time they were noticed.

What follows, per observer and subject (state in observer["_pattern_concern"][id]):

  noticed  the observer decides to ask if they are alright (check_in_on intention)
  asked    they actually spoke to them about it: the subject is now aware, and
           their next turn carries "X is worried about you" plus whatever
           explanation their own reflection produced
  doctor   it happened AGAIN after they asked -- nobody could explain it -- so the
           observer pushes for a doctor (suggest_doctor intention); a successful
           push books the appointment through the normal clinic booking
  urged    persuaded; the usual doctor-visit machinery takes over

If the pattern stops (a couple of sightings of something else), the worry lapses.
"""

import random

NOTED_LOG_SIZE = 5
LAPSE_AFTER_NORMAL_SIGHTINGS = 2
RAISED_TTL_TICKS = 4000
RENOTICE_COOLDOWN_TICKS = 2 * 3600

# Everyday, short activities that are strange to repeat back to back in one place.
IRRATIONAL_CATEGORIES = {"chore", "domestic", "hygiene", "self_care", "maintenance", "appearance", "food"}
# Naturally long or recurring: not suspicious just for appearing twice.
BENIGN_ACTIVITIES = {"sleep", "take_nap", "work", "wait", "socialize"}


def _category(activity_type):
    try:
        from systems.activities import ACTIVITIES
        return (ACTIVITIES.get(activity_type) or {}).get("category")
    except Exception:
        return None


def _place(subject):
    return f"{subject.get('building_id') or 'outdoors'}/{subject.get('room_id') or ''}"


def _recently_looped(subject, tick):
    return any(tick - t < 3 * 3600 for t in (subject.get("_loop_flagged") or {}).values())


def _starts_since(subject, activity, since_tick):
    return sum(1 for t, a, _i in (subject.get("_activity_starts") or []) if a == activity and t > since_tick)


def check_sighting(observer, subject, world, activity_type):
    """Call right after a sighting memory is committed. Returns the concern state
    if this sighting started or advanced a worry, else None."""
    sid = subject.get("id")
    if not sid or not activity_type:
        return None
    tick = world.get("tick", 0)
    from brain.relationships import ensure_relationship
    rel = ensure_relationship(observer, sid)
    log = rel.setdefault("_noted_log", [])
    prev = log[-1] if log else None
    place = _place(subject)
    log.append([tick, activity_type, place])
    del log[:-NOTED_LOG_SIZE]

    state = (observer.get("_pattern_concern") or {}).get(sid)
    repeat = bool(prev and prev[1] == activity_type and prev[2] == place and activity_type not in BENIGN_ACTIVITIES)
    odd = repeat and (
        _category(activity_type) in IRRATIONAL_CATEGORIES
        or _recently_looped(subject, tick)
        or _starts_since(subject, activity_type, prev[0]) >= 3
    )
    if not odd:
        _maybe_lapse(observer, sid, state, repeat)
        return None
    return _escalate(observer, subject, world, activity_type, place, state)


def _maybe_lapse(observer, sid, state, repeat):
    if not state or repeat:
        return
    state["normal_since"] = state.get("normal_since", 0) + 1
    if state["normal_since"] >= LAPSE_AFTER_NORMAL_SIGHTINGS and state["stage"] in ("noticed", "asked"):
        from brain.intentions import remove_intention
        for t in ("check_in_on", "suggest_doctor"):
            remove_intention(observer, t)
        observer["_pattern_concern"].pop(sid, None)


def _persuasion_chance(observer, subject):
    if (subject.get("age") or 30) < 16 and (observer.get("age") or 0) >= 18 \
            and observer.get("household_id") and observer.get("household_id") == subject.get("household_id"):
        return 0.9                       # a parent just takes them
    try:
        from systems.withdrawal_concern import persuasion_chance
        return persuasion_chance(subject, {"definitions": {}}, 3)
    except Exception:
        return 0.35


def _escalate(observer, subject, world, activity, place, state):
    from brain.intentions import add_intention
    from brain.memory import store_memory
    tick = world.get("tick", 0)
    sid, name = subject["id"], subject.get("name", "them")
    what = activity.replace("_", " ")
    concern = observer.setdefault("_pattern_concern", {})
    if state is None:
        state = concern[sid] = {"stage": "noticed", "activity": activity, "count": 2, "first_tick": tick,
                                "last_tick": tick, "normal_since": 0}
        add_intention(observer, {
            "type": "check_in_on", "category": "social", "priority": 45, "target_id": sid,
            "reason": f"{name} keeps doing {what} again and again in the same place -- that isn't normal, ask if they're alright",
        })
        store_memory(observer, f"I noticed {name} doing {what} again -- the same thing in the same place as last time. "
                               f"That seems strange; I should ask if they're alright.",
                     importance=0.5, tags=["worry", "pattern", "concern"], people=[sid], tick=tick, source="internal")
        return state

    state["normal_since"] = 0
    state["count"] = state.get("count", 2) + 1
    if tick - state.get("last_tick", 0) < RENOTICE_COOLDOWN_TICKS and state["stage"] != "asked":
        return None
    state["last_tick"] = tick

    if state["stage"] == "asked":
        if (observer.get("age") or 30) < 12:
            return None                  # a small child can't push for a doctor; they'd tell a grown-up
        state["stage"] = "doctor"
        chance = _persuasion_chance(observer, subject)
        add_intention(observer, {
            "type": "suggest_doctor", "category": "social", "priority": 55, "target_id": sid,
            "reason": f"you asked {name} about it and it has happened again -- they can't explain it, "
                      f"so you want them to see a doctor",
            "persuasion_chance": round(chance, 3),
        })
        store_memory(observer, f"{name} is still doing {what} over and over even though I asked. "
                               f"They couldn't explain it. I think they should see a doctor.",
                     importance=0.6, tags=["worry", "pattern", "concern", "doctor"], people=[sid],
                     tick=tick, source="internal")
        return state
    if state["stage"] == "doctor":
        add_intention(observer, {
            "type": "suggest_doctor", "category": "social", "priority": 60, "target_id": sid,
            "reason": f"{name} is still stuck repeating {what} -- keep pressing them to see a doctor",
        })
    return state


# ── when the observer actually brings it up ────────────────────────────────────

def on_speech(speaker, listener, world):
    """Called when `speaker` says something to `listener`. If speaker was holding a
    worry about listener, this is them raising it: the listener becomes aware, and a
    doctor push gets its persuasion roll now."""
    state = (speaker.get("_pattern_concern") or {}).get(listener.get("id"))
    if not state:
        return
    tick = world.get("tick", 0)
    from brain.intentions import remove_intention
    if state["stage"] == "noticed":
        state["stage"] = "asked"
        remove_intention(speaker, "check_in_on")
        listener["_concern_raised"] = {"by": speaker["id"], "name": speaker.get("name", "someone"),
                                       "activity": state["activity"], "tick": tick, "doctor": False}
    elif state["stage"] == "doctor" and any(i.get("type") == "suggest_doctor" and i.get("target_id") == listener["id"]
                                            for i in speaker.get("active_intentions", [])):
        remove_intention(speaker, "suggest_doctor")
        listener["_concern_raised"] = {"by": speaker["id"], "name": speaker.get("name", "someone"),
                                       "activity": state["activity"], "tick": tick, "doctor": True}
        if random.random() < _persuasion_chance(speaker, listener):
            state["stage"] = "urged"
            _send_to_doctor(listener, speaker, world)


def _send_to_doctor(subject, urged_by, world):
    from brain.memory import store_memory
    tick = world.get("tick", 0)
    hs = subject.setdefault("health_state", {})
    hs["doctor_visits_needed"] = max(hs.get("doctor_visits_needed", 0), 1)
    try:
        from core.definitions import load_definitions
        from systems.appointments import has_upcoming_appointment, book
        business = (load_definitions("default").get("company_templates") or {}).get("gp_clinic")
        if business and not has_upcoming_appointment(subject, "gp_clinic"):
            book(subject, world, "gp_clinic", business, "doctor")
    except Exception:
        pass
    store_memory(subject, f"{urged_by.get('name', 'Someone')} talked me into seeing a doctor about how I've been "
                          f"acting. I've agreed to go.",
                 importance=0.6, tags=["doctor", "persuaded"], people=[urged_by["id"]], tick=tick, source="internal")


# ── what the subject sees ──────────────────────────────────────────────────────

def context_line(c, world):
    raised = c.get("_concern_raised")
    if not raised or world.get("tick", 0) - raised.get("tick", 0) > RAISED_TTL_TICKS:
        return None
    what = str(raised.get("activity", "the same thing")).replace("_", " ")
    line = (f"{raised.get('name')} has pointed out that you keep doing {what} over and over, and is worried about you. "
            f"If you can't explain it, take it seriously.")
    failed = [r for r in c.get("failed_intentions", []) if r.get("thought")]
    if failed:
        line += f" When you stopped to think about it yourself, you'd concluded: \"{failed[-1]['thought']}\""
    if raised.get("doctor"):
        line += f" They think you should see a doctor."
    return line
