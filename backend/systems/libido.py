"""
systems/libido.py

Standalone sexual-release need, deliberately separate from
intimacy.py's relationship-scoped arousal_level (which only rises from
partnered contact, per-pair). Rather than a steady drip, this models
"hornier than usual" days: a small daily roll into a multi-day spike,
weighted by the character's own attraction_profile.libido. What a
spiking character actually DOES about it (spouse first, then a booty
call, then masturbation with privacy) lives in systems/sexual_release.py
-- this module is just the need itself, its build-up, and its context
narration.

c["libido_state"] = {
    "baseline":          0-1, slow personal average, seeded from
                          attraction_profile.libido,
    "current":            0-1, today's actual level (baseline + spike),
    "spike_until_tick":   int | None,
    "denied_count":       consecutive failed release attempts THIS
                          spike (systems/sexual_release.py bumps this;
                          feeds stress and, eventually, the Phase D
                          prostitute-hiring gate),
    "last_release_tick":  int | None,
}

Day-gated by world["calendar"]'s actual date (mirrors
systems/expectations.py's period-key approach) rather than a raw tick
count -- this codebase's CADENCE constants don't reliably mean what
their comments claim in real elapsed time (confirmed inconsistent
against TICK_RATE_SECONDS=1 elsewhere this session), so "roll once per
day" is gated on the calendar actually advancing a day, decoupled from
however often sim_loop happens to call tick_libido().
"""

import random

SPIKE_DAILY_CHANCE_BASE = 0.04     # per sim-day, scaled by libido below
SPIKE_DURATION_DAYS     = (2, 5)
SPIKE_BONUS             = 0.4
DENIAL_STRESS_DELTA     = 4.0
TICKS_PER_DAY           = 86400    # 1 tick == 1 sim-second, confirmed elsewhere this session

SEEK_RELEASE_THRESHOLD  = 0.55


def _day_key(calendar):
    if not calendar:
        return None
    return f"{calendar.get('year', 0):04d}-{calendar.get('month', 0):02d}-{calendar.get('day', 0):02d}"


def ensure_libido_state(c):
    base = (c.get("attraction_profile") or {}).get("libido", 0.5)
    return c.setdefault("libido_state", {
        "baseline":          base,
        "current":           base,
        "spike_until_tick":  None,
        "denied_count":      0,
        "last_release_tick": None,
        "_last_roll_day":    None,
    })


def is_spiking(c):
    return bool((c.get("libido_state") or {}).get("spike_until_tick"))


def tick_libido(world):
    """Call on any reasonably frequent cadence (see sim_loop.py) -- the
    actual once-per-day roll is gated internally by calendar date, not
    by call frequency."""
    calendar = world.get("calendar", {})
    day_key = _day_key(calendar)
    if day_key is None:
        return
    tick = world.get("tick", 0)

    for c in world.get("characters", {}).values():
        if c.get("is_offscreen") or c.get("age_group") in ("child", "teen"):
            continue
        state = ensure_libido_state(c)

        if state.get("spike_until_tick") and tick >= state["spike_until_tick"]:
            state["spike_until_tick"] = None
            state["denied_count"] = 0

        if state.get("_last_roll_day") != day_key:
            state["_last_roll_day"] = day_key
            libido_trait = (c.get("attraction_profile") or {}).get("libido", 0.5)
            if not state.get("spike_until_tick"):
                if random.random() < SPIKE_DAILY_CHANCE_BASE * (0.3 + libido_trait):
                    days = random.randint(*SPIKE_DURATION_DAYS)
                    state["spike_until_tick"] = tick + days * TICKS_PER_DAY

        state["current"] = round(min(1.0, state["baseline"] +
                                      (SPIKE_BONUS if state.get("spike_until_tick") else 0.0)), 3)

        if state["current"] >= SEEK_RELEASE_THRESHOLD:
            from systems.persistent_desires import add_desire
            add_desire(c, "seek_sexual_release", importance=state["current"])

            # Autonomous, once-per-day attempt while spiking -- mirrors
            # this codebase's existing pattern of AI-computed-but-
            # automatically-applied background drives (e.g.
            # attraction.py::recipient_decision(), tick_domestic_control())
            # rather than requiring a dedicated LLM action every roll.
            # See systems/sexual_release.py for the actual cascade.
            try:
                from systems.sexual_release import attempt_release
                attempt_release(c, world)
            except Exception:
                pass


def note_denied(c, world):
    """A release attempt (spouse unwilling, no FWB prospects, or no
    privacy for masturbation) failed -- see systems/sexual_release.py.
    Builds real stress, the gate Phase D's prostitute-hiring desire
    watches."""
    state = ensure_libido_state(c)
    state["denied_count"] = state.get("denied_count", 0) + 1
    c["stress"] = min(100.0, c.get("stress", 0.0) + DENIAL_STRESS_DELTA)


def note_released(c, world):
    state = ensure_libido_state(c)
    state["denied_count"] = 0
    state["last_release_tick"] = world.get("tick", 0)
    state["spike_until_tick"] = None
    state["current"] = state["baseline"]


def get_libido_context(c, world, listener=None):
    """LLM context -- only narrates anything while actually spiking.
    listener: pass the other conversation participant to get the
    same-sex-only cruder/sexist-remark hint (impulse_state["sexism_level"]
    already exists, drifted by harassment.py::on_porn_session(); this is
    the first thing that ever reads it back into context)."""
    state = c.get("libido_state") or {}
    if not state.get("spike_until_tick"):
        return {}

    lines = [
        "feeling unusually horny lately -- more likely to flirt, pursue a "
        "partner, or want to attend social situations hoping to meet someone"
    ]
    if listener and listener.get("sex") == c.get("sex"):
        sexism = c.get("impulse_state", {}).get("sexism_level", 0.0)
        if sexism > 0.15:
            lines.append(
                "talking to someone of the same sex -- might make cruder, more "
                "sexist remarks or suggestions about pursuing women/men, or "
                "suggest going out somewhere together to try to meet someone"
            )
    return {"libido": lines}
