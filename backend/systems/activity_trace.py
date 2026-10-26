"""
systems/activity_trace.py -- an activity carries its own history, and is remembered once, as a whole.

Every step of an activity used to be written to the character's memory as its own line ("started", "reached target", "interrupted",
...), which buried the one thing worth knowing: what happened, how long it took, and why it ended. Now:

  * while it runs, the activity dict itself holds
        act["steps"]     the plan: [{"name", "label", "done_tick", "done_clock"}], ticked off as the activity gets there
        act["timeline"]  what happened, in order: [{"tick", "clock", "step", ...detail}]
  * when it ends (done, interrupted, replaced, timed out) it is closed into ONE memory (kind "activity") holding the whole record
    under `activity_record`: type, target, planned and actual length, outcome, reason, steps with the tick each was reached, timeline.

    begin(c, world)                  an activity has just started (the activity_started event)
    note(act, world, step, **detail) one more entry on the timeline
    step_done(act, world, name)      tick a planned step off
    close(c, world, outcome, reason) write the record to memory; outcome: completed | interrupted | replaced | timed_out
"""

TIMELINE_CAP = 40


def _clock(world):
    cal = world.get("calendar", {})
    return f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"


def _label(act):
    kind = act.get("interaction") if act.get("type") == "interact" and act.get("interaction") else act.get("type")
    return str(kind or "activity").replace("_", " ")


def _target_name(world, act):
    from systems.debug_log import _resolve_target_name
    return _resolve_target_name(world, act.get("target_id")) if act.get("target_id") else None


def _minutes(ticks):
    return max(1, round(ticks / 60)) if ticks else 0


def planned_steps(act, world):
    target = _target_name(world, act)
    steps = []
    if act.get("phase") == "walking":
        steps.append({"name": "walk", "label": f"walk to {target}" if target else "walk to it"})
    steps.append({"name": "use", "label": f"{_label(act)} (about {_minutes(act.get('duration') or 0)} min)"})
    steps.append({"name": "finish", "label": "wrap up"})
    for s in steps:
        s["done_tick"] = None
        s["done_clock"] = None
    return steps


def note(act, world, step, **detail):
    if not act:
        return
    timeline = act.setdefault("timeline", [])
    entry = {"tick": world.get("tick", 0), "clock": _clock(world), "step": step}
    entry.update({k: v for k, v in detail.items() if v not in (None, "")})
    timeline.append(entry)
    if len(timeline) > TIMELINE_CAP:
        del timeline[1:len(timeline) - TIMELINE_CAP + 1]


def step_done(act, world, name):
    for s in (act or {}).get("steps") or []:
        if s["name"] == name and s.get("done_tick") is None:
            s["done_tick"], s["done_clock"] = world.get("tick", 0), _clock(world)
            return


def phase_changed(act, old, new, world):
    """Called from systems/activities.py::set_activity_phase."""
    if "steps" not in act:
        return
    if old == "walking" and new != "walking":
        step_done(act, world, "walk")
    if new == "finishing":
        step_done(act, world, "use")


def begin(c, world):
    act = c.get("activity")
    if not act or act.get("timeline") is not None:
        return
    leftover = c.pop("_trace_open", None)
    if leftover and leftover is not act and not leftover.get("_closed"):
        _write(c, world, leftover, "replaced", c.get("_interrupt_reason") or f"replaced by {_label(act)}")
    act["started_tick"] = world.get("tick", 0)
    act["steps"] = planned_steps(act, world)
    act["timeline"] = []
    note(act, world, "started", target=_target_name(world, act), planned_minutes=_minutes(act.get("duration") or 0))
    c["_trace_open"] = act


def close(c, world, outcome, reason=None):
    act = c.get("activity") or c.get("_trace_open")
    if not act or act.get("_closed"):
        return
    _write(c, world, act, outcome, reason)
    c.pop("_trace_open", None)


def _write(c, world, act, outcome, reason):
    act["_closed"] = True
    tick = world.get("tick", 0)
    started = act.get("started_tick", act.get("phase_started_tick", tick))
    if outcome == "completed":
        step_done(act, world, "walk")
        step_done(act, world, "use")
        step_done(act, world, "finish")
    note(act, world, outcome, reason=reason)
    actual, planned = max(0, tick - started), act.get("duration") or 0
    target = _target_name(world, act)
    label = _label(act)
    text = (f"{label.capitalize()}{f' ({target})' if target else ''}: {outcome.replace('_', ' ')} after {_minutes(actual) or '<1'} min"
            f" of {_minutes(planned) or '?'} planned" + (f" -- {reason}" if reason else ""))
    record = {
        "type": act.get("type"), "interaction": act.get("interaction"), "target_id": act.get("target_id"), "target": target,
        "anchor": act.get("anchor_name"), "started_tick": started, "ended_tick": tick, "planned_ticks": planned,
        "actual_ticks": actual, "outcome": outcome, "reason": reason,
        "steps": [dict(s) for s in act.get("steps") or []], "timeline": list(act.get("timeline") or []),
    }
    from brain.memory import store_memory
    store_memory(c, text, importance=0.2 if outcome == "completed" else 0.3, tags=["activity", outcome], kind="activity", tick=tick,
                 activity_type=act.get("type"), interaction=act.get("interaction"), anchor_name=act.get("anchor_name"),
                 target_id=act.get("target_id"), target_name=target, activity_record=record, source="internal")
