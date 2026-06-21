# =========================================================
# ACTIVITY QUEUE
# An ordered list of tasks a character will execute in
# sequence. Tasks can declare dependencies on earlier tasks
# so the queue idles until those complete.
#
# Task schema:
#   id          — short UUID fragment
#   type        — "search_room" | "retrieve_item" | "setup_prop"
#                 "examine_prop" | "examine_item" | "hobby_session"
#                 "go_shopping" | "return_item" | "order_online"
#   params      — type-specific dict
#   depends_on  — list of task ids that must be "done"/"skipped"
#   status      — "pending" | "active" | "done" | "skipped" | "failed"
#
# Suspended sessions:
# When a more urgent activity interrupts a queued hobby, the
# remaining tasks are serialised into suspended_hobby_sessions
# and reloaded (with validation) when the character is free again.
# =========================================================

import uuid

from systems.persistent_desires import add_desire


# =========================================================
# ENSURE DEFAULTS
# =========================================================

def ensure_queue(c):
    c.setdefault("activity_queue",          [])
    c.setdefault("suspended_hobby_sessions", [])


# =========================================================
# ADD TASK
# =========================================================

def queue_task(c, task_type, params=None, depends_on=None):
    """Append a task and return its id."""
    ensure_queue(c)
    task = {
        "id":         str(uuid.uuid4())[:8],
        "type":       task_type,
        "params":     params or {},
        "depends_on": depends_on or [],
        "status":     "pending",
    }
    c["activity_queue"].append(task)
    return task["id"]


# =========================================================
# DEPENDENCY CHECK
# =========================================================

def _deps_satisfied(task, queue):
    done_ids = {t["id"] for t in queue if t["status"] in ("done", "skipped")}
    return all(dep in done_ids for dep in task.get("depends_on", []))


# =========================================================
# PROCESS QUEUE  (call when character has no active activity)
# =========================================================

def process_activity_queue(c, world):
    """
    Dispatch the next ready task from the queue.
    Returns True if a task was started, False otherwise.
    When queue is empty, checks for a suspended session to resume.
    """
    ensure_queue(c)
    queue = c["activity_queue"]

    if not queue:
        _maybe_resume_suspended(c, world)
        return False

    for task in queue:
        if task["status"] != "pending":
            continue
        if not _deps_satisfied(task, queue):
            continue

        task["status"] = "active"
        started        = _dispatch_task(c, world, task)

        if not started:
            task["status"] = "skipped"
            continue

        return True

    # All tasks terminal — clear queue
    if all(t["status"] in ("done", "skipped", "failed") for t in queue):
        c["activity_queue"] = []

    return False


# =========================================================
# MARK TASK DONE  (call from complete_activity / finish_activity)
# =========================================================

def mark_queue_task_done(c, task_type=None, success=True):
    """
    Mark the currently-active queue task as done or failed.
    Optionally filter by task_type to avoid mis-matching.
    Returns the completed task dict or None.
    """
    ensure_queue(c)
    for task in c["activity_queue"]:
        if task["status"] == "active":
            if task_type is None or task["type"] == task_type:
                task["status"] = "done" if success else "failed"
                return task
    return None


# =========================================================
# SUSPEND QUEUE  (call when urgent interruption occurs)
# =========================================================

def suspend_activity_queue(c, world, reason="interruption"):
    """
    Serialise the remaining queue into a suspended session so the
    character can pick it up later. The active task is reset to
    pending so it restarts cleanly on resumption.

    The session stores which items were already retrieved so that
    validate_and_trim_queue can skip those steps on reload.
    """
    ensure_queue(c)
    queue = c["activity_queue"]
    if not queue:
        return

    completed  = [t for t in queue if t["status"] in ("done", "skipped")]
    remaining  = []

    for t in queue:
        if t["status"] == "active":
            # Reset interrupted task back to pending
            t_copy           = dict(t)
            t_copy["status"] = "pending"
            remaining.append(t_copy)
        elif t["status"] == "pending":
            remaining.append(dict(t))

    if not remaining:
        c["activity_queue"] = []
        return

    # Identify items successfully retrieved during completed tasks
    retrieved_items = [
        t["params"].get("item_type")
        for t in completed
        if t["type"] in ("retrieve_item", "carry_item")
        and t["params"].get("item_type")
    ]

    hobby_task = next(
        (t for t in queue if t["type"] == "hobby_session"), None
    )

    session = {
        "id":               str(uuid.uuid4())[:8],
        "hobby":            hobby_task["params"].get("hobby")    if hobby_task else None,
        "main_prop_id":     hobby_task["params"].get("target_id") if hobby_task else None,
        "remaining_queue":  remaining,
        "completed_types":  [t["type"] for t in completed],
        "retrieved_items":  retrieved_items,
        "suspended_at_tick": world.get("tick", 0),
        "reason":           reason,
        "importance":       0.6,
    }

    c["suspended_hobby_sessions"].append(session)
    c["suspended_hobby_sessions"] = c["suspended_hobby_sessions"][-5:]

    # Register a persistent desire so frustration builds if left too long
    if session["hobby"]:
        add_desire(
            c,
            f"resume_{session['hobby']}",
            target=session["id"],
            importance=0.6,
        )

    c["activity_queue"] = []
    c["activity"]       = None


# =========================================================
# RESUME SUSPENDED SESSION
# =========================================================

def _maybe_resume_suspended(c, world):
    """
    Auto-resume the most important suspended session once importance
    crosses 0.70 (grows slowly over time so they always come back).
    """
    sessions = c.get("suspended_hobby_sessions", [])
    if not sessions:
        return

    tick = world.get("tick", 0)

    # Age up importance on all sessions
    for s in sessions:
        age   = tick - s.get("suspended_at_tick", tick)
        s["importance"] = min(0.95, s["importance"] + age * 0.000002)

    best = max(sessions, key=lambda s: s.get("importance", 0))

    if best["importance"] < 0.70:
        return

    _reload_suspended_session(c, world, best)
    c["suspended_hobby_sessions"].remove(best)


def _reload_suspended_session(c, world, session):
    """Re-validate the remaining queue and push it back as the active queue."""
    from systems.hobby_planner import validate_and_trim_queue
    remaining = session.get("remaining_queue", [])
    if not remaining:
        return
    trimmed = validate_and_trim_queue(c, world, remaining, session)
    if trimmed:
        c["activity_queue"] = trimmed


# =========================================================
# TASK DISPATCH
# =========================================================

def _dispatch_task(c, world, task):
    """Convert a queue task into a running activity."""
    from systems.action_router import _scaffold
    from systems.props         import get_prop_by_id

    t = task["type"]
    p = task.get("params", {})

    if t == "hobby_session":
        return _dispatch_hobby(c, world, task)

    if t in ("examine_prop", "examine_item"):
        target_id = p.get("target_id") or p.get("main_prop_id")
        if not target_id:
            return False
        c["activity"]        = _scaffold(c, world, "examine",
                                         target_id=target_id,
                                         interaction="examine",
                                         duration=180)
        c["animation_state"] = "examine"
        c["_queue_task_id"]  = task["id"]
        return True

    if t in ("retrieve_item", "carry_item"):
        return _dispatch_retrieve(c, world, task)

    if t == "search_room":
        return _dispatch_search(c, world, task)

    if t == "setup_prop":
        target_id = p.get("target_id")
        prop      = get_prop_by_id(world, target_id)
        if prop:
            prop["state"] = "setup"
        c["activity"]       = _scaffold(c, world, "interact",
                                         target_id=target_id,
                                         interaction="interact",
                                         duration=120)
        c["_queue_task_id"] = task["id"]
        return True

    if t == "return_item":
        return _dispatch_return(c, world, task)

    if t in ("go_shopping", "order_online"):
        from systems.activities import ACTIVITIES, start_activity
        act_type = "go_shopping" if t == "go_shopping" else "browse_phone"
        if act_type in ACTIVITIES:
            ok = start_activity(c, world, act_type)
        else:
            c["activity"] = _scaffold(c, world, act_type, duration=5400)
            ok = True
        if ok:
            c["_queue_task_id"] = task["id"]
        return ok

    return False


def _dispatch_hobby(c, world, task):
    from systems.activities import ACTIVITIES, start_activity
    from systems.action_router import _scaffold

    p             = task.get("params", {})
    activity_type = p.get("activity", p.get("hobby", "paint"))
    target_id     = p.get("target_id")

    if activity_type in ACTIVITIES:
        ok = start_activity(c, world, activity_type)
    else:
        c["activity"] = _scaffold(c, world, activity_type,
                                   target_id=target_id,
                                   duration=5400)
        ok = True

    if ok:
        c["_queue_task_id"]       = task["id"]
        c["_active_hobby_params"] = p   # stash for consume_uses on completion
    return ok


def _dispatch_retrieve(c, world, task):
    from systems.action_router import _scaffold

    p            = task.get("params", {})
    container_id = p.get("container_id")
    if not container_id:
        return False

    act                = _scaffold(c, world, "retrieve_item",
                                    target_id=container_id,
                                    interaction="interact",
                                    duration=300)
    act["item_type"]   = p.get("item_type")
    act["dest_prop_id"]= p.get("dest_prop_id")
    act["is_retrieve"] = True
    c["activity"]      = act
    c["_queue_task_id"]= task["id"]
    c["animation_state"] = "walk"
    return True


def _dispatch_search(c, world, task):
    from systems.action_router import _scaffold

    p         = task.get("params", {})
    act             = _scaffold(c, world, "search_room",
                                interaction="search",
                                duration=900)
    act["item_type"]      = p.get("item_type")
    act["room_id"]        = p.get("room_id")
    act["dest_prop_id"]   = p.get("dest_prop_id")
    act["search_phase"]   = "starting"
    act["containers_left"]= []
    c["activity"]         = act
    c["_queue_task_id"]   = task["id"]
    c["animation_state"]  = "walk"
    return True


def _dispatch_return(c, world, task):
    from systems.action_router import _scaffold

    p            = task.get("params", {})
    container_id = p.get("container_id")
    if not container_id:
        return False

    act               = _scaffold(c, world, "return_item",
                                   target_id=container_id,
                                   interaction="interact",
                                   duration=180)
    act["item_type"]  = p.get("item_type")
    act["is_return"]  = True
    c["activity"]     = act
    c["_queue_task_id"]= task["id"]
    return True
