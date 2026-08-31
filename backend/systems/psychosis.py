"""
systems/psychosis.py

Psychosis is a temporary STATE any character can enter -- from stress,
sleep deprivation (body.py::body_energy() as the proxy; no separate
sleep-debt tracker exists to build a second one from), or intoxication
(harassment.py's real alcohol/drug tracking). A schizophrenia diagnosis
doesn't get a separate hallucination system -- it's the same mechanic
with a much higher baseline entry rate and more severe/longer episodes,
matching the template's own notes ("without medication, episodes of
psychosis become more severe").
"""

import random

STRESS_THRESHOLD = 60.0
ENERGY_THRESHOLD = 0.25
INTOX_THRESHOLD = 0.5
SCHIZOPHRENIA_MULTIPLIER = 8.0
EPISODE_DURATION_TICKS = (300, 1800)  # 5-30 sim-minutes
CONTINUED_HALLUCINATION_CHANCE = 0.3

_HALLUCINATION_CONTENT = [
    ("aliens",        "There's something out there -- lights, in the sky..."),
    ("ghost",          "Someone's standing right there. Watching."),
    ("shadow_figure",  "There's someone in the corner of the room."),
    ("voice",          "Did you hear that? Someone just said my name."),
    ("insects",        "Something's crawling on me -- get it off!"),
]


def _has_schizophrenia(c):
    return "schizophrenia" in c.get("mental_health", [])


def tick_psychosis(c, world):
    """Called at a moderate per-character cadence (see sim_loop.py).
    Rolls entry/exit and fires a hallucination while active."""
    state = c.setdefault("psychosis_state", {
        "active": False, "intensity": 0.0, "trigger": None, "started_tick": None,
    })
    tick = world.get("tick", 0)

    if state["active"]:
        duration = tick - (state.get("started_tick") or tick)
        if duration > state.get("_duration", EPISODE_DURATION_TICKS[1]):
            state["active"] = False
            state["intensity"] = 0.0
            state["trigger"] = None
            state["_duration"] = None
            return
        if random.random() < CONTINUED_HALLUCINATION_CHANCE:
            trigger_hallucination(c, world)
        return

    from systems.body import body_energy
    stress = c.get("stress", 0.0)
    energy = body_energy(c)
    intox = c.get("intoxication_state", {})
    alcohol = intox.get("alcohol_level", 0.0)
    drug = intox.get("drug_level", 0.0)

    score = 0.0
    trigger = None
    if stress >= STRESS_THRESHOLD:
        score += (stress - STRESS_THRESHOLD) / 100.0
        trigger = "stress"
    if energy <= ENERGY_THRESHOLD:
        contrib = (ENERGY_THRESHOLD - energy) / ENERGY_THRESHOLD * 0.5
        if contrib > score:
            trigger = "sleep_deprivation"
        score += contrib
    if alcohol >= INTOX_THRESHOLD or drug >= INTOX_THRESHOLD:
        contrib = max(alcohol, drug) * 0.6
        if contrib > score:
            trigger = "intoxication"
        score += contrib

    if _has_schizophrenia(c):
        score = max(score, 0.05) * SCHIZOPHRENIA_MULTIPLIER
        trigger = trigger or "schizophrenia"

    if score <= 0:
        return

    entry_chance = min(0.9, score * 0.15)
    if random.random() > entry_chance:
        return

    intensity = min(1.0, score)
    lo, hi = EPISODE_DURATION_TICKS
    duration = int(lo + (hi - lo) * intensity)
    if _has_schizophrenia(c):
        intensity = min(1.0, intensity * 1.5)
        duration = int(duration * 1.5)

    state["active"] = True
    state["intensity"] = intensity
    state["trigger"] = trigger
    state["started_tick"] = tick
    state["_duration"] = duration

    trigger_hallucination(c, world)


def trigger_hallucination(c, world):
    """Fires a real, observable reaction -- other nearby characters
    perceive the frightened/erratic reaction itself (not the
    hallucination), which is the "bizarre situation" a household needs
    to react to (brain/perception.py already surfaces reactions to
    anyone nearby, no new observation channel needed)."""
    content_type, line = random.choice(_HALLUCINATION_CONTENT)

    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(c, world, "hallucinating")
    except Exception:
        pass

    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "exclaim", line, world)
    except Exception:
        pass

    return {"content_type": content_type, "line": line}
