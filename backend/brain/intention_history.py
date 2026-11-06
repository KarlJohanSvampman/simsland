"""
What became of each intention: c["intention_history"] (newest last, INTENTION_HISTORY_KEPT kept), so the inspector can
list finished intentions in the order they came -- done ones green and ticked off, the rest marked as they ended.

    {"type", "target", "reason", "category", "since", "ended", "outcome": "done" | "blocked" | "dropped", "how"}

An intention is DONE when, while it was there, something that satisfies it happened:
  - a live intention's plan satisfied it (brain/plans/runner.py emits intention.satisfied -> every type it replaces)
  - its expectation was satisfied (expectation:<id>)
  - an activity completed that satisfies it: the same type, or one brain/intention_needs.satisfied_by() lists
BLOCKED when its plan was blocked; otherwise DROPPED (it went away -- the need eased, it lapsed, it was replaced).

track(c, world) runs once per character per tick from brain/agent_loop.py: a comparison of the intention list with the
last one (by type and target), cheap; the "done" marks come from events.
"""

INTENTION_HISTORY_KEPT = 60


def _key(i):
    return f"{i.get('type')}|{i.get('target_id') or i.get('child_id') or ''}"


def track(c, world):
    now = {_key(i): i for i in c.get("active_intentions") or [] if i.get("type")}
    seen = c.setdefault("_intention_seen", {})
    tick = world.get("tick", 0)
    for k, i in now.items():
        if k not in seen:
            seen[k] = {"type": i.get("type"), "target": i.get("target_id") or i.get("child_id"),
                       "reason": str(i.get("reason") or "")[:160], "category": i.get("category"), "since": tick}
    marks = c.get("_intention_done") or {}
    for k in [k for k in seen if k not in now]:
        rec = seen.pop(k)
        mark = marks.pop(k, None) or marks.pop(rec["type"] + "|", None)
        rec.update(ended=tick, outcome=(mark or {}).get("outcome", "dropped"), how=(mark or {}).get("how"))
        c.setdefault("intention_history", []).append(rec)
    if len(c.get("intention_history") or []) > INTENTION_HISTORY_KEPT:
        del c["intention_history"][:-INTENTION_HISTORY_KEPT]
    # a mark for something no longer (or never) there does not wait forever
    for k in [k for k, m in marks.items() if tick - m.get("tick", tick) > 600 and k not in now]:
        marks.pop(k, None)


def mark(c, world, intention_type, outcome, how, target=None):
    """Something just satisfied (or blocked) this intention type for c."""
    k = f"{intention_type}|{target or ''}"
    keys = [k] if target else [kk for kk in c.get("_intention_seen", {}) if kk.split("|")[0] == intention_type] or [k]
    for kk in keys:
        c.setdefault("_intention_done", {})[kk] = {"outcome": outcome, "how": how, "tick": world.get("tick", 0)}


def _on_activity_completed(data, world):
    c = (world.get("characters") or {}).get(data.get("character_id"))
    if not c:
        return
    from brain.intention_needs import satisfied_by
    t = data.get("activity_type")
    for k, rec in list((c.get("_intention_seen") or {}).items()):
        itype = rec["type"]
        base = itype.split(":", 1)[1] if itype.startswith("expectation:") else itype
        sb = satisfied_by(itype)
        if t in (itype, base) or t in sb:
            c.setdefault("_intention_done", {})[k] = {"outcome": "done", "how": t.replace("_", " "), "tick": world.get("tick", 0)}


def _on_plan_end(outcome):
    def handler(data, world):
        c = (world.get("characters") or {}).get(data.get("character_id"))
        if not c:
            return
        from brain.plans import store
        intent = store.get(store.load(), "intentions", data.get("intention")) or {}
        for t in intent.get("replaces") or []:
            mark(c, world, t, "done" if outcome == "satisfied" else "blocked", data.get("why"))
    return handler


def _register():
    from core.event_bus import subscribe
    subscribe("activity_completed", _on_activity_completed)
    subscribe("intention.satisfied", _on_plan_end("satisfied"))
    subscribe("intention.blocked", _on_plan_end("blocked"))


_register()
