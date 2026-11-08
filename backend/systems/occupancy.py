def find_free_anchor(prop, interaction):

    for a in prop.get("anchors", []):
        if a.get("interaction") == interaction and not a.get("occupied_by"):
            return a

    return None


def reserve_anchor(c, prop, anchor):

    anchor["occupied_by"] = c["id"]
    anchor.setdefault("queue", [])
    c["occupying"] = {
        "prop_id": prop["id"],
        "anchor_name": anchor["name"]
    }


def enqueue_anchor(c, prop, anchor):
    anchor.setdefault("queue", [])
    if c["id"] not in anchor["queue"]:
        anchor["queue"].append(c["id"])

CALLER_REASONS = {
    "systems.curiosity": "something caught their attention",
    "systems.loop_guard": "they were stuck repeating the same thing",
    "systems.social": "a conversation started",
    "systems.travel": "they set off on a trip",
    "systems.whereabouts": "they left home",
    "systems.psychosis": "a psychotic episode",
    "systems.claustrophobia": "a wave of claustrophobia",
    "systems.worry_breakdown": "they broke down under their worries",
    "systems.worry_relief": "they were too worried to carry on",
    "systems.reading_process": "the reading ended",
    "systems.activity_watchdog": "it stalled",
    "systems.step_timeouts": "it got stuck",
    "systems.director_mode": "the admin took over",
    "api.admin": "the admin reset it",
}


def _caller_reason():
    import sys
    frame = sys._getframe(2)
    module = frame.f_globals.get("__name__", "?")
    return CALLER_REASONS.get(module) or f"cut off by {module}.{frame.f_code.co_name}"


def interrupt_activity(c, world, reason=None, outcome="interrupted"):
    """Confirmed live bug: at least a dozen call sites across this
    codebase clear a character's activity directly (`c["activity"] =
    None`) to interrupt it -- a conversation starting, curiosity
    pulling them away, claustrophobia, psychosis, travel departing,
    etc. -- without releasing whatever prop anchor that activity had
    reserved (systems/interactions.py::begin_interaction() reserves one
    for every interaction-based activity: use_toilet, take_shower,
    wash_hands, ...). complete_activity()'s own release_anchor() call
    only fires on a NATURAL finish, so an interrupted use_toilet left
    the toilet permanently "occupied_by" someone who'd since wandered
    off elsewhere entirely, silently blocking everyone else forever
    (confirmed live: a queued character never got their turn because
    the anchor they were waiting on was never actually freed). Use this
    instead of a bare `c["activity"] = None` anywhere an activity is
    being interrupted rather than completing normally.

    Second confirmed live bug, same root cause: this never reset
    c["posture"] either -- a character interrupted mid-sleep (posture
    "lying") and sent off on a trip (travel.py:93-94 calls this right
    before departure) kept showing "lying" the whole time they were
    walking to/waiting for the bus, since travel's own frozen
    travel_state states skip update_internal_state's normal posture
    processing entirely (see interrupt_travel_for_incapacitation's own
    docstring). Reset here, once, at the moment of interruption --
    exactly mirrors activities.py's use_toilet-completion posture fix."""
    # Confirmed live bug (player report: a character gave up mid-"drink
    # water", still 0% hydrated, with zero trace of it -- no debug
    # bubble, no memory, the intention never marked as anything other
    # than pending): this shared interrupt path -- used by well over a
    # dozen call sites (a conversation starting, curiosity, travel
    # departing, work priority, ...) -- never logged the interruption at
    # all. debug_log.py's activity_started/completed events already
    # exist for the other two lifecycle points; this is the missing
    # third one.
    act = c.get("activity") or {}
    act_type = act.get("type")
    if act_type:
        reason = reason or c.pop("_interrupt_reason", None) or _caller_reason()
        from systems.debug_log import log_activity
        log_activity(c, world, act_type, "ended" if outcome == "completed" else "interrupted", target_id=act.get("target_id"),
                    interaction=act.get("interaction"), anchor_name=act.get("anchor_name"), reason=reason)
        from systems.activity_trace import close
        close(c, world, outcome, reason)
        from core.event_bus import emit
        emit("activity_interrupted", {
            "character_id": c["id"], "activity_type": act_type,
            "target_id": act.get("target_id"), "anchor_name": act.get("anchor_name"),
            "x": c.get("x"), "y": c.get("y"), "building_id": c.get("building_id"), "reason": reason,
        })

    release_anchor(c, world)
    drop_carried_prop(c, world)
    c["activity"] = None
    from systems.posture import set_posture
    set_posture(c, world, "standing")


def drop_carried_prop(c, world):
    """Put down a prop the character is carrying where they stand. A carry
    that is interrupted (or cancelled by the activity watchdog) otherwise left
    the prop hidden and attached to them forever -- the world copy is invisible
    while carried_by is set."""
    prop_id = c.get("carrying")
    if not prop_id:
        return
    c.pop("carrying", None)
    for p in world.get("props", []):
        if p.get("id") == prop_id and p.get("carried_by") == c.get("id"):
            p["x"], p["y"] = c.get("x", p.get("x")), c.get("y", p.get("y"))
            p.pop("carried_by", None)
            p["visible"] = True
            break


def release_orphan_carried_props(world):
    """Safety net: a prop marked carried_by someone who isn't carrying it (or
    who no longer exists) is put back in the world where its carrier stands."""
    chars = world.get("characters", {})
    for p in world.get("props", []):
        holder_id = p.get("carried_by")
        if not holder_id:
            continue
        holder = chars.get(holder_id)
        carrying_now = (
            holder
            and holder.get("carrying") == p.get("id")
            and (holder.get("activity") or {}).get("interaction") == "carry"
        )
        if carrying_now:
            continue
        if holder:
            p["x"], p["y"] = holder.get("x", p.get("x")), holder.get("y", p.get("y"))
            holder.pop("carrying", None)
        p.pop("carried_by", None)
        p["visible"] = True


def release_anchor(c, world):

    occ = c.get("occupying")
    if not occ:
        return

    c["occupying"] = None

    prop_id = occ["prop_id"]
    anchor_name = occ["anchor_name"]

    for p in world.get("props", []):
        if p["id"] != prop_id:
            continue

        for a in p.get("anchors", []):
            if a["name"] != anchor_name:
                continue

            if a.get("occupied_by") == c["id"]:
                a["occupied_by"] = None

                # 🔥 wake next in queue
                queue = a.get("queue", [])
                if queue:
                    next_id = queue.pop(0)

                    for c2 in world["characters"].values():
                        if c2["id"] == next_id:
                            c2["activity"] = None  # force replan


def reserve_anchor_for(c, anchor, world, timeout=10):
    if anchor.get("occupied_by"):
        return False

    if anchor.get("reserved_by") and anchor["reserved_by"] != c["id"]:
        return False

    anchor["reserved_by"] = c["id"]
    anchor["reserved_until"] = world["tick"] + timeout

    return True


def release_reservation(c, world):
    for p in world.get("props", []):
        for a in p.get("anchors", []):
            if a.get("reserved_by") == c["id"]:
                a["reserved_by"] = None
                a["reserved_until"] = None

# =========================================================
# ONE THING AT A TIME
# =========================================================
# A character does one activity at a time. Starting another while one is still running -- not finished, interrupted
# or paused -- is a bug in whatever started it: it used to overwrite the running one silently (its anchor never
# released, its record written off as "replaced", or not at all), which is how characters ended up "doing" several
# things and finishing none. Every assignment of a character's activity goes through occupy() now:
#
#   c["activity"] = occupy(c, world, new_activity)
#
# A clash is logged as an error with where it came from (and kept in world["activity_clashes"]), the running activity
# ends ("clash"), the new one is dropped, and the character loses a few minutes standing there flustered -- and thinks
# so. A deliberate switch (a decision to do something else) says so first: `with switching(c, reason): ...` ends the
# running activity properly before the new one starts.

import contextlib

CLASH_WASTE_SECONDS = 3 * 60
CLASH_LOG_KEPT = 200


def is_running(act):
    """An activity still under way: not closed (activity_trace), not already completed (its completion side-effects
    ran; only the one-tick finishing animation is left), not paused."""
    return bool(act) and not act.get("_closed") and not act.get("_completed") and not act.get("paused") \
        and act.get("phase") != "finishing"


@contextlib.contextmanager
def switching(c, reason):
    """Within this block, a new activity replaces the running one on purpose (interrupting it properly first)."""
    prev = c.get("_switching")
    c["_switching"] = reason or "they chose to do something else"
    try:
        yield
    finally:
        if prev is None:
            c.pop("_switching", None)
        else:
            c["_switching"] = prev


def occupy(c, world, new):
    """The activity to put in c["activity"]: `new`, or -- when it would go on top of one still running without that one
    being ended first -- the result of a clash (see above)."""
    if new is None:
        return None
    cur = c.get("activity")
    if cur is None or cur is new or not is_running(cur) or world is None:
        return new
    if c.get("_switching"):
        interrupt_activity(c, world, reason=c["_switching"])
        return new
    return _clash(c, world, cur, new)


def _origin():
    import traceback
    frames = [f for f in traceback.extract_stack()[:-3] if "occupancy.py" not in f.filename]
    return " <- ".join(f"{f.filename.rsplit('/', 2)[-1] if '/' in f.filename else f.filename}:{f.lineno} {f.name}"
                       for f in reversed(frames[-3:]))


def _label(act):
    return str((act or {}).get("type") or "something").replace("_", " ")


def _clash(c, world, cur, new):
    tick = world.get("tick", 0)
    name = c.get("name") or c.get("id")
    where = _origin()
    print(f"[activity] ERROR one-thing-at-a-time: {name} was made to start '{_label(new)}' while still "
          f"'{_label(cur)}' (since tick {cur.get('phase_started_tick')}) -- both dropped. Started from: {where}",
          flush=True)
    log = world.setdefault("activity_clashes", [])
    log.append({"tick": tick, "character_id": c.get("id"), "running": cur.get("type"), "started": new.get("type"),
                "from": where})
    del log[:-CLASH_LOG_KEPT]
    interrupt_activity(c, world, reason=f"tried to start {_label(new)} on top of it", outcome="clash")
    thought = (f"I tried to {_label(new)} while I was still {_label(cur)}, and now I'm doing neither. "
               f"That's a few minutes wasted -- I must look so slow. I can't do two things at once.")
    c["last_thought"] = thought
    try:
        from brain.memory import store_memory
        store_memory(c, thought, importance=0.4, tags=["thought", "clash"], tick=tick, source="internal")
    except Exception as exc:                                   # noqa: BLE001 -- the clash itself must stand
        print(f"[activity] could not remember the clash for {c.get('id')}: {exc!r}")
    from core.event_bus import emit
    emit("activity_clash", {"character_id": c.get("id"), "running": cur.get("type"), "started": new.get("type"),
                            "from": where})
    from core import scheduler
    scheduler.schedule_in(world, f"fluster:{c.get('id')}", "end", CLASH_WASTE_SECONDS)
    return {"type": "wait", "phase": "using", "phase_started_tick": tick, "duration": CLASH_WASTE_SECONDS,
            "state": {"reason": "flustered"}, "reason": "standing there, flustered, after trying to do two things at once"}


def _end_fluster(world, entry):
    """The few minutes lost to a clash are over: free to decide again."""
    c = world.get("characters", {}).get(entry["owner"].split(":", 1)[1])
    act = (c or {}).get("activity") or {}
    if act.get("type") == "wait" and (act.get("state") or {}).get("reason") == "flustered":
        c["activity"] = None
        from brain.cognition_scheduler import wake_character
        wake_character(c, world, "activity_finished", {"activity": "being flustered"})


def _register():
    from core import scheduler
    scheduler.register("fluster", _end_fluster)


_register()
