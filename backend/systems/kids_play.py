"""
systems/kids_play.py -- children with friends nearby want to play with them.

Neighbour ties (systems/neighbours.py) give a child friends two doors down; this is what lets the child act on it. Every
PLAY_CADENCE ticks, a child who is free (awake, nothing running, not at school, not at work, daytime, needs not
screaming) and has a friend of about their age who is also free gets a `play_with_friend` intention naming that friend
-- go and ask if they can play, or invite them over. The intention is what the child's own thinking sees; nothing is
forced. The same friend isn't suggested again for PLAY_COOLDOWN ticks (`c["_play_log"][friend_id]`), and the urge is
dropped once it has lapsed.
"""

import random

from systems.neighbours import _is_person, _friends, KID_AGES

HOUR = 3600
PLAY_COOLDOWN = 3 * HOUR
PLAY_HOURS = (9, 19)                       # clock hours in which children think of playing
PLAY_CHANCE = 0.5                          # per eligible child per check, so not every kid gets the urge at once
PLAY_PRIORITY = 48
BUSY_BLOCKS = {"school", "sleep", "work"}
MAX_NEED_PRESSURE = 80                     # a child this hungry/tired thinks about food or bed, not playing


def _is_child(c):
    age = c.get("age")
    return age is not None and KID_AGES[0] <= age <= KID_AGES[1]


def _free(c, world):
    """Awake, on the grid, nothing running, not in a school/sleep/work block."""
    if not _is_person(c) or c.get("off_grid") or c.get("travel") or c.get("in_transit"):
        return False
    if (c.get("activity") or {}).get("type"):
        return False
    from systems.scheduling import get_current_activity
    if get_current_activity(c, world) in BUSY_BLOCKS:
        return False
    body = c.get("body") or {}
    hydration = body.get("hydration")
    if (body.get("hunger", 0) or 0) > MAX_NEED_PRESSURE or (hydration is not None and hydration < 100 - MAX_NEED_PRESSURE):
        return False
    return True


def _playmates(world, c):
    """Friends of `c` (children, same-age, not kin) who are free right now and not on cooldown, closest friend first."""
    tick = world.get("tick", 0)
    log = c.get("_play_log") or {}
    chars = world.get("characters", {})
    out = []
    for oid in _friends(c):
        o = chars.get(oid)
        if not o or not _is_child(o) or not _free(o, world):
            continue
        if tick - log.get(oid, -PLAY_COOLDOWN) < PLAY_COOLDOWN:
            continue
        out.append(((c["relationships"][oid].get("friendship", 0) or 0), o))
    return [o for _, o in sorted(out, key=lambda t: (-t[0], t[1]["id"]))]


def want_to_play(world, c):
    """The friend `c` wants to play with right now, or None."""
    if not _is_child(c) or not _free(c, world):
        return None
    hour = (world.get("calendar") or {}).get("hour")
    if hour is not None and not (PLAY_HOURS[0] <= hour < PLAY_HOURS[1]):
        return None
    mates = _playmates(world, c)
    return mates[0] if mates else None


def tick_kids_play(world):
    """Scheduled job: give free children with a free friend the urge to play with them."""
    from brain.intentions import add_intention
    tick = world.get("tick", 0)
    for c in list(world.get("characters", {}).values()):
        friend = want_to_play(world, c)
        if friend is None or random.random() >= PLAY_CHANCE:
            continue
        c.setdefault("_play_log", {})[friend["id"]] = tick
        add_intention(c, {
            "type": "play_with_friend",
            "category": "social",
            "priority": PLAY_PRIORITY,
            "target_id": friend["id"],
            "source": "kids_play",
            "reason": f"{friend['name']} lives close by and you feel like playing together -- go and ask "
                      f"{friend['name']} if they can play, or invite them over.",
        })
