"""
systems/psychosis.py

Psychosis is a temporary STATE any character can enter -- but only after
one of hunger, thirst, sleep deprivation, or intoxication has been pushed
to a genuine extreme (not just "elevated") AND held there continuously
for EXTREME_SUSTAIN_TICKS (a few hours) -- a momentary spike doesn't
count, per user feedback. A schizophrenia diagnosis
doesn't get a separate hallucination system -- it's the same mechanic
with a much higher baseline entry rate (independent of the extremes
below) and more severe/longer episodes, matching the template's own
notes ("without medication, episodes of psychosis become more severe").

Live bug report (user-reported): this used to trigger off ordinary
stress and moderate need levels, and an active episode did nothing but
occasionally say a hallucination line out loud -- no real behavioral
change. Reworked so entry requires an extreme need state, and an active
episode periodically forces real, disruptive behavior (interrupting
whatever the character was doing to wander off, freeze up, or mutter to
themselves) rather than just narrating a line while everything else
continues normally.
"""

import random

# Disabled at the user's live-report request (2026-09-12): even with the
# extreme-threshold + sustain-duration gating below, an entire household
# ended up starving/dehydrated in sync (stuck off-grid for a long stretch)
# and all triggered psychosis together. Rather than re-tuning the
# threshold further, the mechanic is fully switched off here -- a single
# early return, so tick_psychosis() is a guaranteed no-op and no character
# can ever enter an episode. Nothing else needs to change: get_psychosis_
# context()/context_builder.py's _sec_psychosis section and reactions.py's
# "hallucinating" entries are purely reactive to psychosis_state and
# safely produce nothing once it never activates. Flip back to True to
# re-enable -- no other code changes needed.
PSYCHOSIS_ENABLED = False

# Extreme-only thresholds -- deliberately far past body.py's own everyday
# "notice this need" thresholds (e.g. _HEALTH_THRESHOLDS' hunger=85):
# reaching one of these is meant to be rare and severe, not a routine
# elevated-need state.
EXTREME_HUNGER_THRESHOLD   = 92.0   # body.py hunger: 0=full, 100=starving
EXTREME_THIRST_THRESHOLD   = 12.0   # body.py hydration: 100=hydrated, 0=dehydrated -- extreme is hydration AT OR BELOW this
ENERGY_THRESHOLD           = 0.12   # body_energy(): 0=depleted, 1=full -- extreme sleep deprivation
INTOX_THRESHOLD            = 0.85   # intoxication_state alcohol/drug level, 0-1 (1.0 = full blackout per harassment.py)

SCHIZOPHRENIA_MULTIPLIER = 8.0
EPISODE_DURATION_TICKS = (3600, 14400)  # 1-4 sim-hours (TICK_RATE_SECONDS=1s/tick)
ERRATIC_BEHAVIOR_CHANCE = 0.06  # per CADENCE["health"] (30-tick) check while active

# A momentary spike past an extreme threshold isn't enough on its own --
# it has to actually persist. Each of the four triggers below tracks its
# own "been extreme continuously since tick X" onset separately (see
# psychosis_state["extreme_onset"]), and only counts toward entry once
# it's held for this long.
EXTREME_SUSTAIN_TICKS = 3 * 3600  # a few hours

_HALLUCINATION_CONTENT = [
    ("aliens",        "There's something out there -- lights, in the sky..."),
    ("ghost",          "Someone's standing right there. Watching."),
    ("shadow_figure",  "There's someone in the corner of the room."),
    ("voice",          "Did you hear that? Someone just said my name."),
    ("insects",        "Something's crawling on me -- get it off!"),
]

_MUTTER_LINES = [
    "No, no, no, that's not right...",
    "They think I don't know. I know.",
    "Stop it. Stop it. Just stop.",
    "This isn't real. This isn't real.",
    "Why won't anyone listen to me?",
]

_FREEZE_LINES = [
    "...wait. What was I just doing?",
    "Something's wrong. Something's really wrong.",
    "I can't -- I can't think straight.",
]

_ERRATIC_WANDER_RADIUS = 5


def _has_schizophrenia(c):
    return "schizophrenia" in c.get("mental_health", [])


def _update_extreme_onset(c, world, state):
    """Stamps the tick each of the four extremes FIRST became true, and
    clears it back to None the moment it stops being true -- so
    EXTREME_SUSTAIN_TICKS below is measuring one continuous stretch, not
    cumulative time. Runs every check (active episode or not, see
    tick_psychosis) so a character who's still starving when an episode
    ends doesn't have to wait through another full sustain window before
    the next one can start."""
    tick = world.get("tick", 0)
    onset = state.setdefault("extreme_onset", {})

    from systems.body import body_energy
    body = c.get("body", {})
    hunger = body.get("hunger", 0.0)
    hydration = body.get("hydration", 100.0)
    energy = body_energy(c)
    intox = c.get("intoxication_state", {})
    alcohol = intox.get("alcohol_level", 0.0)
    drug = intox.get("drug_level", 0.0)

    currently_extreme = {
        "starvation":        hunger >= EXTREME_HUNGER_THRESHOLD,
        "dehydration":       hydration <= EXTREME_THIRST_THRESHOLD,
        "sleep_deprivation": energy <= ENERGY_THRESHOLD,
        "intoxication":      alcohol >= INTOX_THRESHOLD or drug >= INTOX_THRESHOLD,
    }
    for key, is_extreme in currently_extreme.items():
        if is_extreme:
            if onset.get(key) is None:
                onset[key] = tick
        else:
            onset[key] = None

    return hunger, hydration, energy, alcohol, drug


def _sustained(onset, key, tick):
    since = onset.get(key)
    return since is not None and (tick - since) >= EXTREME_SUSTAIN_TICKS


def _interrupt_activity(c, world):
    """Psychosis doesn't let a character calmly finish what they were
    doing -- clears the current activity/queue the same way an urgent
    interruption (e.g. curiosity.py's _start_investigation) already does
    elsewhere in this codebase."""
    if c.get("activity_queue"):
        from systems.activity_queue import suspend_activity_queue
        suspend_activity_queue(c, world, reason="psychosis")
    from systems.occupancy import interrupt_activity
    interrupt_activity(c, world)


def tick_psychosis(c, world):
    """Called at a moderate per-character cadence (see sim_loop.py).
    Rolls entry/exit and forces real erratic behavior while active.

    Suppressed entirely while asleep -- a live bug report: a sleeping
    character kept speaking hallucination lines out loud (fire_incidental
    doesn't check activity/consciousness), which doesn't make sense for a
    "did you hear that" spoken reaction. Rather than converting this into
    a nightmare-specific variant (bigger, unrequested scope), this simply
    pauses the whole mechanic while asleep -- no new episode starts, no
    erratic behavior fires, and an already-active episode's clock doesn't
    advance either, so nothing about it depends on exactly when the
    character happened to fall asleep."""
    if not PSYCHOSIS_ENABLED:
        return
    if (c.get("activity") or {}).get("type") == "sleep":
        return

    state = c.setdefault("psychosis_state", {
        "active": False, "intensity": 0.0, "trigger": None, "started_tick": None,
    })
    tick = world.get("tick", 0)

    hunger, hydration, energy, alcohol, drug = _update_extreme_onset(c, world, state)

    if state["active"]:
        duration = tick - (state.get("started_tick") or tick)
        if duration > state.get("_duration", EPISODE_DURATION_TICKS[1]):
            state["active"] = False
            state["intensity"] = 0.0
            state["trigger"] = None
            state["_duration"] = None
            return
        if random.random() < ERRATIC_BEHAVIOR_CHANCE:
            _do_erratic_behavior(c, world)
        return

    onset = state["extreme_onset"]
    score = 0.0
    trigger = None
    if hunger >= EXTREME_HUNGER_THRESHOLD and _sustained(onset, "starvation", tick):
        contrib = (hunger - EXTREME_HUNGER_THRESHOLD) / (100.0 - EXTREME_HUNGER_THRESHOLD)
        if contrib > score:
            trigger = "starvation"
        score += contrib
    if hydration <= EXTREME_THIRST_THRESHOLD and _sustained(onset, "dehydration", tick):
        contrib = (EXTREME_THIRST_THRESHOLD - hydration) / EXTREME_THIRST_THRESHOLD
        if contrib > score:
            trigger = "dehydration"
        score += contrib
    if energy <= ENERGY_THRESHOLD and _sustained(onset, "sleep_deprivation", tick):
        contrib = (ENERGY_THRESHOLD - energy) / ENERGY_THRESHOLD
        if contrib > score:
            trigger = "sleep_deprivation"
        score += contrib
    if (alcohol >= INTOX_THRESHOLD or drug >= INTOX_THRESHOLD) and _sustained(onset, "intoxication", tick):
        contrib = max(alcohol, drug)
        if contrib > score:
            trigger = "intoxication"
        score += contrib

    if _has_schizophrenia(c):
        # Schizophrenia keeps its own small, always-present baseline chance
        # independent of the extremes above -- a diagnosed character can
        # still have an episode without having starved/dehydrated/stayed
        # awake/gotten drunk first, matching how the condition actually
        # works; the extremes above are what gates it for everyone else.
        score = max(score, 0.05) * SCHIZOPHRENIA_MULTIPLIER
        trigger = trigger or "schizophrenia"

    if score <= 0:
        return

    entry_chance = min(0.9, score * 0.3)
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

    _interrupt_activity(c, world)
    _do_erratic_behavior(c, world)


_ERRATIC_BEHAVIORS = ("hallucinate", "wander", "freeze", "mutter")


def _do_erratic_behavior(c, world):
    """Picks one real, disruptive behavior rather than just narrating a
    line -- an active episode now visibly derails whatever the character
    was doing, not just makes them say something spooky mid-activity."""
    behavior = random.choice(_ERRATIC_BEHAVIORS)
    if behavior == "hallucinate":
        trigger_hallucination(c, world)
    elif behavior == "wander":
        _erratic_wander(c, world)
    elif behavior == "freeze":
        _erratic_freeze(c, world)
    elif behavior == "mutter":
        _erratic_mutter(c, world)


def _erratic_wander(c, world):
    """Interrupts whatever they were doing and sets off toward a random
    nearby point -- not going anywhere in particular, just compelled to
    move. plan_character_route() already handles building/floorplan
    pathing and no-ops safely if the point isn't reachable."""
    _interrupt_activity(c, world)
    from systems.navigation import plan_character_route
    tx = c.get("x", 0) + random.randint(-_ERRATIC_WANDER_RADIUS, _ERRATIC_WANDER_RADIUS)
    ty = c.get("y", 0) + random.randint(-_ERRATIC_WANDER_RADIUS, _ERRATIC_WANDER_RADIUS)
    if plan_character_route(world, c, tx, ty):
        c["animation_state"] = "walk"
        c["is_moving"] = True
    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(c, world, "hallucinating")
    except Exception:
        pass


def _erratic_freeze(c, world):
    """Stops dead -- interrupts whatever they were doing without giving
    them anywhere new to go, unlike _erratic_wander()."""
    _interrupt_activity(c, world)
    c["is_moving"] = False
    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "exclaim", random.choice(_FREEZE_LINES), world)
    except Exception:
        pass


def _erratic_mutter(c, world):
    """Talking to someone who isn't there -- doesn't interrupt movement/
    activity on its own (the mumbling itself is the disruption)."""
    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "exclaim", random.choice(_MUTTER_LINES), world)
    except Exception:
        pass


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


def get_psychosis_context(c, world):
    """LLM narrative helper -- reinforces the mechanical erratic behavior
    above so a normal LLM-driven turn during an active episode stays
    consistent with it (confused, paranoid, not acting like themselves)
    instead of the model being the only thing that knows anything is
    wrong."""
    state = c.get("psychosis_state") or {}
    if not state.get("active"):
        return None
    trigger = state.get("trigger") or "psychosis"
    trigger_label = {
        "starvation": "you haven't eaten in a dangerously long time",
        "dehydration": "you're severely dehydrated",
        "sleep_deprivation": "you've been awake far too long",
        "intoxication": "you're extremely intoxicated",
        "schizophrenia": "your condition",
    }.get(trigger, "your condition")
    return [
        f"You're having an episode of psychosis (brought on by {trigger_label}) -- "
        "your thoughts are disorganized, you may misread what's happening around you, "
        "hear or see things that aren't there, and struggle to focus on anything for long."
    ]
