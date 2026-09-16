"""
systems/household_summary.py

Hourly/daily/weekly household activity recording and narration -- an
explicit sibling to systems/offgrid_narrative.py's off-grid trip
narration, but for the at-home side. While anyone is physically inside
a household's home building, every activity start/complete/interrupt
and every spoken line gets logged onto the household itself
(household["event_log"]), gated on real presence via
systems/home_presence.py::is_character_home() -- the event's OWN acting
character being home is what "as long as anybody is at home" cashes out
to, and it naturally covers a present guest's speech/activity too,
logged under the host household.

Cascade (each tier resets/deletes the tier below it once it rolls up --
see sim_loop.py for the calendar-boundary-gated wiring):
  event_log (<=1 hour of raw events)
    -> hourly_summaries (<=24, cleared once a day rolls up)
      -> daily_summaries (<=7, cleared once a week rolls up)
        -> weekly_summaries (kept, capped ~20) -- narrated in the
           house's own first-person voice, per the user's explicit ask

core/event_handlers.py subscribes _on_activity_started/etc. below to
the real event_bus events (activity_started/completed/interrupted,
speech_spoken) that feed the logger.
"""

from systems.home_presence import is_character_home

MAX_HOURLY_SUMMARIES = 24
MAX_DAILY_SUMMARIES = 7
MAX_WEEKLY_SUMMARIES = 20


# =========================================================
# ROOM RESOLUTION
# =========================================================
# c["room_id"] is confirmed dead codebase-wide (never actually set for
# characters) -- resolve directly from the snapshotted building_id/x/y
# every event payload already carries, exactly like every other live
# consumer of room data (systems/room_assignment.py's PROP path) does.

def _resolve_room_label(world, building_id, x, y):
    if not building_id or x is None or y is None:
        return None
    from systems.building_entrances import get_building_by_id
    building = get_building_by_id(world, building_id)
    if not building:
        return None
    from systems.navigation import get_room_at_position, runtime_room_id
    room_id = get_room_at_position(building, x, y)
    if not room_id:
        return None
    for room in world.get("runtime_rooms", []):
        if runtime_room_id(building_id, room.get("id")) == room_id:
            return room.get("type") or room.get("id")
    return room_id


# =========================================================
# EVENT LOGGING
# =========================================================

def _log_event(character_id, world, event_type, **fields):
    c = world.get("characters", {}).get(character_id)
    if not c:
        return
    if not is_character_home(c, world):
        return
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return

    building_id = fields.pop("building_id", None)
    x = fields.pop("x", None)
    y = fields.pop("y", None)
    room_label = _resolve_room_label(world, building_id, x, y)

    entry = {
        "tick": world.get("tick", 0),
        "type": event_type,
        "character_id": character_id,
        "room_label": room_label,
        **fields,
    }
    household.setdefault("event_log", []).append(entry)
    return household


def on_activity_started(data, world):
    character_id = data.get("character_id")
    household = _log_event(
        character_id, world, "activity_started",
        activity_type=data.get("activity_type"),
        target_id=data.get("target_id"),
        building_id=data.get("building_id"), x=data.get("x"), y=data.get("y"),
    )
    if household is not None:
        household.setdefault("_active_event_starts", {})[character_id] = world.get("tick", 0)


def _pop_start_tick(household, character_id, world):
    starts = household.setdefault("_active_event_starts", {})
    start_tick = starts.pop(character_id, None)
    if start_tick is None:
        return 0
    return max(0, world.get("tick", 0) - start_tick)


def on_activity_completed(data, world):
    character_id = data.get("character_id")
    c = world.get("characters", {}).get(character_id)
    if not c or not is_character_home(c, world):
        return
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    duration = _pop_start_tick(household, character_id, world)
    _log_event(
        character_id, world, "activity_completed",
        activity_type=data.get("activity_type"),
        target_id=data.get("target_id"), duration_ticks=duration,
        building_id=data.get("building_id"), x=data.get("x"), y=data.get("y"),
    )


def on_activity_interrupted(data, world):
    character_id = data.get("character_id")
    c = world.get("characters", {}).get(character_id)
    if not c or not is_character_home(c, world):
        return
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    duration = _pop_start_tick(household, character_id, world)
    _log_event(
        character_id, world, "activity_interrupted",
        activity_type=data.get("activity_type"),
        target_id=data.get("target_id"), duration_ticks=duration,
        building_id=data.get("building_id"), x=data.get("x"), y=data.get("y"),
    )


def on_speech_spoken(data, world):
    _log_event(
        data.get("character_id"), world, "speech",
        utterance=data.get("utterance"), target_id=data.get("target_id"),
        speech_act=data.get("speech_act"),
        building_id=data.get("building_id"), x=data.get("x"), y=data.get("y"),
    )


# =========================================================
# HOURLY -- condense event_log, reset it
# =========================================================

def update_household_hourly_summaries(world):
    from llm.household_summary_narration import generate_hourly_summary
    tick = world.get("tick", 0)
    for household in world.get("households", {}).values():
        events = household.get("event_log") or []
        if not events:
            continue
        text = generate_hourly_summary(household, events, world)
        household.setdefault("hourly_summaries", []).append({
            "id": f"h{tick}",
            "period_start_tick": events[0]["tick"],
            "period_end_tick": tick,
            "text": text,
            "tick_generated": tick,
        })
        del household["hourly_summaries"][:-MAX_HOURLY_SUMMARIES]
        household["event_log"] = []
        household["_active_event_starts"] = {}


# =========================================================
# DAILY -- condense hourly_summaries, delete them
# =========================================================

def update_household_daily_summaries(world):
    from llm.household_summary_narration import generate_daily_summary
    tick = world.get("tick", 0)
    cal = world.get("calendar", {})
    day_key = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}"
    for household in world.get("households", {}).values():
        hourlies = household.get("hourly_summaries") or []
        if not hourlies:
            continue
        hourly_texts = [h["text"] for h in hourlies]
        text = generate_daily_summary(household, hourly_texts, world)
        household.setdefault("daily_summaries", []).append({
            "id": f"d{tick}",
            "day_key": day_key,
            "text": text,
            "tick_generated": tick,
        })
        del household["daily_summaries"][:-MAX_DAILY_SUMMARIES]
        household["hourly_summaries"] = []


# =========================================================
# WEEKLY -- condense daily_summaries, delete them. Narrated as the
# house itself (llm/household_summary_narration.py::generate_weekly_
# summary's distinct first-person framing).
# =========================================================

def update_household_weekly_summaries(world):
    from llm.household_summary_narration import generate_weekly_summary
    tick = world.get("tick", 0)
    cal = world.get("calendar", {})
    week_key = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}"
    for household in world.get("households", {}).values():
        dailies = household.get("daily_summaries") or []
        if not dailies:
            continue
        daily_texts = [d["text"] for d in dailies]
        text = generate_weekly_summary(household, daily_texts, world)
        household.setdefault("weekly_summaries", []).append({
            "id": f"w{tick}",
            "week_key": week_key,
            "text": text,
            "tick_generated": tick,
        })
        del household["weekly_summaries"][:-MAX_WEEKLY_SUMMARIES]
        household["daily_summaries"] = []
