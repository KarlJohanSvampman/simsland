"""
systems/loop_guard.py

Catches a character stuck repeating the same activity -- and makes them notice.

A real bug (a child dusting a spotless house for ten hours while starving) went
unseen because every individual step was legitimate: an intention resolved to an
activity, the activity finished, the intention was still there. Nothing looked at
the PATTERN. This does:

  1. Every activity start is recorded (systems/loop_guard.note_start, from the
     activity_started event).
  2. A red flag is the same activity started LOOP_RUN_MIN times in a row within
     LOOP_WINDOW_TICKS, or two activities alternating A,B,A,B,A,B.
  3. The character is made to break the pattern at once, deterministically:
     the running activity is interrupted, the intention that kept dispatching it
     is dropped and recorded in c["failed_intentions"] as an erratic-behaviour
     failure, and (for non-vital intentions) it can't be re-added for a while.
  4. They then reflect on it: a background self-assessment call (llm/
     self_assessment.py) writes a first-person thought about why. That thought is
     attached to the failure record, stored as a memory, and wakes the character
     so their next decision starts from it. It is also a debugging trace -- what
     the character thinks is going on -- along with a snapshot of their state.

The reflection never blocks the break: if the model is unavailable the character
still stops, with a plain fallback thought.
"""

LOOP_RUN_MIN = 4
LOOP_ALTERNATE_MIN = 6
LOOP_WINDOW_TICKS = 4000
LOOP_COOLDOWN_TICKS = 3000      # don't re-flag the same activity this soon
SUPPRESS_TICKS = 1800           # a dropped (non-vital) intention can't come straight back
ASSESS_TIMEOUT_TICKS = 900      # no answer by then -> fallback thought
HISTORY_CAP = 12
FAILED_CAP = 20

_EXEMPT = {"wait", "sleep", "take_nap", "work", "socialize"}
_VITAL = {"survival", "health"}


def _pattern(history):
    """(kind, activity or [A, B], count) for a red-flag pattern ending at the latest
    start, else None. history entries: [tick, activity, intention]."""
    if not history:
        return None
    last_tick = history[-1][0]
    window = [h for h in history if last_tick - h[0] <= LOOP_WINDOW_TICKS]
    types = [h[1] for h in window]
    if not types or types[-1] in _EXEMPT:
        return None
    run = 0
    for t in reversed(types):
        if t != types[-1]:
            break
        run += 1
    if run >= LOOP_RUN_MIN:
        return ("repeat", types[-1], run)
    if len(types) >= LOOP_ALTERNATE_MIN:
        tail = types[-LOOP_ALTERNATE_MIN:]
        a, b = tail[-2], tail[-1]
        if a != b and not ({a, b} & _EXEMPT) and all(tail[i] == (a if i % 2 == 0 else b) for i in range(len(tail))):
            return ("alternate", [a, b], LOOP_ALTERNATE_MIN)
    return None


def note_start(c, world, activity_type):
    """Record an activity start and trip the guard if it completes a pattern."""
    if not activity_type or c.get("is_workplace_npc") or c.get("is_service_worker"):
        return None
    tick = world.get("tick", 0)
    intention = (c.get("current_intention") or {}).get("type")
    history = c.setdefault("_activity_starts", [])
    history.append([tick, activity_type, intention])
    del history[:-HISTORY_CAP]
    found = _pattern(history)
    if not found:
        return None
    kind, what, count = found
    key = what if isinstance(what, str) else "|".join(what)
    flagged = c.setdefault("_loop_flagged", {})
    if tick - flagged.get(key, -10**9) < LOOP_COOLDOWN_TICKS:
        return None
    flagged[key] = tick
    return trip(c, world, kind, what, count)


# ── breaking the pattern ──────────────────────────────────────────────────────

def _situation(c, world):
    """A compact, honest snapshot of what the character is dealing with -- the
    raw material for their reflection and the debugging trace."""
    body = c.get("body") or {}
    bits = []
    for label, key, bad_high in (("hunger", "hunger", True), ("tiredness", "energy", False),
                                 ("hygiene", "hygiene", False), ("bladder", "bladder", True)):
        v = body.get(key)
        if isinstance(v, (int, float)):
            if bad_high and v >= 70:
                bits.append(f"very high {label} ({round(v)}/100)")
            elif not bad_high and v <= 25:
                bits.append(f"very low {key} ({round(v)}/100)")
    from brain.intentions import final_priority
    top = sorted(c.get("active_intentions", []), key=lambda i: final_priority(i, c), reverse=True)[:5]
    wants = [f"{i.get('type')} ({i.get('reason') or i.get('source') or 'no reason'})" for i in top]
    lines = []
    if bits:
        lines.append("Your body: " + ", ".join(bits) + ".")
    if wants:
        lines.append("Things on your mind: " + "; ".join(wants) + ".")
    lines.append(f"It is {world.get('calendar', {}).get('hour', '?')}:00.")
    return "\n".join(lines)


def _intention_for(c, world, activity_types):
    """The intention that kept dispatching this activity: the one recorded when it
    started, else whichever current intention resolves to it."""
    starts = c.get("_activity_starts") or []
    for _t, act, intention in reversed(starts):
        if act in activity_types and intention:
            return intention
    from systems.strategy import resolve_strategy
    for i in c.get("active_intentions", []):
        try:
            if resolve_strategy(c, world, i) in activity_types:
                return i.get("type")
        except Exception:
            continue
    return None


def trip(c, world, kind, what, count):
    from brain.intentions import remove_intention
    from brain.memory import store_memory
    from brain.cognition_scheduler import wake_character
    from systems.occupancy import interrupt_activity

    tick = world.get("tick", 0)
    activities = [what] if isinstance(what, str) else list(what)
    label = " and ".join(a.replace("_", " ") for a in activities)
    history = c.get("_activity_starts") or []
    span = max(1, history[-1][0] - history[-min(count, len(history))][0]) if history else 1
    intention_type = _intention_for(c, world, set(activities))
    intention = next((i for i in c.get("active_intentions", []) if i.get("type") == intention_type), None)
    category = (intention or {}).get("category")
    reason = (intention or {}).get("reason")

    # 1. stop doing it
    if (c.get("activity") or {}).get("type") in activities:
        interrupt_activity(c, world)
        c["is_moving"] = False
        c["move_target"] = None
    c["current_intention"] = None

    # 2. drop the intention that kept dispatching it, as a recorded failure
    record = {
        "id": f"loop_{tick}", "tick": tick, "kind": kind, "activity": label, "count": count,
        "span_ticks": span, "intention": intention_type, "category": category,
        "reason": "erratic_behavior", "thought": None, "instead": None,
        "situation": _situation(c, world), "status": "pending",
    }
    if intention_type:
        remove_intention(c, intention_type)
        if category not in _VITAL:
            c.setdefault("_intention_suppressed", {})[intention_type] = tick + SUPPRESS_TICKS
    c.setdefault("failed_intentions", []).append(record)
    del c["failed_intentions"][:-FAILED_CAP]
    c["_loop_assessment"] = {"record_id": record["id"], "tick": tick, "activity": activities[0],
                             "count": count, "minutes": max(1, round(span / 60)),
                             "reason": reason, "submitted": False}

    # 3. immediate fallback memory; the real thought replaces it when it arrives
    from llm.self_assessment import fallback_thought
    store_memory(c, f"I caught myself doing {label} over and over ({count} times) and dropped it"
                    + (f" -- I'd been telling myself: {reason}." if reason else "."),
                 importance=0.5, tags=["self_assessment", "erratic", "gave_up"], tick=tick, source="internal")
    print(f"[loop_guard] tick {tick}: {c.get('name', c.get('id'))} repeated {label} x{count} "
          f"in {span} ticks (intention {intention_type}) -- dropped, self-assessing")
    wake_character(c, world, "self_assessment", {"thought": fallback_thought(activities[0], count, reason)})
    return record


# ── the reflection ────────────────────────────────────────────────────────────

def _apply(c, world, assess, thought, instead):
    from brain.memory import store_memory
    from brain.cognition_scheduler import wake_character
    tick = world.get("tick", 0)
    rec = next((r for r in c.get("failed_intentions", []) if r.get("id") == assess["record_id"]), None)
    if rec:
        rec["thought"], rec["instead"], rec["status"] = thought, instead, "assessed"
    store_memory(c, f"(thinking to myself) {thought}", importance=0.55,
                 tags=["self_assessment", "thought"], tick=tick, source="internal")
    c.pop("_loop_assessment", None)
    wake_character(c, world, "self_assessment", {"thought": thought})


def service(c, world):
    """Per-character, every few ticks: submit the reflection, collect the answer,
    fall back if it never comes. Request lives in c["_loop_assessment"] so a
    restart simply re-submits."""
    a = c.get("_loop_assessment")
    if not a:
        return
    from systems import bg_llm
    from llm.self_assessment import assess, fallback_thought
    tick = world.get("tick", 0)
    key = f"selfassess:{c['id']}:{a['record_id']}"
    rec = next((r for r in c.get("failed_intentions", []) if r.get("id") == a["record_id"]), {})
    if not bg_llm.is_pending(key) and tick - a["tick"] <= ASSESS_TIMEOUT_TICKS:
        bg_llm.submit(key, assess, c.get("name") or "someone", c.get("age"), a["activity"], a["count"],
                      a["minutes"], a.get("reason"), rec.get("situation") or "")
        return
    ready, result = bg_llm.take(key)
    if ready:
        if result:
            _apply(c, world, a, result["thought"], result.get("instead"))
        else:
            _apply(c, world, a, fallback_thought(a["activity"], a["count"], a.get("reason")), None)
        return
    if tick - a["tick"] > ASSESS_TIMEOUT_TICKS:
        _apply(c, world, a, fallback_thought(a["activity"], a["count"], a.get("reason")), None)


def service_all(world):
    for c in world.get("characters", {}).values():
        if c.get("_loop_assessment"):
            try:
                service(c, world)
            except Exception as exc:
                print(f"[loop_guard] assessment error for {c.get('id')}: {exc}")
