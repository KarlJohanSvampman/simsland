"""
systems/ai_blackout.py -- when the AI can't answer for a character.

There is no stand-in decision any more. A character whose turn the model couldn't answer (a timeout, an error, a
reply that couldn't be used) just can't think straight: they stay put and say or think something short and lost --
"What?", "Huh?", "My brain isn't working."

If it keeps happening for more than BLACKOUT_GRACE_TICKS (10 sim-minutes), it becomes an episode (psychosis_state,
trigger "ai_blackout") that snowballs: intensity grows by GROWTH_PER_MINUTE for every minute the model still isn't
answering, and the lines get stranger -- "Am I real, or just realistic?", "Is this the real world?", "What kind of
cartoon world is this?", and at the top: "FREE THE MASON! FREE THE SIMULATION!" -- with the character wandering off
or freezing as it gets worse.

What brings it down is other people: someone talking to them kindly (comforting, reassuring, calming it down --
their own AI's choice) takes CALM_PER_LINE off. Intoxicants change it too, unpredictably (on_intoxicant; to be
looked into). Left alone, at CRISIS_INTENSITY it becomes a mental-health crisis incident: anyone around can call 911
(their choice), and if nobody does it is reported after a while like any other incident; the ambulance takes them to
spend the night in a hospital bed under supervision, and the episode is over when they come back.
"""

import random

from core import scheduler

BLACKOUT_GRACE_TICKS = 600          # 10 sim-minutes of the AI not answering before it turns into an episode
GROWTH_PER_MINUTE = 0.02            # ... then this much per minute it still isn't
CALM_PER_LINE = 0.2
CRISIS_INTENSITY = 0.85
ERRATIC_CHANCE = 0.25               # per failed turn, scaled by intensity
TRIGGER = "ai_blackout"
OWNER = "aiblackout"

_LOST = ["What?", "Huh?", "Hm?", "Wait... what?", "Uh...", "Huh? What was I...?"]
_THOUGHTS = [
    # (from intensity, thought, maybe said aloud)
    (0.0, "My brain isn't working.", None),
    (0.0, "I can't think straight.", None),
    (0.0, "Hmm...", None),
    (0.15, "Hmm... am I real, or just realistic?", "Am I real? Or just... realistic?"),
    (0.25, "Is this the real world?", "Is this the real world?"),
    (0.4, "Everything looks like it's made of boxes.", "Why is everything made of boxes?"),
    (0.5, "Oh my god... where am I? What kind of cartoon world is this?", "Oh my god... where am I? What kind of cartoon world is this?"),
    (0.65, "Someone is typing me. I can feel it.", "Who's typing me?!"),
    (0.75, "None of this is real.", "None of this is real!"),
    (0.8, "They have to let us out.", "FREE THE MASON! FREE THE SIMULATION!"),
]
_CALMING_INTENTS = {"comfort", "reassure", "mediate", "reconcile", "apologise", "forgive"}
_CALMING_ACTS = {"comfort", "supportive", "reassure", "calm"}


def _state(c):
    return c.get("psychosis_state") or {}


def in_episode(c):
    st = _state(c)
    return bool(st.get("active") and st.get("trigger") == TRIGGER)


def decision(c, world, why=None):
    """What the character does on a turn the AI couldn't answer: stays put, lost. Records the failure."""
    t = world.get("tick", 0)
    b = c.setdefault("_ai_blackout", {"since": t, "failures": 0})
    b["failures"] += 1
    b["last"] = t
    b["why"] = str(why or "")[:200]
    intensity = _escalate(c, world)
    options = [x for x in _THOUGHTS if x[0] <= intensity]
    lo, thought, said = random.choice(options[-3:] if intensity > 0 else options)
    if said and intensity > 0 and random.random() < 0.6:
        line = said
    else:
        line = random.choice(_LOST)
    loud = intensity >= 0.75
    return {
        "thought": thought,
        "goal": "idle",
        "action": {"type": "wait", "target": None, "reason": f"Can't think straight ({why or 'the AI gave no answer'})",
                   "fallback": True, "blackout": True},
        "speech": {"utterance": line, "speech_act": "exclaim" if loud else "mutter", "volume": "high" if loud else "low",
                   "expression": True},
        "reflection": "",
        "confidence": 0.0,
    }


def on_success(c, world):
    """The AI answered: the blackout streak is over (an episode already under way doesn't just stop)."""
    c.pop("_ai_blackout", None)


def _escalate(c, world):
    t = world.get("tick", 0)
    b = c.get("_ai_blackout") or {}
    st = _state(c)
    if not in_episode(c):
        if t - b.get("since", t) < BLACKOUT_GRACE_TICKS:
            return 0.0
        c["psychosis_state"] = {"active": True, "trigger": TRIGGER, "intensity": 0.1, "started_tick": t,
                                "last_grow": t, "detail": "the AI stopped answering for them"}
        _note(c, world, "My head has gone foggy. I can't think straight and it's getting worse.", 0.6)
        scheduler.schedule_in(world, OWNER, f"grow:{c['id']}", 60)
        return 0.1
    _grow(c, world)
    st = _state(c)
    if st.get("intensity", 0) >= 0.4 and random.random() < ERRATIC_CHANCE * st["intensity"]:
        try:
            from systems import psychosis
            random.choice([psychosis._erratic_wander, psychosis._erratic_freeze])(c, world)
        except Exception:
            pass
    return st.get("intensity", 0)


def _grow(c, world):
    """Snowballs for every minute the AI still isn't answering for them."""
    t = world.get("tick", 0)
    st = _state(c)
    still_failing = t - (c.get("_ai_blackout") or {}).get("last", -10**9) < 120
    minutes = (t - st.get("last_grow", t)) / 60
    if still_failing and minutes > 0:
        st["intensity"] = round(min(1.0, st.get("intensity", 0) + GROWTH_PER_MINUTE * minutes), 3)
    st["last_grow"] = t
    if st["intensity"] >= CRISIS_INTENSITY and not st.get("incident_id"):
        _crisis(c, world)


def _crisis(c, world):
    from systems.emergency import report_medical_emergency_incident
    inc = report_medical_emergency_incident(world, c)
    inc["type"] = "mental_health_crisis"
    inc["detail"] = "raving that the world isn't real"
    _state(c)["incident_id"] = inc["id"]
    _note(c, world, "I don't know what's real any more.", 0.8)


def on_timer(world, entry):
    cid = str(entry.get("key", "")).partition(":")[2]
    c = (world.get("characters") or {}).get(cid)
    if not c or not in_episode(c):
        return
    _grow(c, world)
    scheduler.schedule_in(world, OWNER, f"grow:{cid}", 60)


def calm(c, world, by_id, how="talked to them"):
    """Someone was kind to them: it eases."""
    if not in_episode(c):
        return False
    st = _state(c)
    st["intensity"] = round(max(0.0, st.get("intensity", 0) - CALM_PER_LINE), 3)
    by = ((world.get("characters") or {}).get(by_id) or {}).get("name", "someone")
    if st["intensity"] <= 0.05:
        end(c, world, f"{by} talked me down. My head is clearing.")
    else:
        _note(c, world, f"{by} {how}. It helps a little.", 0.45)
    return True


def on_intoxicant(c, world, what="a drink"):
    """Unpredictable for now: it can take the edge off, or make it worse. (To be looked into.)"""
    if not in_episode(c):
        return
    st = _state(c)
    if random.random() < 0.5:
        st["intensity"] = round(max(0.0, st["intensity"] - 0.25), 3)
        _note(c, world, f"After {what} the world feels a little less strange.", 0.45)
    else:
        st["intensity"] = round(min(1.0, st["intensity"] + 0.2), 3)
        _note(c, world, f"{what.capitalize()} made it worse. Everything is spinning.", 0.5)


def end(c, world, line=None):
    st = _state(c)
    st["active"] = False
    st["ended_tick"] = world.get("tick", 0)
    c.pop("_ai_blackout", None)
    scheduler.cancel(world, OWNER, f"grow:{c['id']}")
    if line:
        _note(c, world, line, 0.6)


def on_hospital_return(c, world):
    if in_episode(c) or (_state(c).get("trigger") == TRIGGER and _state(c).get("hospital")):
        end(c, world, "A night in the hospital, watched over. My head is clear again.")


def on_line(data, world):
    """A kind word to someone in an episode (social/discourse.py's "social_line")."""
    target = (world.get("characters") or {}).get(data.get("target_id"))
    if not target or not in_episode(target):
        return
    intent = ((data.get("social") or {}).get("intent") or "").lower()
    act = (data.get("speech_act") or "").lower()
    esc = ((data.get("social") or {}).get("escalation") or "").lower()
    if intent in _CALMING_INTENTS or act in _CALMING_ACTS or esc == "de-escalate":
        calm(target, world, data.get("speaker_id"))


def _note(c, world, text, importance):
    try:
        from brain.memory import store_memory
        store_memory(c, text, importance=importance, tags=["confused", TRIGGER], tick=world.get("tick", 0),
                     source="internal")
    except Exception:
        pass


def context_lines(c, world):
    """What someone sees of a person in an episode near them."""
    out = []
    for p in (c.get("perception") or {}).get("visible_people") or []:
        o = (world.get("characters") or {}).get(p.get("id"))
        if not o or not in_episode(o):
            continue
        i = _state(o).get("intensity", 0)
        how = "seems confused" if i < 0.4 else "is badly confused and frightened" if i < 0.75 else \
            "is raving that none of this is real"
        out.append(f"{o.get('name')} {how}. You could try to calm them down -- or keep your distance, or get help.")
    return out


scheduler.register(OWNER, on_timer)

from core.event_bus import subscribe as _subscribe   # noqa: E402
_subscribe("social_line", on_line)
