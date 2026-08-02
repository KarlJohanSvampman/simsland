"""
systems/scheduling.py

Weekly schedule generation is driven by two real inputs:

  1. FINANCIAL NEED — the household's weekly expenses (rent, electricity,
     water, gasoline, internet, food) divided by the character's share and
     hourly wage gives the minimum hours they must work that week.
     Ambition/laziness traits add a buffer above or below that minimum.

  2. SOCIAL CONTRACT COMMITMENTS — any active contract that includes a
     recurring_activity term (e.g. "take kids to school Mon/Wed/Fri 08:00")
     gets blocked out as fixed schedule slots before leisure is allocated.

Body needs (toilet, sleep interruption, hunger) are NOT scheduled — they
fire as urgent interruptions via agent_loop._check_urgent_interruption and
abort/pause the current activity.
"""

import random
from datetime import datetime

WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]
WORK_DAYS = WEEKDAYS[:5]


# =========================================================
# EXPENSE-DRIVEN WORK HOURS
# =========================================================

def _calc_min_work_hours(c, world):
    """
    How many hours must this character work this week to cover their
    share of household expenses?
    """
    hid       = c.get("household_id")
    household = world.get("households", {}).get(hid) if hid else None

    if household:
        weekly_exp = household.get("weekly_expenses", 0)
        n_members  = max(1, len(household.get("members", [])))
        share      = weekly_exp / n_members
    else:
        # Solo / no household — estimate based on environment
        env   = world.get("environment", {})
        share = 150 * env.get("cost_of_living_index", 1.0)

    wage = max(0.01, c.get("hourly_wage", 12.0))
    min_hours = share / wage

    # Trait buffers
    if "ambitious" in c.get("traits", []):
        min_hours *= 1.25   # aim to save / advance
    if "lazy" in c.get("traits", []):
        min_hours *= 0.85   # works the bare minimum
    if "workaholic" in c.get("traits", []):
        min_hours *= 1.40

    # Hard caps: never fewer than 10h or more than 60h per week
    return max(10.0, min(60.0, min_hours))


# =========================================================
# SOCIAL CONTRACT RECURRING BLOCKS
# =========================================================

def _contract_blocks(c, world):
    """
    Return a list of {day, start_h, end_h, activity} dicts from any
    active social contract that has recurring_activity terms for this
    character.
    """
    blocks = []
    for contract in world.get("social_contracts", {}).values():
        if contract.get("status") != "active":
            continue
        if c["id"] not in contract.get("parties", []):
            continue
        for term in contract.get("terms", []):
            if term.get("party") != c["id"]:
                continue
            if term.get("check_type") != "recurring_activity":
                continue
            params = term.get("params", {})
            days   = params.get("days", WORK_DAYS)
            start  = params.get("start_hour", 8)
            end    = params.get("end_hour",   9)
            act    = params.get("activity", term.get("commitment", "errand"))
            for day in days:
                blocks.append({
                    "day":      day.lower(),
                    "start_h":  start,
                    "end_h":    end,
                    "activity": act,
                    "source":   "contract",
                })
    return blocks


# =========================================================
# GENERATE WEEK SCHEDULE
# =========================================================

def generate_week_schedule(c, world):
    """
    Build a full week schedule.

    Priority order per day:
      1. Sleep block (23:00-07:00, fixed)
      2. Social-contract recurring activity blocks
      3. Work blocks (distributed Mon-Fri to hit weekly hour target)
      4. Meal slots (12:00-13:00, 18:00-19:00) — skipped if overlapping
      5. Leisure (remaining evening time)
    """
    min_hours      = _calc_min_work_hours(c, world)
    contract_blks  = _contract_blocks(c, world)

    # Distribute work hours across Mon-Fri, then overflow to Sat if needed
    hours_remaining = min_hours
    day_work_hours  = {}
    for day in WORK_DAYS:
        if hours_remaining <= 0:
            break
        h = min(10.0, hours_remaining)    # max 10h/day
        day_work_hours[day] = h
        hours_remaining -= h
    if hours_remaining > 0:
        day_work_hours["saturday"] = min(8.0, hours_remaining)

    # Pick a consistent start time for this character (trait-influenced)
    if "night_owl" in c.get("traits", []):
        preferred_work_start = random.choice([10, 11, 12])
    elif "early_bird" in c.get("traits", []):
        preferred_work_start = random.choice([7, 8])
    else:
        preferred_work_start = random.choice([8, 9, 10])

    schedule = {"week": {}, "last_generated": world.get("calendar", {}).get("timestamp", 0)}

    for day in WEEKDAYS:
        blocks = []

        # 1. Sleep
        blocks.append({"start": "23:00", "end": "07:00", "activity": "sleep"})

        # 2. Contract recurring blocks for this day
        for cb in contract_blks:
            if cb["day"] == day:
                blocks.append({
                    "start":    f"{cb['start_h']:02d}:00",
                    "end":      f"{cb['end_h']:02d}:00",
                    "activity": cb["activity"],
                    "source":   "contract",
                })

        # 3. Work block
        wh = day_work_hours.get(day, 0)
        if wh > 0:
            ws = preferred_work_start
            we = ws + int(wh)
            # Avoid overlap with contract blocks
            for cb in contract_blks:
                if cb["day"] == day and cb["start_h"] < we and cb["end_h"] > ws:
                    ws = cb["end_h"]
                    we = ws + int(wh)
            we = min(we, 22)   # never work past 22:00
            if we > ws:
                blocks.append({
                    "start":    f"{ws:02d}:00",
                    "end":      f"{we:02d}:00",
                    "activity": "work",
                })

        # 4. Meals — only add if not overlapping with work/contract
        occupied = _occupied_hours(blocks)
        if 12 not in occupied and 13 not in occupied:
            blocks.append({"start": "12:00", "end": "13:00", "activity": "eat"})
        if 18 not in occupied and 19 not in occupied:
            blocks.append({"start": "18:00", "end": "19:00", "activity": "eat"})

        # 5. Leisure — evening gap between last daytime block and sleep
        occupied = _occupied_hours(blocks)
        leisure_start = max((h for h in occupied if h < 23), default=19) + 1
        if leisure_start < 22:
            blocks.append({
                "start":    f"{leisure_start:02d}:00",
                "end":      "22:00",
                "activity": "relax",
            })

        schedule["week"][day] = sorted(blocks, key=lambda b: b["start"])

    return schedule


def _occupied_hours(blocks):
    """Set of integer hours covered by existing blocks (excluding sleep)."""
    occupied = set()
    for b in blocks:
        if b["activity"] == "sleep":
            continue
        try:
            s = int(b["start"][:2])
            e = int(b["end"][:2])
            for h in range(s, e):
                occupied.add(h)
        except ValueError:
            pass
    return occupied


# =========================================================
# STAGGER HOUSEMATES
# =========================================================

def adjust_for_household(c, world):
    """Stagger work start times between housemates by 1 hour."""
    hid = c.get("household_id")
    if not hid:
        return

    members    = [
        x for x in world["characters"].values()
        if x.get("household_id") == hid
    ]
    member_ids = [x["id"] for x in members]
    try:
        offset = member_ids.index(c["id"]) % 2
    except ValueError:
        offset = 0

    if offset == 0:
        return

    for day, blocks in c.get("schedule", {}).get("week", {}).items():
        for b in blocks:
            if b["activity"] == "work" and b.get("source") != "contract":
                hour = int(b["start"][:2])
                hour = min(hour + offset, 13)   # don't push past 13:00
                end_hour = int(b["end"][:2]) + offset
                b["start"] = f"{hour:02d}:00"
                b["end"]   = f"{min(end_hour, 22):02d}:00"


# =========================================================
# RUNTIME TRACKING
# =========================================================

def get_current_activity(c, world):
    cal      = world.get("calendar", {})
    day      = cal.get("weekday", "").lower()
    time_str = f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"
    day_plan = c.get("schedule", {}).get("week", {}).get(day, [])

    for block in day_plan:
        s, e = block["start"], block["end"]
        # Handle overnight sleep block
        if s > e:
            if time_str >= s or time_str < e:
                return block["activity"]
        elif s <= time_str < e:
            return block["activity"]
    return None


def update_schedule_runtime(c, world):
    """Update the character's active schedule block each tick."""
    cal      = world.get("calendar", {})
    day      = cal.get("weekday", "").lower()
    time_str = f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"
    day_plan = c.get("schedule", {}).get("week", {}).get(day, [])

    current = None
    for block in day_plan:
        s, e = block["start"], block["end"]
        if s > e:
            if time_str >= s or time_str < e:
                current = block
                break
        elif s <= time_str < e:
            current = block
            break

    previous = c.get("active_schedule_block")
    if current == previous:
        return

    c["active_schedule_block"] = current

    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "schedule_block")

    if not current:
        return

    c["current_intention"] = {
        "type":   current["activity"],
        "source": current.get("source", "schedule"),
    }
