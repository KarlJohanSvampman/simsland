"""
core/entity_patch.py -- an entity's change as a field-level patch (docs/step5b_plan.md: partitioned ownership).

A unit of work that changed an entity another partition owns sends the owner the change, not the entity: only the
paths it touched, so two partitions changing different fields of the same entity both land.

    diff(old, new) -> [op]     what turns `old` into `new`
    apply(entity, ops)         carry them out on the owner's copy (in place)

ops (paths are lists of keys / list indexes):
    ["set", path, value]       a value changed or appeared (a dict key added goes on the end, as an in-place write would)
    ["del", path]              a dict key removed
    ["append", path, items]    a list that only grew at the end: on apply, the items go on the end of the OWNER's list
                               -- an append made there meanwhile stays (two partitions adding memories both land)
    ["trim", path, n]          a capped list dropped its n oldest items (with an append, the usual "keep the last N")

Merge rule otherwise: for the same path, the patch applied later wins (the owner applies patches in arrival order).
"""

import copy

_MISSING = object()
_TRIM_SEARCH = 64            # how many dropped-from-the-front items a capped list is checked for


def same(a, b):
    """Equal as JSON would see it: True is not 1, 1.0 is not 1 (Python's == says they are)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def _prefix(short, lst):
    return len(lst) >= len(short) and all(same(x, y) for x, y in zip(short, lst))


def diff(old, new, path=None):
    path = path or []
    if type(old) is not type(new) and not (isinstance(old, dict) and isinstance(new, dict)) \
            and not (isinstance(old, list) and isinstance(new, list)):
        return [] if same(old, new) else [["set", path, copy.deepcopy(new)]]
    if isinstance(new, dict):
        kept = [k for k in old if k in new]
        if list(new) != kept + [k for k in new if k not in old]:
            return [["set", path, copy.deepcopy(new)]]        # reordered (replaced whole): key order matters
        ops = []
        for k in old:
            if k not in new:
                ops.append(["del", path + [k]])
        for k, v in new.items():
            if k not in old:
                ops.append(["set", path + [k], copy.deepcopy(v)])
            elif not same(old[k], v):
                ops.extend(diff(old[k], v, path + [k]))
        return ops
    if isinstance(new, list):
        if same(old, new):
            return []
        n_old = len(old)
        if len(new) > n_old and _prefix(old, new):
            return [["append", path, copy.deepcopy(new[n_old:])]]
        for k in range(1, min(n_old, _TRIM_SEARCH) + 1):          # capped: dropped k from the front, maybe appended
            rest = old[k:]
            if _prefix(rest, new):
                ops = [["trim", path, k]]
                if len(new) > len(rest):
                    ops.append(["append", path, copy.deepcopy(new[len(rest):])])
                return ops
        if len(new) == n_old:                                      # same length: element by element
            ops = []
            for i, (a, b) in enumerate(zip(old, new)):
                if not same(a, b):
                    ops.extend(diff(a, b, path + [i]))
            return ops
        return [["set", path, copy.deepcopy(new)]]
    return [] if same(old, new) else [["set", path, copy.deepcopy(new)]]


def _parent(entity, path, create=True):
    cur = entity
    for key in path[:-1]:
        if isinstance(cur, list):
            if not isinstance(key, int) or key >= len(cur):
                return None
            cur = cur[key]
        else:
            nxt = cur.get(key, _MISSING) if isinstance(cur, dict) else _MISSING
            if nxt is _MISSING or not isinstance(nxt, (dict, list)):
                if not create or not isinstance(cur, dict):
                    return None
                cur[key] = {}
                nxt = cur[key]
            cur = nxt
    return cur


def _target(entity, path):
    cur = entity
    for key in path:
        if isinstance(cur, list):
            if not isinstance(key, int) or key >= len(cur):
                return None
            cur = cur[key]
        elif isinstance(cur, dict):
            if key not in cur:
                return None
            cur = cur[key]
        else:
            return None
    return cur


def apply(entity, ops):
    """Carry out a patch on `entity` (in place). Returns how many ops landed (one whose place no longer exists on the
    owner -- a list since shortened, a key's parent replaced by a value -- is skipped)."""
    landed = 0
    for op in ops:
        kind, path = op[0], op[1]
        if kind in ("append", "trim"):
            lst = _target(entity, path)
            if lst is None and kind == "append":
                parent = _parent(entity, path)
                if isinstance(parent, dict):
                    parent[path[-1]] = []
                    lst = parent[path[-1]]
            if not isinstance(lst, list):
                continue
            if kind == "append":
                lst.extend(copy.deepcopy(op[2]))
            else:
                del lst[:op[2]]
            landed += 1
            continue
        if not path:
            continue
        parent = _parent(entity, path, create=(kind == "set"))
        if parent is None:
            continue
        key = path[-1]
        if kind == "set":
            if isinstance(parent, list):
                if isinstance(key, int) and key < len(parent):
                    parent[key] = copy.deepcopy(op[2])
                    landed += 1
            else:
                parent[key] = copy.deepcopy(op[2])
                landed += 1
        elif kind == "del" and isinstance(parent, dict) and key in parent:
            del parent[key]
            landed += 1
    return landed
