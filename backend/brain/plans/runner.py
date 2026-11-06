"""
Runs an intention's ActionPlans on a character (design doc "Intentions and ActionPlans").

    c["plan_attempts"][intention]   the attempt under way: the plan stack, the variables, the trace
    c["beliefs"][requirement]       what the character believes: value, when, how, until
    c["plan_log"]                   finished attempts (newest last), for the inspector and statistics

Entry points into this module:
    autopilot(c, world, intention_entry)   from brain/agent_loop.py's autopilot, for an intention type a LIVE intention
                                           replaces: starts or continues the attempt. Returns None (not ours), "started"
                                           (an activity began), or "busy" (waiting, or recently blocked).
    on_activity_end(...)                   event handlers: a step's activity finished / was interrupted / clashed --
                                           the attempt moves on at once, no polling
Nothing else starts an activity for a live intention (systems/occupancy.py::occupy keeps it to one at a time).
"""

from brain.plans import store
from brain.plans.checker import outputs_for
from brain.plans.resolvers import RESOLVERS
from brain.plans.actions import ACTIONS

MAX_HOPS = 60                 # node transitions per call: a path the checker allowed can't need more
WAIT_RECHECK_SECONDS = 60
BLOCKED_COOLDOWN_SECONDS = 30 * 60
LOG_KEPT = 30
TRACE_KEPT = 80


# ── definitions ──────────────────────────────────────────────────────────────────────────────────────────────────

def _data(world):
    return store.load(world.get("sim_id", "default") if isinstance(world.get("sim_id"), str) else "default")


def live_intention_for(world, intention_type):
    """The live intention that has taken over this old intention type (eat_food -> reduce_hunger), or None."""
    for i in _data(world).get("intentions") or []:
        if i.get("status") == "live" and intention_type in (i.get("replaces") or []):
            return i
    return None


def drive_level(c, world, drive):
    src = str((drive or {}).get("source") or "")
    if src.startswith("body."):
        return ((c.get("body") or {}).get(src[5:]))
    return None


# ── beliefs ──────────────────────────────────────────────────────────────────────────────────────────────────────

def observe(c, world, rid, how="looked"):
    """Find out the truth of requirement `rid` now; the character's belief becomes it. Returns the value."""
    data = _data(world)
    req = store.get(data, "requirements", rid) or {}
    fn = RESOLVERS.get(req.get("resolver") or rid)
    value = bool(fn(c, world)) if fn else False
    tick = world.get("tick", 0)
    ttl = req.get("ttl_seconds") or 0
    b = c.setdefault("beliefs", {}).get(rid)
    c["beliefs"][rid] = {"value": value, "tick": tick, "how": how, "until": tick + ttl if ttl else tick,
                         "was": b.get("value") if b and believed(c, world, rid) is not None else None}
    return value


def believed(c, world, rid):
    """True / False / None (unknown, or the belief has expired)."""
    b = (c.get("beliefs") or {}).get(rid)
    if not b or world.get("tick", 0) > b.get("until", 0):
        return None
    return b.get("value")


# ── variables (decision nodes) ───────────────────────────────────────────────────────────────────────────────────

def _var(c, world, att, name):
    if name in (att.get("vars") or {}):
        return att["vars"][name]
    cal = world.get("calendar") or {}
    if name in ("hour", "minute_of_day", "weekday"):
        return cal.get(name)
    if name == "money":
        return c.get("money") or 0
    if name == "energy":
        return (c.get("body") or {}).get("energy")
    if name == "age":
        return c.get("age")
    if name == "drive_level":
        return att.get("drive_level")
    return None


_OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b, "!=": lambda a, b: a != b, "in": lambda a, b: a in (b or [])}


def _decide(c, world, att, node):
    for rule in node.get("rules") or []:
        ok = True
        for cond in rule.get("when") or []:
            v = _var(c, world, att, cond.get("var"))
            try:
                ok = v is not None and _OPS[cond.get("op", "==")](v, cond.get("value"))
            except Exception:                                  # noqa: BLE001 -- a bad comparison is a false condition
                ok = False
            if not ok:
                break
        if ok:
            return rule.get("output")
    return node.get("default")


# ── attempts ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _trace(att, world, **entry):
    att.setdefault("trace", []).append(dict(entry, tick=world.get("tick", 0)))
    del att["trace"][:-TRACE_KEPT]


def _plans(world):
    return store.by_id(_data(world), "plans")


def _usable(plan):
    return plan and plan.get("status") != "planned"


def _entry_node(plan, entry_id=None):
    entries = plan.get("entries") or [{"id": "start", "node": plan.get("start")}]
    for e in entries:
        if entry_id is None or e.get("id") == entry_id:
            return e.get("node")
    return entries[0].get("node")


def _choose(c, world, att, intention):
    """The next plan to try: in the intention's order, untried, usable, whose entry requirements are not believed
    false. Scouting first when the character doesn't know enough and isn't impulsive."""
    plans = _plans(world)
    cands = [pid for pid in intention.get("plans") or [] if pid not in att["tried"] and _usable(plans.get(pid))]
    scout = intention.get("scout_plan")
    if (scout and not att.get("scouted") and _usable(plans.get(scout)) and "impulsive" not in (c.get("traits") or [])
            and sum(1 for pid in cands for r in plans[pid].get("requires") or [] if believed(c, world, r) is None) >= 2):
        att["scouted"] = True
        return scout
    for pid in cands:
        if all(believed(c, world, r) is not False for r in plans[pid].get("requires") or []):
            return pid
        _trace(att, world, plan=pid, what="skipped", why="believed not possible: " + ", ".join(
            r for r in plans[pid].get("requires") or [] if believed(c, world, r) is False))
        att["tried"].append(pid)
    return None


def _start_plan(c, world, att, pid, entry=None, return_to=None):
    plan = _plans(world)[pid]
    if return_to is None and plan.get("kind") != "scout":
        att["tried"].append(pid)
    att["stack"].append({"plan": pid, "node": _entry_node(plan, entry), "return_to": return_to})
    _trace(att, world, plan=pid, what="plan", why=("sidetrack" if return_to else "chosen") + (f" via entry {entry}" if entry else ""))


def _finish(c, world, iid, att, status, why):
    att["status"], att["ended"], att["why"] = status, world.get("tick", 0), why
    _trace(att, world, what=status, why=why)
    c.setdefault("plan_log", []).append({k: att[k] for k in ("id", "intention", "started", "ended", "status", "why",
                                                             "tried", "trace", "vars") if k in att})
    del c["plan_log"][:-LOG_KEPT]
    (c.get("plan_attempts") or {}).pop(iid, None)
    from core import scheduler
    scheduler.cancel(world, f"planwait:{c['id']}", iid)
    if status == "blocked":
        c.setdefault("_plan_cooldown", {})[iid] = world.get("tick", 0) + BLOCKED_COOLDOWN_SECONDS
        try:
            from brain.memory import store_memory
            store_memory(c, f"I couldn't manage it ({why}).", importance=0.4, tags=["plan", "blocked", iid],
                         tick=world.get("tick", 0), source="internal")
        except Exception:                                      # noqa: BLE001
            pass
    from core.event_bus import emit
    emit(f"intention.{status}", {"character_id": c["id"], "intention": iid, "why": why})


def _satisfied(c, world, intention):
    data = _data(world)
    drive = store.get(data, "drives", intention.get("drive"))
    below = ((intention.get("satisfied_when") or {}).get("drive_below")
             if intention.get("satisfied_when") else (drive or {}).get("satisfied_below"))
    lvl = drive_level(c, world, drive)
    return below is not None and lvl is not None and lvl < below


def autopilot(c, world, intention_entry):
    """See the module docstring."""
    intention = live_intention_for(world, intention_entry.get("type"))
    if not intention:
        return None
    iid = intention["id"]
    if world.get("tick", 0) < (c.get("_plan_cooldown") or {}).get(iid, -1):
        return "busy"
    att = (c.setdefault("plan_attempts", {})).get(iid)
    if att is None:
        att = c["plan_attempts"][iid] = {"id": f"{iid}@{world.get('tick', 0)}", "intention": iid,
                                         "started": world.get("tick", 0), "stack": [], "tried": [], "vars": {},
                                         "status": "running"}
        att["drive_level"] = drive_level(c, world, store.get(_data(world), "drives", intention.get("drive")))
        _trace(att, world, what="raised", why=f"{intention_entry.get('type')} ({intention_entry.get('reason')})")
    if att.get("waiting_activity"):
        # autopilot only runs when they are doing nothing: the step's activity is gone without its end being
        # reported (it never really started) -- the step failed
        node = att.pop("waiting_activity")
        return _run(c, world, iid, att, intention, came_out="failed", at=node)
    if att.get("wait"):
        return "busy"
    return _run(c, world, iid, att, intention)


def _run(c, world, iid, att, intention, came_out=None, at=None):
    plans = _plans(world)
    for _ in range(MAX_HOPS):
        if _satisfied(c, world, intention):
            _finish(c, world, iid, att, "satisfied", "the need is met")
            return "busy"
        if not att["stack"]:
            pid = _choose(c, world, att, intention)
            if not pid:
                _finish(c, world, iid, att, "blocked", "no plan left that could work: " + ", ".join(att["tried"]) if att["tried"] else "no plan")
                return "busy"
            _start_plan(c, world, att, pid)
            came_out = None
            continue
        frame = att["stack"][-1]
        plan = plans.get(frame["plan"])
        nodes = {n["id"]: n for n in (plan or {}).get("nodes") or []}
        node = nodes.get(frame["node"])
        if node is None:
            _finish(c, world, iid, att, "blocked", f"plan {frame['plan']} has no node {frame['node']}")
            return "busy"
        out = None
        if came_out is not None and at == node["id"]:
            out, came_out = came_out, None
        k = node["kind"]
        if out is None:
            if k == "gate":
                before = believed(c, world, node["requirement"])
                val = observe(c, world, node["requirement"], how="at the gate")
                out = "yes" if val else "no"
                _trace(att, world, plan=frame["plan"], node=node["id"], what="gate", req=node["requirement"],
                       believed=before, found=val, out=out)
            elif k == "decision":
                out = _decide(c, world, att, node)
                _trace(att, world, plan=frame["plan"], node=node["id"], what="decision", out=out)
            elif k == "step":
                from systems.activities import start_activity
                started = start_activity(c, world, node["activity"])
                _trace(att, world, plan=frame["plan"], node=node["id"], what="step", activity=node["activity"], started=bool(started))
                if started:
                    att["waiting_activity"] = node["id"]
                    att["activity_type"] = node["activity"]
                    return "started"
                out = "failed"
            elif k == "action":
                fn = ACTIONS.get(node["action"])
                ok = bool(fn and fn(c, world, att))
                out = "done" if ok else "failed"
                _trace(att, world, plan=frame["plan"], node=node["id"], what="action", action=node["action"], out=out)
            elif k == "wait":
                w = att.get("wait")
                if not w or w.get("node") != node["id"]:
                    w = att["wait"] = {"node": node["id"], "until": world.get("tick", 0) + int(node.get("timeout_seconds") or 600)}
                if observe(c, world, node["requirement"], how="waited"):
                    out = "ready"
                elif world.get("tick", 0) >= w["until"]:
                    out = "timed_out"
                else:
                    from core import scheduler
                    scheduler.schedule_in(world, f"planwait:{c['id']}", iid, WAIT_RECHECK_SECONDS)
                    return "busy"
                att.pop("wait", None)
                _trace(att, world, plan=frame["plan"], node=node["id"], what="wait", req=node["requirement"], out=out)
            elif k == "plan":
                sub = plans.get(node.get("plan"))
                used = att.setdefault("sidetracks", [])
                key = f"{frame['plan']}/{node['id']}"
                if not _usable(sub) or key in used or len(att["stack"]) > 2:
                    out = "blocked"
                    _trace(att, world, plan=frame["plan"], node=node["id"], what="sidetrack", out=out,
                           why="not available" if not _usable(sub) else "already tried")
                else:
                    used.append(key)
                    _start_plan(c, world, att, sub["id"], entry=node.get("entry"), return_to=node["id"])
                    continue
            elif k == "end":
                outcome = node.get("outcome")
                att["stack"].pop()
                if frame.get("return_to") is not None:                     # a sidetrack: back to the node that sent it
                    parent = att["stack"][-1]
                    came_out, at = ("done" if outcome == "done" else "blocked"), frame["return_to"]
                    parent["node"] = frame["return_to"]
                    _trace(att, world, plan=frame["plan"], what="returned", out=came_out)
                    continue
                plan_kind = (plan or {}).get("kind")
                if plan_kind == "scout":
                    continue                                                 # scouting done: now choose a plan
                if outcome == "satisfied":
                    if _satisfied(c, world, intention):
                        _finish(c, world, iid, att, "satisfied", f"{plan.get('name', frame['plan'])} worked")
                        return "busy"
                    _trace(att, world, plan=frame["plan"], what="fallback", why="the plan ended but the need is still there")
                    continue
                if outcome == "blocked":
                    _finish(c, world, iid, att, "blocked", (att.get("vars") or {}).get("why") or f"{plan.get('name', frame['plan'])} was blocked")
                    return "busy"
                _trace(att, world, plan=frame["plan"], what="fallback", why=(att.get("vars") or {}).get("why", "a gate said no"))
                continue
        edge = next((e for e in plan.get("edges") or [] if e.get("from") == node["id"] and e.get("output") == out), None)
        if not edge:
            _finish(c, world, iid, att, "blocked", f"{frame['plan']}/{node['id']} has no wire for '{out}'")
            return "busy"
        att.setdefault("vars", {}).update(edge.get("set") or {})
        frame["node"] = edge["to"]
    _finish(c, world, iid, att, "blocked", "the plan went round too long")
    return "busy"


# ── events: a step's activity ended; a wait is due ─────────────────────────────────────────────────────────────

def on_activity_end(data, world, out):
    c = (world.get("characters") or {}).get(data.get("character_id"))
    if not c:
        return
    for iid, att in list((c.get("plan_attempts") or {}).items()):
        node = att.get("waiting_activity")
        if not node:
            continue
        if data.get("activity_type") and att.get("activity_type") and data["activity_type"] != att["activity_type"]:
            continue
        att.pop("waiting_activity", None)
        intention = store.get(_data(world), "intentions", iid)
        if intention:
            _run(c, world, iid, att, intention, came_out=out, at=node)


def _on_wait_timer(world, entry):
    c = (world.get("characters") or {}).get(entry["owner"].split(":", 1)[1])
    iid = entry.get("key")
    att = ((c or {}).get("plan_attempts") or {}).get(iid)
    intention = store.get(_data(world), "intentions", iid)
    if c and att and intention and att.get("wait") and not c.get("activity"):
        _run(c, world, iid, att, intention)
    elif c and att and att.get("wait"):
        from core import scheduler
        scheduler.schedule_in(world, f"planwait:{c['id']}", iid, WAIT_RECHECK_SECONDS)


def _register():
    from core.event_bus import subscribe
    from core import scheduler
    subscribe("activity_finished", lambda d, w: on_activity_end(d, w, "done"))
    subscribe("activity_interrupted", lambda d, w: on_activity_end(d, w, "failed"))
    subscribe("activity_clash", lambda d, w: on_activity_end(dict(d, activity_type=d.get("started")), w, "failed"))
    scheduler.register("planwait", _on_wait_timer)


_register()
