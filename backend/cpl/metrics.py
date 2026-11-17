"""
cpl/metrics.py -- the measures the spec asks for (docs/cpl_implementation_plan.md phase 5): how turns were generated,
how many model calls conversations took, how they ended. Kept on the world (world["cpl_metrics"], persisted with it)
and read by GET /admin/cpl/metrics (api/cpl.py).
"""


def _m(world):
    m = world.get("cpl_metrics")
    if m is None:
        world["cpl_metrics"] = m = {"turns": {"A": 0, "B": 0, "C": 0}, "model_calls": 0, "compact_turns": 0,
                                    "ended": {}}
    return m


def note_turn(world, mode, compact=False):
    m = _m(world)
    m["turns"][mode] = m["turns"].get(mode, 0) + 1
    if mode != "A":
        m["model_calls"] += 1
    if compact:
        m["compact_turns"] += 1


def note_ended(world, reason):
    m = _m(world)
    m["ended"][reason] = m["ended"].get(reason, 0) + 1


def report(world):
    m = dict(_m(world))
    turns = sum(m["turns"].values()) or 1
    ended = sum(m["ended"].values()) or 1
    m["share_without_model"] = round(m["turns"].get("A", 0) / turns, 3)
    m["share_timeout_or_abandoned"] = round((m["ended"].get("timeout", 0) + m["ended"].get("abandoned", 0)
                                             + m["ended"].get("no_answer", 0)) / ended, 3)
    m["live"] = sum(1 for c in (world.get("cpl_conversations") or {}).values()
                    if c.get("state") not in ("resolved", "expired"))
    return m
