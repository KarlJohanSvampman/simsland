"""
core/active_loops.py -- the "temporary active loop" of docs/distributed_architecture_plan.md.

A component that is genuinely continuous while something is happening (people walking, the bus driving, a live
exchange in a conversation) runs once per clock step -- but only for its MEMBERS, and not at all when it has none.
It never scans the population to find out whether there is work: whoever starts the activity adds the member, and the
loop drops a member when its work is over.

    register(name, fn, order=0)     fn(world, ids) -> iterable of ids that are finished (removed); runs per step
    add(world, name, id)            start: id is a member until fn reports it finished (or discard() is called)
    discard(world, name, id)
    members(world, name)            the current members (a list, in the order they were added)
    run(world)                      each loop with members, in `order`
    run_one(world, name)            one loop, at the point of the step where it belongs
    rebuild(world, name, ids)       replace the members (a world loaded from a save, a safety sweep)

Members live on the world (world["_active_loops"][name]) so they persist with it. A loop with no members costs one
dictionary lookup per step. Stats per loop (steps run, members seen) are kept in process memory for /admin.
"""

_loops = {}           # name -> {"fn", "order"}
_stats = {}           # name -> {"steps": int, "member_steps": int, "errors": int}


def register(name, fn, order=0):
    _loops[name] = {"fn": fn, "order": order}
    _stats.setdefault(name, {"steps": 0, "member_steps": 0, "errors": 0})


def _bucket(world, name):
    return world.setdefault("_active_loops", {}).setdefault(name, [])


def add(world, name, member_id):
    if member_id is None:
        return
    b = _bucket(world, name)
    if member_id not in b:
        b.append(member_id)


def discard(world, name, member_id):
    b = (world.get("_active_loops") or {}).get(name)
    if b and member_id in b:
        b.remove(member_id)


def members(world, name):
    return list((world.get("_active_loops") or {}).get(name) or ())


def rebuild(world, name, ids):
    """Set the members to `ids` (keeping the existing order for those already present). Returns the ids that were
    missing -- members the starting code never added (a safety sweep reports them)."""
    b = _bucket(world, name)
    want = list(dict.fromkeys(ids))
    missing = [i for i in want if i not in b]
    b[:] = [i for i in b if i in want] + missing
    return missing


def run(world):
    for name, _loop in sorted(_loops.items(), key=lambda kv: kv[1]["order"]):
        run_one(world, name)


def run_one(world, name):
    """Run one loop now (for its members only); nothing when it has none."""
    loop = _loops.get(name)
    ids = members(world, name)
    if ids:
        from core import partitions
        ids = partitions.loop_ids(world, name, ids)       # this partition's members only (core/partitions.py)
    if loop is None or not ids:
        return
    st = _stats[name]
    st["steps"] += 1
    st["member_steps"] += len(ids)
    try:
        done = loop["fn"](world, ids) or ()
    except Exception as exc:
        st["errors"] += 1
        print(f"[active_loops] {name} failed: {exc!r}")
        return
    for i in done:
        discard(world, name, i)


def stats():
    return {name: dict(st) for name, st in _stats.items()}
