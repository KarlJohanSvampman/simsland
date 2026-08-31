"""
systems/diary.py

Diary-writing: a routine some sims have (gated on the keep_a_diary
hobby + owning a real diary item), summarizing their day in their own
words at day's end, grounded in their REAL stored memories from that
day -- see llm/diary_narration.py. Also doubles as an informal
verification tool for the memory system: a hollow/generic entry with no
real content behind it is a real signal something upstream isn't
storing memories correctly.
"""

DIARY_LOOKBACK_TICKS = 86400  # ~1 sim-day of memories
MAX_DIARY_ENTRIES = 60


def _day_key(world):
    cal = world.get("calendar", {})
    return f"{cal.get('year', 0):04d}-{cal.get('month', 0):02d}-{cal.get('day', 0):02d}"


def sync_diary_hobby(c, world):
    """Called wherever hobbies get (re)assigned -- see systems/sports.py's
    identical sync-on-pickup pattern. Picking up keep_a_diary grants a
    real starter diary, since no hobby's required_items get auto-stocked
    today (confirmed via grep this session)."""
    if "keep_a_diary" not in c.get("hobbies", []):
        return False
    from systems.personal_items import get_item_by_template, make_item, add_item
    if get_item_by_template(c, "diary"):
        return False
    add_item(c, make_item("diary", world=world))
    return True


def _todays_memories(c, world):
    tick = world.get("tick", 0)
    cutoff = tick - DIARY_LOOKBACK_TICKS
    return [m for m in c.get("memories", []) if m.get("tick", 0) >= cutoff]


def write_diary_entry(c, world):
    """Generates and records a real entry right now -- shared by both
    the automatic day-end routine (maybe_write_diary) and a direct
    player/LLM-chosen write_diary action."""
    from systems.personal_items import get_item_by_template
    if not get_item_by_template(c, "diary"):
        return None

    day_memories = _todays_memories(c, world)

    from llm.diary_narration import generate_diary_entry
    text = generate_diary_entry(c, world, day_memories)

    entry = {
        "tick":            world.get("tick", 0),
        "date":            _day_key(world),
        "text":            text,
        "memory_count":    len(day_memories),
    }
    entries = c.setdefault("diary_entries", [])
    entries.append(entry)
    del entries[:-MAX_DIARY_ENTRIES]
    return entry


def maybe_write_diary(c, world):
    """Daily-cadence, day-key-gated (see sim_loop.py) -- only characters
    with the keep_a_diary hobby AND a real diary in hand write
    automatically at day's end."""
    if "keep_a_diary" not in c.get("hobbies", []):
        return None
    today = _day_key(world)
    if c.get("_last_diary_day") == today:
        return None
    c["_last_diary_day"] = today
    return write_diary_entry(c, world)
