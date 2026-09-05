"""
systems/temporary_separation.py

After a real fight (systems/conflict_pipeline.py) resolves badly, one of
the two people involved may choose to move out for a while rather than
stay under the same roof. No prior scaffolding for a "second, temporary
residence" existed in this codebase (confirmed via research) -- household
membership was always single and permanent (systems/household_manager.py)
and every off-grid trip was a single short, capped stay (systems/
offgrid.py). This adds a genuinely new but small piece of state rather
than rebuilding either of those systems:

  c["temporary_residence"] = None | {
      "host_type": "family" | "friend",
      "host_id": <character id>,
      "origin_building_id": <the character's real home building>,
      "started_tick": int,
  }

Two paths, matching what the user described:
  - A trusted contact (parent/sibling, or a close/best-friend-tier friend)
    with their OWN real home takes the character in as a real, on-grid
    guest -- the character's building_id actually moves there (visible,
    walkable) while household_id (and therefore mail/mortgage/etc.) stays
    untouched, since this is meant to be temporary, not a real move.
  - If nobody suitable is available (or the willingness roll fails), the
    character instead goes off-grid for a few days "staying with family/
    friends" (systems/offgrid.py's existing abstracted-trip machinery,
    extended with the new "temporary_separation" uncapped-duration
    reason) -- this resolves and returns automatically via offgrid.py's
    own existing return-tick mechanism, no separate reconciliation check
    needed for that path.
"""

import random

from systems.confiding import tag_dramatic_memory

MIN_DAYS_BEFORE_RETURN_ROLL = 2
DAILY_RETURN_CHANCE_BASE = 0.15
DAILY_RETURN_CHANCE_PER_DAY = 0.05
OFFGRID_SEPARATION_DAYS = 3
TICKS_PER_DAY = 86400  # 1 tick = 1 nominal game-second, sim_loop.py::advance_calendar()


def _find_separation_host(c, world):
    """Best available real host -- a family member or a close/best friend
    with their own real home, not already sharing this character's own
    household. Returns (other_char, host_household, is_family, chance) or
    None if nobody at all qualifies."""
    chars = world.get("characters", {})
    households = world.get("households", {})
    candidates = []

    for other_id, rel in c.get("relationships", {}).items():
        other = chars.get(other_id)
        if not other or not other.get("alive", True):
            continue
        if other.get("household_id") == c.get("household_id"):
            continue
        is_family = any(l in rel.get("labels", []) for l in ("parent", "sibling"))
        is_trusted_friend = rel.get("designation") in ("close_friend", "best_friend")
        if not (is_family or is_trusted_friend):
            continue
        host_household = households.get(other.get("household_id"))
        if not host_household or not host_household.get("home_id"):
            continue
        trust = rel.get("trust", 0)
        score = trust + (50 if is_family else 0)
        chance = 0.9 if is_family else max(0.2, min(0.85, 0.3 + trust / 200.0))
        candidates.append((score, other, host_household, is_family, chance))

    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    _, other, host_household, is_family, chance = candidates[0]
    return other, host_household, is_family, chance


def begin_temporary_separation(c, world, reason="argument"):
    """Called after a bad conflict outcome. Returns True if the character
    actually moved out (on-grid or off-grid), False if nothing happened
    (e.g. already off-grid, already separated)."""
    if c.get("off_grid") or c.get("temporary_residence"):
        return False

    found = _find_separation_host(c, world)
    if found:
        other, host_household, is_family, chance = found
        if random.random() < chance:
            origin_building_id = c.get("building_id")
            c["temporary_residence"] = {
                "host_type": "family" if is_family else "friend",
                "host_id": other["id"],
                "origin_building_id": origin_building_id,
                "started_tick": world.get("tick", 0),
            }
            c["building_id"] = host_household["home_id"]
            tag_dramatic_memory(
                c, world,
                f"Things got so bad at home that I'm staying with {other.get('name', 'them')} for a while.",
                importance=0.75, people=[other["id"]],
            )
            return True

    # Fallback: an abstracted off-grid stay with family/friends elsewhere.
    from systems.offgrid import send_offgrid
    send_offgrid(c, world, "temporary_separation", OFFGRID_SEPARATION_DAYS * 24 * 60)
    tag_dramatic_memory(
        c, world,
        "Needed to get away for a few days after everything that happened at home.",
        importance=0.7,
    )
    return True


def maybe_return_from_separation(c, world):
    """Daily check for anyone currently staying with an on-grid host
    (the off-grid path resolves on its own via offgrid.py's existing
    return-tick machinery). Chance of reconciling and heading home rises
    the longer they've been away."""
    residence = c.get("temporary_residence")
    if not residence:
        return

    started = residence.get("started_tick", 0)
    days_away = max(0, (world.get("tick", 0) - started) // TICKS_PER_DAY)
    if days_away < MIN_DAYS_BEFORE_RETURN_ROLL:
        return

    chance = min(0.9, DAILY_RETURN_CHANCE_BASE + DAILY_RETURN_CHANCE_PER_DAY * days_away)
    if random.random() < chance:
        c["building_id"] = residence.get("origin_building_id")
        host = world.get("characters", {}).get(residence.get("host_id"))
        c["temporary_residence"] = None
        host_suffix = f" after staying with {host.get('name')}" if host else ""
        tag_dramatic_memory(
            c, world,
            f"Decided it was time to head back home{host_suffix}.",
            importance=0.5,
        )
