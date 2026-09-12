"""
systems/director_mode.py

Backend primitives for "director mode" -- live micro-management of a
character mid-scene from outside the simulation's own AI loop, requested
as the core of VR/operator_view Phase 1 (see the scoping conversation).
Deliberately headset-agnostic: both the eventual WebXR controller input
and a plain desktop admin page (api/director.py) call these same
functions, so the mechanism is provable without a headset.

Four real ops, all logged to world["director_log"] so a session's
interventions stay visible/auditable:

  start_director_session(c, world)        -- opens a session on c, staging
                                              area for set_preference() below
  interrupt_attention(c, world)           -- pauses whatever c is doing and
                                              wakes them with top priority,
                                              so their next think() notices
                                              the director
  inject_line(c, world, text)             -- puts a real line in c's mouth
                                              right now (the same apply_speech
                                              pipeline any other character's
                                              speech goes through) -- "here's
                                              an argument to use"
  set_preference(c, world, field, value)  -- STAGES a change to an existing
                                              top-level character field;
                                              not applied until...
  end_director_session(c, world)          -- ...this commits every staged
                                              change and closes the session,
                                              matching the VR ask ("save the
                                              changes you made" on release)

Only top-level fields that already exist on the character can be staged
via set_preference -- this is a deliberately narrow, safe primitive (no
nested paths, no inventing new fields) rather than an arbitrary character
mutator; broadening it is a Phase 2+ concern once real usage shows what's
actually needed.

interrupt_attention() does NOT go through activity_queue.py's hobby-
suspend machinery (suspend_activity_queue) -- that path exists specifically
to preserve a resumable hobby session with its own decaying-importance
resume desire, which doesn't apply to an arbitrary director interruption.
This just clears the activity gate and wakes the character; a hobby they
were mid-session on is not automatically resumed afterward, a real, small,
documented scope gap rather than a silent one.
"""

import uuid

from brain.cognition_scheduler import wake_character

DIRECTOR_WAKE_REASON = "director_attention"


def _log(world, char_id, op, detail):
    entry = {
        "id":     f"dirlog_{uuid.uuid4().hex[:8]}",
        "tick":   world.get("tick", 0),
        "char_id": char_id,
        "op":     op,
        "detail": detail,
    }
    log = world.setdefault("director_log", [])
    log.append(entry)
    del log[:-200]
    return entry


def start_director_session(c, world):
    """Opens (or returns the existing) staging area for this character.
    Idempotent -- selecting an already-under-direction character again
    doesn't reset pending changes."""
    session = c.get("_director_session")
    if session is None:
        session = {"started_tick": world.get("tick", 0), "pending_changes": {}}
        c["_director_session"] = session
        _log(world, c["id"], "start_session", {})
    return session


def interrupt_attention(c, world):
    """Pauses whatever c is doing and wakes them with top priority so
    their next think() notices the director. See module docstring for
    why this doesn't use activity_queue.py's hobby-suspend path."""
    start_director_session(c, world)
    from systems.occupancy import interrupt_activity
    interrupt_activity(c, world)
    wake_character(c, world, DIRECTOR_WAKE_REASON)
    _log(world, c["id"], "interrupt_attention", {})


def inject_line(c, world, text):
    """Puts a real line in c's mouth right now, via the same apply_speech
    pipeline any other character's speech goes through -- "here's an
    argument to use," delivered immediately rather than queued for a
    later LLM turn to decide on."""
    text = (text or "").strip()
    if not text:
        return False
    start_director_session(c, world)
    from systems.action_router import apply_speech
    apply_speech(c, world, {
        "speech_act": "declare",
        "topic": "director_line",
        "utterance": text,
    })
    _log(world, c["id"], "inject_line", {"text": text})
    return True


_STAGEABLE_VALUE_TYPES = (str, int, float, bool, list, dict, type(None))


def set_preference(c, world, field, value):
    """Stages a change to an existing top-level character field -- only
    applied once end_director_session() commits it (Confirmed scope: a
    director's edits take effect once directors mode ends, not
    immediately). Refuses to stage a field that doesn't already exist on
    the character, or a value of a type schema_defaults.py wouldn't have
    produced -- a narrow, safe primitive, not an arbitrary mutator."""
    if field not in c:
        return False
    if not isinstance(value, _STAGEABLE_VALUE_TYPES):
        return False
    session = start_director_session(c, world)
    session["pending_changes"][field] = value
    _log(world, c["id"], "stage_preference", {"field": field})
    return True


def call_attention_radius(world, x, y, radius):
    """VR director-mode primitive: every living, on-grid character within
    `radius` tiles of (x, y) -- the director's own position, holding the
    gesture button long enough to trigger this -- gets interrupt_attention()
    called on them (pauses what they're doing, wakes them so their next
    think() actually notices the director). Turning to visually FACE the
    director is left to the frontend (frontend/src/operator_view.js) --
    character facing is purely a derived-from-recent-movement render
    detail in main.js, there's no persisted "facing" field on the
    character to set here, so this returns the affected ids and lets the
    caller handle the visual turn directly. Returns the list of affected
    character ids."""
    affected = []
    for other in world.get("characters", {}).values():
        if not other.get("alive", True) or other.get("off_grid"):
            continue
        dx = other.get("x", 0) - x
        dy = other.get("y", 0) - y
        if (dx * dx + dy * dy) ** 0.5 <= radius:
            interrupt_attention(other, world)
            affected.append(other["id"])
    _log(world, None, "call_attention_radius", {"x": x, "y": y, "radius": radius, "affected": affected})
    return affected


def end_director_session(c, world):
    """Commits every staged change and closes the session. Returns the
    dict of fields actually changed (empty if nothing was staged)."""
    session = c.get("_director_session")
    if not session:
        return {}
    changes = session.get("pending_changes", {})
    for field, value in changes.items():
        c[field] = value
    c["_director_session"] = None
    _log(world, c["id"], "end_session", {"fields_changed": list(changes.keys())})
    return changes
