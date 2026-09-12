# =========================================================
# WAITING FOR A REASON
# Distinguishes "waiting for something specific to happen" (a person,
# a business, a delivery) from the plain "wait" activity's generic
# idle/nothing-better-to-do fallback (see action_router.py::_route_wait).
# A waiting-for-a-reason character has a patience timer -- shorter when
# stressed, longer when patient -- and accrues stress from their own
# backlog (systems/backlog.py) while blocked. When the timer runs out,
# the character is woken to reconsider (check in on the person, contact
# the business, etc.) rather than silently continuing to sit still.
# =========================================================

from systems.backlog import apply_waiting_stress
from brain.cognition_scheduler import wake_character

# Baseline patience before any trait/stress modifiers -- roughly the
# generic "wait" activity's own default duration (see
# action_router.py::_INTERACTION_DURATIONS["wait"]), since patience-driven
# waiting is meant to be in the same ballpark as an ordinary wait, not an
# order of magnitude longer or shorter.
BASE_PATIENCE_TICKS = 120

PATIENT_MODIFIER   = 1.5
IMPATIENT_MODIFIER = 0.6

# How many ticks of patience a maxed-out (100) current stress level
# removes -- current stress shortens the timer (more stressed = follows
# up sooner), scaled linearly down to 0 removed at 0 stress.
STRESS_PATIENCE_PENALTY_TICKS = 90

MIN_PATIENCE_TICKS = 20


def _patience_modifier(c):
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    if "patient" in traits:
        return PATIENT_MODIFIER
    if "impatient" in traits:
        return IMPATIENT_MODIFIER
    return 1.0


def _stress_penalty_ticks(c):
    stress = max(0, min(100, c.get("stress", 0)))
    return STRESS_PATIENCE_PENALTY_TICKS * (stress / 100)


def start_waiting_for(c, world, kind, ref):
    """Arm a patience timer on the character's current (already-scaffolded
    'wait') activity. Call right after _route_wait() sets c["activity"]."""
    act = c.get("activity")
    if not act:
        return

    timer = BASE_PATIENCE_TICKS * _patience_modifier(c) - _stress_penalty_ticks(c)
    timer = max(MIN_PATIENCE_TICKS, round(timer))

    act.setdefault("state", {})["waiting_for"] = {
        "kind": kind,          # "person" | "business" | "delivery"
        "ref": ref,             # char_id / business key / free text
        "expires_at_tick": world.get("tick", 0) + timer,
        "timed_out": False,
    }


def tick_waiting(c, world):
    """Call once per character per tick (mirrors process_health's spot in
    brain/agent_loop.py::update_internal_state). No-ops unless the
    character is currently waiting-for-a-reason."""
    act = c.get("activity")
    if not act or act.get("type") != "wait":
        return
    waiting_for = act.get("state", {}).get("waiting_for")
    if not waiting_for or waiting_for.get("timed_out"):
        return

    apply_waiting_stress(c, world)

    if world.get("tick", 0) >= waiting_for["expires_at_tick"]:
        kind = waiting_for["kind"]

        # Per the user's ask: waiting on an occupied appliance (the only
        # instance of it, per systems/interactions.py::begin_interaction's
        # queueing path) escalates into real banging on the door instead
        # of just quietly re-checking -- a visible, audible cue rather
        # than a silent cognition-only wake, and genuinely repeats (a
        # fresh, shorter patience timer) rather than a one-off event, so
        # persistent occupancy reads as mounting impatience.
        if kind == "prop":
            from systems.incidental_speech import fire_incidental
            bang_count = waiting_for.get("bang_count", 0) + 1
            waiting_for["bang_count"] = bang_count
            text = "Hurry up in there!" if bang_count == 1 else "Come ON, seriously?!"
            fire_incidental(c, "inform", f"*bangs on the door* {text}", world)
            c["stress"] = min(100, c.get("stress", 0) + 4 * bang_count)

            # Re-arm a shorter timer (escalating urgency) instead of a
            # one-shot timeout -- still occupied means still banging.
            waiting_for["expires_at_tick"] = world.get("tick", 0) + max(MIN_PATIENCE_TICKS, round(BASE_PATIENCE_TICKS * 0.5))
        else:
            waiting_for["timed_out"] = True

        wake_character(c, world, "waiting_timed_out", {
            "kind": waiting_for["kind"],
            "ref":  waiting_for["ref"],
        })
