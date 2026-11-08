"""
systems/building_grid.py -- what's inside a building, where its ways in and out are, and walking it without going
through walls.

Pathing used to treat a floorplan as open ground: the indoor A* (systems/navigation.py) looked only at
navigation.blocked tiles, so routes went straight through walls, and "indoors" was any tile with a floor -- a hallway
authored with walls but no floor counted as yard, and a patio with a wooden floor counted as indoors. Characters ended
up "outside" in the middle of the house, or at the back of a house looking for a way in (2026-11-04).

Now, per floorplan (cached here, by object):

  inside     every floored tile, plus the tiles that can't be reached from beyond the plot without passing a wall,
             window or door (a room authored without a floor is still indoors).
  entrances  the doors between an inside tile and an outside one: {"inside", "outside", "side"} in local coords.
  path()     4-way A* over the plot that never crosses a wall or window (doors are walked through), avoiding
             navigation.blocked tiles.

Edges: a wall on either tile's facing side blocks the step between them.
"""

from heapq import heappush, heappop

STEP = {(0, -1): ("north", "south"), (0, 1): ("south", "north"), (1, 0): ("east", "west"), (-1, 0): ("west", "east")}
OFFSET = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
MAX_EXPANSIONS = 20000
_CACHE = {}


def edge(tiles, a, b):
    """What stands between neighbouring tiles a and b: None, "door", "window" or "wall". A door on either tile's
    facing side wins: floorplans often have the door on one tile and a leftover wall on the other's matching side."""
    near, far = STEP.get((b[0] - a[0], b[1] - a[1]), (None, None))
    if not near:
        return None
    kinds = []
    for tile, side in ((a, near), (b, far)):
        wall = ((tiles.get(f"{tile[0]},{tile[1]}") or {}).get("walls") or {}).get(side)
        if wall:
            kinds.append(wall.get("type") or "wall")
    if "door" in kinds:
        return "door"
    if "window" in kinds:
        return "window"
    return "wall" if kinds else None


def _bounds(floorplan):
    tiles = floorplan.get("tiles") or {}
    keys = [tuple(int(v) for v in k.split(",")) for k in tiles]
    w = floorplan.get("width") or (max((k[0] for k in keys), default=-1) + 1)
    h = floorplan.get("height") or (max((k[1] for k in keys), default=-1) + 1)
    return int(w), int(h)


def analyse(floorplan):
    """{"inside": set of (x, y), "entrances": [...]} for a floorplan, cached on it."""
    tiles = floorplan.get("tiles") or {}
    sig = (len(tiles), floorplan.get("width"), floorplan.get("height"))
    # keyed by the tiles dict: resolve_floorplan() hands back a fresh merged dict every call, but its "tiles" is the
    # template's own, shared (keying on the floorplan itself missed every time and re-flooded on every lookup)
    cached = _CACHE.get(id(tiles))
    if cached and cached.get("sig") == sig and cached.get("ref") is tiles:
        return cached
    w, h = _bounds(floorplan)
    has_walls = any((t or {}).get("walls") and any((t.get("walls") or {}).values()) for t in tiles.values())

    if not has_walls:
        inside = {tuple(int(v) for v in k.split(",")) for k, t in tiles.items() if (t or {}).get("floor", True)}
    else:
        # flood from beyond the plot: a border tile is reached unless its outward side has a wall, window or door
        outside = set()
        stack = []
        for x in range(w):
            for y in range(h):
                for side, (dx, dy) in OFFSET.items():
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        continue
                    wall = ((tiles.get(f"{x},{y}") or {}).get("walls") or {}).get(side)
                    if not wall and (x, y) not in outside:
                        outside.add((x, y))
                        stack.append((x, y))
        while stack:
            x, y = stack.pop()
            for (dx, dy) in STEP:
                n = (x + dx, y + dy)
                if n in outside or not (0 <= n[0] < w and 0 <= n[1] < h):
                    continue
                if edge(tiles, (x, y), n):
                    continue
                outside.add(n)
                stack.append(n)
        # enclosed tiles (a room authored without a floor is still a room), and every floored tile (authored walls
        # have gaps -- a house whose outline isn't closed would otherwise come out as all yard)
        inside = {(x, y) for x in range(w) for y in range(h) if (x, y) not in outside and f"{x},{y}" in tiles}
        inside |= {tuple(int(v) for v in k.split(",")) for k, t in tiles.items() if (t or {}).get("floor", True)}

    entrances, seen = [], set()
    for key, t in tiles.items():
        for side, wall in ((t or {}).get("walls") or {}).items():
            if not wall or wall.get("type") != "door":
                continue
            a = tuple(int(v) for v in key.split(","))
            dx, dy = OFFSET.get(side, (0, 0))
            b = (a[0] + dx, a[1] + dy)
            a_in, b_in = a in inside, b in inside
            if a_in == b_in:
                continue                                   # between two rooms, or two yard tiles
            pair = (a, b) if a_in else (b, a)
            if pair in seen:
                continue
            seen.add(pair)
            entrances.append({"inside": pair[0], "outside": pair[1], "side": side})

    out = {"sig": sig, "ref": tiles, "inside": inside, "entrances": entrances, "width": w, "height": h}
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[id(tiles)] = out                      # kept off the floorplan itself: it may be saved with the world
    return out


def is_inside(floorplan, x, y):
    return (int(x), int(y)) in analyse(floorplan)["inside"]


def path(floorplan, start, goal, blocked=()):
    """Local-coordinate tiles from start to goal (start excluded, like navigation.astar), [] if there is no way
    that doesn't go through a wall. Steps may leave the plot by up to a tile (round the outside of a corner)."""
    start, goal = tuple(start), tuple(goal)
    if start == goal:
        return []
    tiles = floorplan.get("tiles") or {}
    g = analyse(floorplan)
    w, h = g["width"], g["height"]
    blocked = {tuple(b) for b in blocked} - {start}
    open_set = [(abs(goal[0] - start[0]) + abs(goal[1] - start[1]), 0, start)]
    came, cost = {start: None}, {start: 0}
    n = 0
    while open_set and n < MAX_EXPANSIONS:
        _, gc, cur = heappop(open_set)
        n += 1
        if cur == goal:
            out = []
            while cur != start:
                out.append(cur)
                cur = came[cur]
            return list(reversed(out))
        if gc > cost.get(cur, 1 << 30):
            continue
        for d in STEP:
            nxt = (cur[0] + d[0], cur[1] + d[1])
            if not (-1 <= nxt[0] <= w and -1 <= nxt[1] <= h) or nxt in blocked:
                continue
            if edge(tiles, cur, nxt) in ("wall", "window"):
                continue
            c = gc + 1
            if c < cost.get(nxt, 1 << 30):
                cost[nxt] = c
                came[nxt] = cur
                heappush(open_set, (c + abs(goal[0] - nxt[0]) + abs(goal[1] - nxt[1]), c, nxt))
    return []
