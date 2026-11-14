"""
core/positions.py -- who is where, without reaching every character (step 5a).

"Who is near X" used to be a loop over every character (relationships built by time spent near each other, contagion
between people in the same building, the people a validation question can be put to). Each such loop reached every
character -- through the WorldView façade (core/world_view.py) that marks every one as touched, so locked for the step
and compared at the next flush, though only a handful were near anyone.

This is a read model of positions, read raw (dict access underneath the façade, so building it touches nobody) and
fresh on each call -- a few dict reads per character, as current as the old loop's. A system asks it who is near,
then reaches only those characters. With per-entity locks, a position read this way may be mid-change by another unit
of work (a step's worth stale at most) -- reading a neighbour's position is not owning it. In separate processes
(step 5b) this is the spatial index a position service keeps.

    snapshot(world)                  [(id, x, y, building_id, alive, off_grid, flags)] in the characters' order
    ids_near(world, c, radius, ...)  ids within a Manhattan radius (optionally: same building only)
    pairs_within(world, radius, keep=None)  (a, b) id pairs within radius, a before b in the characters' order
    by_building(world, keep=None)    {building_id: [ids]} in order
"""


def _raw(d, k, default=None):
    return dict.get(d, k, default) if isinstance(d, dict) else default


def snapshot(world):
    rows = []
    for cid, c in dict.items(dict.get(world, "characters") or {}):
        cs = _raw(c, "contagion_state") or {}
        rows.append((cid, _raw(c, "x", 0) or 0, _raw(c, "y", 0) or 0, _raw(c, "building_id"),
                     _raw(c, "alive", True) is not False, bool(_raw(c, "off_grid")),
                     {"workplace_npc": bool(_raw(c, "is_workplace_npc")),
                      "contagious": bool(_raw(cs, "is_contagious"))}))
    return rows


def ids_near(world, c, radius=None, same_building=False):
    """Ids of the characters near `c` (not c): in its building when same_building, else within `radius`."""
    me = c.get("id")
    bid = c.get("building_id")
    x, y = c.get("x", 0) or 0, c.get("y", 0) or 0
    out = []
    for cid, ox, oy, obid, alive, _off, _f in snapshot(world):
        if cid == me:
            continue
        if same_building:
            if obid == bid:
                out.append((cid, alive, obid))
        elif radius is not None and abs(ox - x) + abs(oy - y) <= radius:
            out.append((cid, alive, obid))
    return out


def pairs_within(world, radius, keep=None):
    """(a, b) id pairs within `radius` (Manhattan), a earlier than b in the characters' order; `keep(row)` filters."""
    rows = [r for r in snapshot(world) if keep is None or keep(r)]
    out = []
    for i in range(len(rows)):
        a = rows[i]
        for j in range(i + 1, len(rows)):
            b = rows[j]
            if abs(a[1] - b[1]) + abs(a[2] - b[2]) <= radius:
                out.append((a[0], b[0]))
    return out


def by_building(world, keep=None):
    groups = {}
    for r in snapshot(world):
        if keep is None or keep(r):
            groups.setdefault(r[3], []).append(r[0])
    return groups
