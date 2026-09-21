"""
Activity watchdog: nobody stays in one activity phase forever.

Activities finish by themselves once they reach their "using" phase and their
duration elapses. Everything else -- the walking phase, carry legs, any phase
waiting on something -- waits for a condition (is_moving clearing, a queue
turn) with no upper bound, so an unreachable target, a failed route or a lost
anchor pins the character for good. This is the general net under all of
those, checked every tick per character.

A phase that has outlived its limit is interrupted through
occupancy.interrupt_activity (which releases the prop anchor and posture),
movement is cleared, a memory records the failure, and the character is woken
with `activity_aborted` so they choose again.
"""

WALK_LIMIT_TICKS = 600            # any non-"using" phase (walking, carrying, queueing)
USING_SLACK_TICKS = 600           # "using" may overrun its own duration by this much...
USING_MAX_FACTOR = 2.0            # ...or by this multiple, whichever is larger
EXEMPT_TYPES = {"sleep"}          # sleep length is driven by fatigue/alarms, not the clock


def _limit(act):
    if act.get("phase", "using") != "using":
        return WALK_LIMIT_TICKS
    duration = act.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return None
    return max(duration * USING_MAX_FACTOR, duration + USING_SLACK_TICKS)


def check_activity_watchdog(c, world):
    """Returns True if an activity was cancelled this call."""
    act = c.get("activity")
    if not act or not act.get("type") or act.get("type") in EXEMPT_TYPES:
        c.pop("_watchdog", None)
        return False

    tick = world.get("tick", 0)
    key = [act.get("type"), act.get("target_id"), act.get("phase", "using"),
           act.get("phase_started_tick")]
    wd = c.get("_watchdog")
    if not wd or wd.get("key") != key:
        c["_watchdog"] = {"key": key, "since": tick}
        return False

    limit = _limit(act)
    if limit is None or tick - wd["since"] < limit:
        return False

    from systems.occupancy import interrupt_activity
    from brain.cognition_scheduler import wake_character
    from brain.memory import store_memory

    act_type, target = act.get("type"), act.get("target_id")
    phase = act.get("phase", "using")
    print(f"[watchdog] tick {tick}: {c.get('name', c.get('id'))} stuck {tick - wd['since']} ticks in "
          f"{act_type}/{phase} (target {target}) -- cancelling")
    interrupt_activity(c, world)
    c["is_moving"] = False
    c["move_target"] = None
    c.pop("_watchdog", None)
    label = str(act_type).replace("_", " ")
    store_memory(c, f"I couldn't get anywhere with {label} and gave up on it for now.",
                 importance=0.3, tags=["gave_up"], tick=tick, source="internal")
    wake_character(c, world, "activity_aborted",
                   {"activity": act_type, "target_id": target, "phase": phase})
    return True
