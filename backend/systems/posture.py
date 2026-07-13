"""
systems/posture.py

Body-stance transitions: standing, sitting_seat, sitting_floor, lying,
crouching, crawling, fallen_front, fallen_back, leaning_wall, unconscious,
dead, intoxicated. (Dragging/pushing are NOT posture values — they're a
separate, prop-attachment-driven mechanic, see systems/prop_movement.py
and movement.py; their animation resolution is authored in animbank the
same way, but through main.js's _STANCE_IDLE_KEY, not through this file.)

set_posture() is the single entry point every route/activity should use to
change a character's posture — it updates c["posture"] immediately, and
drives c["animation_state"] through a one-shot "{old}_to_{new}" transition
key before settling into the new posture's idle animation a fixed number
of ticks later (promote_pending_posture(), called once per character per
tick from brain/agent_loop.py, mirrors clear_expired_speech()'s pattern in
action_router.py).

The frontend resolves both the transition key and the idle key through a
character's per-source animbank mapping (main.js's resolveLocomotionMap(),
fed by animbank.js's Stances/Transitions panels) — if nothing was authored
for a given pair, the transition key simply falls back to whatever
ANIM_LAYERS/_playSingleAction already do with an unrecognized key, so an
un-authored transition doesn't error, it just cuts less gracefully.

The stance vocabulary itself (which postures exist, each one's idle key)
lives in definitions.json's "stance_templates" category, not hardcoded
here — see _idle_key() below. This is the same vocabulary animbank.js's
Stances panel and main.js's _STANCE_IDLE_KEY/_STANCE_MOVE_KEY read, so
adding a new posture (or a new animation-override slot like carry) is a
data edit in the Definitions editor, not a change in three separate
files.
"""

# Fixed placeholder — the backend has no visibility into how long an
# authored transition clip actually runs (that lives in animbank/GLB
# metadata, frontend-only), so this is a flat guess, not derived from any
# real clip duration.
_POSTURE_SETTLE_TICKS = 15


def _idle_key(world, posture):
    """Look up a posture's idle animation_state from stance_templates.
    Only entries with is_posture=true are real c["posture"] values (carry/
    dragging/pushing are animation-override slots driven by other
    character fields, not posture — see the module docstring). Cheap
    enough (~15 entries) not to need its own cache; world["definitions"]
    is already refreshed every tick (main.py::_run_tick_and_persist)."""
    stances = (world.get("definitions") or {}).get("stance_templates") or {}
    entry = stances.get(posture)
    if entry and entry.get("is_posture"):
        return entry.get("idle_key", "idle")
    return "idle"


def set_posture(c, world, new_posture):
    """
    Transition a character to a new posture.

    Updates c["posture"] immediately. If the posture actually changed,
    also writes the "{old}_to_{new}" transition key to c["animation_state"]
    and arms a pending-settle marker so promote_pending_posture() flips it
    to the new posture's idle animation after _POSTURE_SETTLE_TICKS,
    unless something else has changed animation_state in the meantime.
    """
    old_posture = c.get("posture", "standing")
    c["posture"] = new_posture
    if old_posture == new_posture:
        return

    transition_key = f"{old_posture}_to_{new_posture}"
    c["animation_state"] = transition_key
    c["_posture_settle"] = {
        "expected_state": transition_key,
        "target_idle":    _idle_key(world, new_posture),
        "ready_at_tick":  world.get("tick", 0) + _POSTURE_SETTLE_TICKS,
    }


def promote_pending_posture(c, world):
    """
    Call once per character per tick. Settles animation_state into the
    target idle once the fixed settle window has elapsed — but only if
    nothing else has since overwritten animation_state (so a
    mid-transition interrupt, e.g. sitting down interrupted by an urgent
    need, doesn't get clobbered back to an idle pose that no longer
    matches what actually happened).
    """
    pending = c.get("_posture_settle")
    if not pending:
        return
    if world.get("tick", 0) < pending["ready_at_tick"]:
        return
    if c.get("animation_state") == pending["expected_state"]:
        c["animation_state"] = pending["target_idle"]
    c["_posture_settle"] = None
