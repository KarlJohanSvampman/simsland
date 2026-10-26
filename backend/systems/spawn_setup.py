"""
systems/spawn_setup.py -- settle a character who has just been placed in the world.

generate_character() builds a person from nothing: a body at its defaults (0 hours awake, whatever the time of day), no
schedule until the tick loop gets to it, and no idea which room they are standing in. settle_new_character() is run once
when somebody is spawned (api/editor.py::_spawn_character_locked) and can be run again on anyone already in the world
(POST /admin/settle_characters):

  1. places them: if they stand inside a building they are in it, and in that room
  2. gives them a week schedule now (not whenever the loop reaches them), staggered against their housemates, and works
     out which block they are in
  3. sets the body clock to the time of day: hours awake since their schedule's wake-up, with the fatigue that goes with it
     (never lowering what they already have), so a person spawned at midnight is not a person who woke up a moment ago
  4. points the first hour at the day: a housemate in their sleep time who has a day ahead of them gets the bedtime
     intention straight away (systems/bedtime.py)

It is idempotent in effect: running it twice leaves the same schedule shape and does not push fatigue down. Returns a
dict saying what was done, for the admin route and the tests.
"""

from systems.body import AWAKE_FATIGUE_RATE_PER_TICK

HOUR = 3600
DEFAULT_WAKE_HOUR = 7


def _place(world, c):
    from systems.navigation import find_building_at, get_room_at_position
    building, _ = find_building_at(world, c.get("x", 0), c.get("y", 0))
    if not building:
        return None
    c["building_id"] = building["id"]
    c["room_id"] = get_room_at_position(building, c["x"], c["y"])
    return building["id"]


def wake_hour(c, today):
    """The hour the sleep block of `today` ends, from the schedule (the default if there is none)."""
    for b in (c.get("schedule") or {}).get("week", {}).get(today, []):
        if b.get("activity") == "sleep":
            try:
                return int(b["end"][:2]) + int(b["end"][3:5]) / 60.0
            except (KeyError, ValueError):
                break
    return float(DEFAULT_WAKE_HOUR)


def hours_since_waking(c, world):
    cal = world.get("calendar") or {}
    now = cal.get("hour", 12) + cal.get("minute", 0) / 60.0
    wake = wake_hour(c, str(cal.get("weekday", "")).lower())
    return now - wake if now >= wake else (24 - wake) + now        # before waking time: awake since yesterday's


def _set_body_clock(c, world):
    from systems.body import ensure_body
    ensure_body(c)
    body = c["body"]
    hours = max(0.0, hours_since_waking(c, world))
    body["hours_awake"] = max(body.get("hours_awake", 0) or 0, round(hours, 2))
    fatigue = hours * HOUR * AWAKE_FATIGUE_RATE_PER_TICK
    body["fatigue"] = round(max(body.get("fatigue", 0) or 0, min(fatigue, 70.0)), 2)
    return body["hours_awake"]


def settle_new_character(world, c):
    from systems.scheduling import generate_week_schedule, adjust_for_household, _lookup_block
    done = {"placed_in": _place(world, c)}
    from systems.offgrid import backfill_detail
    done["offgrid_detail"] = backfill_detail(c, world)
    from systems.vision import ensure_vision
    done["vision_added"] = ensure_vision(c)
    household = (world.get("households") or {}).get(c.get("household_id"))
    if household:
        from systems.household_beds import ensure_household_beds
        done["beds_added"] = ensure_household_beds(world, household)
        from systems.household_pantry import stock_pantry
        done["food_added"] = stock_pantry(world, household)

    c["schedule"] = generate_week_schedule(c, world)
    adjust_for_household(c, world)
    done["schedule_days"] = len(c["schedule"]["week"])

    cal = world.get("calendar") or {}
    day = str(cal.get("weekday", "")).lower()
    time_str = f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"
    c["active_schedule_block"] = _lookup_block(c["schedule"]["week"].get(day, []), time_str)
    done["block"] = (c["active_schedule_block"] or {}).get("activity")

    done["hours_awake"] = _set_body_clock(c, world)

    if c.get("conversation_log"):                     # one thread per set of people, whatever was logged before
        from brain.conversations import add_to_conversation_log
        add_to_conversation_log(c, None)

    try:
        from systems.body_intentions import generate_body_intentions
        generate_body_intentions(c, world)
    except Exception as exc:                          # the loop will do it on its next pass
        done["intentions_error"] = repr(exc)
    done["bedtime"] = any(i.get("type") == "sleep" and i.get("reason") == "bedtime" for i in c.get("active_intentions", []))
    return done
