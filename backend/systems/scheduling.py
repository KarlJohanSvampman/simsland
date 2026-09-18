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

# Per-contracted-work-day chance of a real exception replacing that
# day's work block entirely, re-rolled at every weekly regeneration --
# documented tunable, not derived from anything real-world.
SCHEDULE_EXCEPTION_CHANCE = 0.08
SCHEDULE_EXCEPTIONS = ["doctor_appointment", "holiday", "wfh"]


# =========================================================
# SHIFT WORK (weekend/inconvenient-hours jobs)
# =========================================================
# job_templates' own work_days field is real but unauthored in practice
# (confirmed: every sampled template -- cashier, bartender, police_officer,
# firefighter -- carries the identical placeholder [1,2,3,4,5], even for
# roles that obviously need weekend/night coverage in real life). Rather
# than a 577-entry manual content pass, this derives "does this job
# realistically require shift work" from fields every template already
# has (name/industry/tags), same deterministic-classifier approach as
# systems/job_complexity.py::classify_job(). Per the user's explicit ask:
# a job that needs inconvenient hours pays a real premium (applied once,
# at listing/hire time -- see jobs.py::_make_listing()) rather than
# scheduling.py silently discounting the disruption.
SHIFT_WORK_PAY_PREMIUM = 0.15  # +15% hourly for shift-work jobs

_SHIFT_WORK_KEYWORDS = (
    "retail", "hospitality", "restaurant", "food_service", "bar",
    "bartend", "nurse", "medical", "hospital", "clinic", "police",
    "fire", "emergency", "security", "cashier", "server", "cook",
    "chef", "entertainment", "casino", "hotel", "transit", "driver",
    "delivery", "paramedic",
)


def job_requires_shift_work(job_template):
    if not job_template:
        return False
    haystack = " ".join([
        job_template.get("name", "") or "",
        job_template.get("industry", "") or "",
        " ".join(job_template.get("tags", []) or []),
    ]).lower()
    return any(k in haystack for k in _SHIFT_WORK_KEYWORDS)


# =========================================================
# EXPENSE-DRIVEN WORK HOURS
# =========================================================

def _calc_min_work_hours(c, world):
    """
    How many hours must this character work this week to cover their
    share of household expenses?
    """
    # Confirmed live bug (player report: a retired 63-year-old still had
    # "work" blocks and a go_to_work expectation): this never checked
    # whether the character actually HAS a job at all -- share/wage below
    # always comes out positive (wage floors at 0.01 even when the real
    # hourly_wage is 0), then the hard floor a few lines down forces it
    # into a 20-40h/week band regardless. A character with no real job --
    # retired (either via systems/retirement.py::_do_retire(), or born
    # retired at generation, systems/character_gen.py::_assign_job()'s
    # own "retired" placeholder) or simply between jobs -- has no wage to
    # work toward and shouldn't get a work skeleton at all.
    job = c.get("job") or {}
    if not job.get("id") or job.get("id") == "retired":
        return 0.0

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

    # Hard caps: aim for a realistic 20-40h/week range. (Previously
    # 10-60h -- the 10h floor collided badly with the day-distribution
    # loop's own 10h/day cap, see generate_week_schedule(): a character
    # right at that floor got their entire week's hours crammed into a
    # single Monday shift and nothing else. Per the user's explicit ask,
    # doubled the floor and tightened the ceiling to a normal part-time-
    # to-full-time band.)
    return max(20.0, min(40.0, min_hours))


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

def _contract_day_work_hours(contract):
    """Real work_hours/work_days straight from a signed employment
    contract (systems/jobs.py::_stamp_employment_contract()) -- work_days
    uses the common 1=Monday..7=Sunday convention. Returns a
    {weekday_name: hours} dict, same shape generate_week_schedule()'s
    financial-need-driven distribution already produces."""
    work_hours = contract.get("work_hours") or [9, 17]
    work_days = contract.get("work_days") or [1, 2, 3, 4, 5]
    hours = max(0, work_hours[1] - work_hours[0])
    return {WEEKDAYS[(d - 1) % 7]: hours for d in work_days}


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

    # A real, signed employment contract (systems/jobs.py::
    # _stamp_employment_contract()) takes over the work-hours skeleton
    # entirely -- deterministic, from the contract's own work_hours/
    # work_days, not recomputed from financial need every week. A
    # character with no contract (not yet hired, or an older job that
    # predates this feature) keeps the existing financial-need-driven
    # behavior below unchanged.
    employment_contract = c.get("employment_contract")

    # Confirmed live bug (real player report): this used to greedily fill
    # each day up to MAX_HOURS_PER_DAY before ever moving to the next one
    # -- with min_hours' own 20h floor (previously 10h) sitting well
    # under that per-day cap, a character's ENTIRE week's hours landed on
    # a single Monday shift, nothing the rest of the week. Real jobs have
    # a consistent day-to-day shift length -- spread evenly across as
    # many of Mon-Fri as it takes to keep each shift a realistic length
    # (at least MIN_SHIFT_HOURS), collapsing toward fewer/longer days
    # only when the total is too small to support 5 real shifts, and
    # only overflowing into Saturday for a total too big to fit 5 days
    # at the per-day cap.
    MAX_HOURS_PER_DAY = 10.0
    MIN_SHIFT_HOURS   = 3.0

    # Per the user's explicit ask: weekends stay clear of work by default
    # -- ONLY a job whose own description reads as needing inconvenient/
    # weekend coverage (see job_requires_shift_work() above) is eligible
    # to schedule Saturday/Sunday shifts at all. A per-character rotation
    # offset (stable, from their own id) spreads WHICH days off shift
    # workers get across Sat/Sun/weekdays, rather than every shift worker
    # ending up with the identical Mon-Fri pattern non-shift jobs already
    # use, which would make the weekend-eligibility pointless in practice.
    job_templates = (world.get("definitions", {}) or {}).get("job_templates", {})
    job_template = job_templates.get(c.get("job_template_id"))
    is_shift_work = job_requires_shift_work(job_template)

    if is_shift_work:
        offset = sum(ord(ch) for ch in str(c.get("id", ""))) % 7
        day_pool = [WEEKDAYS[(offset + i) % 7] for i in range(7)]
        max_days = 6   # never a full 7-day week, even for shift workers
    else:
        day_pool = WORK_DAYS
        max_days = len(WORK_DAYS)

    if employment_contract:
        day_work_hours = _contract_day_work_hours(employment_contract)
    else:
        num_days = min(max_days, len(day_pool))
        while num_days > 1 and min_hours / num_days < MIN_SHIFT_HOURS:
            num_days -= 1

        hours_remaining = min_hours
        day_work_hours  = {}
        for i, day in enumerate(day_pool[:num_days]):
            days_left = num_days - i
            h = min(MAX_HOURS_PER_DAY, round(hours_remaining / days_left, 2))
            day_work_hours[day] = h
            hours_remaining -= h
        if hours_remaining > 0.01:
            overflow_day = day_pool[num_days] if num_days < len(day_pool) else "saturday"
            day_work_hours[overflow_day] = min(8.0, hours_remaining)

    # Pick a consistent start time for this character (trait-influenced).
    # Live bug report: night_owl/early_bird are physical_trait_templates
    # entries (c["physical_traits"]), not personality traits
    # (c["traits"]) -- this used to check the wrong field, so night_owl
    # (the only one of the two that even had a registry entry) never
    # actually affected anyone's schedule in practice. early_bird had no
    # registry entry at all until this round, on top of that.
    physical_traits = c.get("physical_traits", [])
    if "deep_sleeper" in physical_traits:
        preferred_work_start = random.choice([11, 12, 13])
    elif "night_owl" in physical_traits:
        preferred_work_start = random.choice([10, 11, 12])
    elif "early_bird" in physical_traits:
        preferred_work_start = random.choice([7, 8])
    else:
        preferred_work_start = random.choice([8, 9, 10])

    # A real contract's own start hour wins over the trait-based guess
    # above -- your employer decided your hours, not your sleep type.
    if employment_contract and employment_contract.get("work_hours"):
        preferred_work_start = employment_contract["work_hours"][0]

    # Unstructured/routineless: no fixed sleep block at all -- bedtime and
    # wake time drift day to day, so a single week-wide sleep window
    # doesn't fit them. Generated per-day in the loop below instead of
    # once here.
    freeform_sleep = bool({"unstructured", "routineless"} & set(physical_traits))

    schedule = {"week": {}, "last_generated": world.get("calendar", {}).get("timestamp", 0)}

    for day in WEEKDAYS:
        blocks = []

        # 1. Sleep
        if freeform_sleep:
            start_h = random.randint(21, 26) % 24   # 21:00-01:59, wrapping past midnight
            duration = random.randint(5, 9)
            end_h = (start_h + duration) % 24
            blocks.append({"start": f"{start_h:02d}:00", "end": f"{end_h:02d}:00", "activity": "sleep"})
        else:
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

        # 3. Work block -- a real contract keeps its base hours every
        # week (Confirmed Decision #14) rather than being recomputed
        # from financial need; the only week-to-week variation is a
        # small, real chance of a genuine exception replacing that
        # day's work block entirely, per the user's own "roll/test for
        # exceptions" ask.
        wh = day_work_hours.get(day, 0)
        if employment_contract and wh > 0 and random.random() < SCHEDULE_EXCEPTION_CHANCE:
            blocks.append({
                "start":    f"{preferred_work_start:02d}:00",
                "end":      f"{preferred_work_start + int(wh):02d}:00",
                "activity": random.choice(SCHEDULE_EXCEPTIONS),
                "source":   "exception",
            })
            wh = 0
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
                # Hygiene: a short "get ready" slot 30-60 min before work,
                # same insertion shape as the meal slots below (Wants plan
                # Phase D) -- gives update_schedule_runtime() something
                # real to fire a proactive take_shower intention from,
                # instead of hygiene only ever being a reactive interrupt
                # once the hygiene stat has already dropped too far.
                lead_min = random.choice([30, 45, 60])
                start_total_min = max(0, ws * 60 - lead_min)
                hs_h, hs_m = divmod(start_total_min, 60)
                blocks.append({
                    "start":    f"{hs_h:02d}:{hs_m:02d}",
                    "end":      f"{ws:02d}:00",
                    "activity": "hygiene",
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

OVERSLEEP_CHANCE = 0.35  # per natural wake-up, deep_sleeper only
OVERSLEEP_EXTRA_TICKS = (3600, 7200)  # 1-2 extra hours held asleep


def _lookup_block(day_plan, time_str):
    for block in day_plan:
        s, e = block["start"], block["end"]
        # Handle overnight sleep block
        if s > e:
            if time_str >= s or time_str < e:
                return block
        elif s <= time_str < e:
            return block
    return None


def get_current_activity(c, world):
    cal      = world.get("calendar", {})
    day      = cal.get("weekday", "").lower()
    time_str = f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"
    day_plan = c.get("schedule", {}).get("week", {}).get(day, [])
    block = _lookup_block(day_plan, time_str)
    return block["activity"] if block else None


def update_schedule_runtime(c, world):
    """Update the character's active schedule block each tick."""
    cal      = world.get("calendar", {})
    day      = cal.get("weekday", "").lower()
    time_str = f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"
    day_plan = c.get("schedule", {}).get("week", {}).get(day, [])

    current  = _lookup_block(day_plan, time_str)
    previous = c.get("active_schedule_block")
    tick     = world.get("tick", 0)

    # Deep sleeper oversleep -- a real, occasional "hard to wake up" beat
    # on top of the later preferred_work_start they already get (see
    # generate_week_schedule). Only relevant right at a sleep -> anything-
    # else transition; once rolled, the extra time is a real held window
    # (_oversleep_until_tick), not re-rolled every tick while it's active.
    if "deep_sleeper" in c.get("physical_traits", []):
        oversleep_until = c.get("_oversleep_until_tick")
        was_sleeping = bool(previous) and previous.get("activity") == "sleep"
        waking_now = current is None or current.get("activity") != "sleep"
        if oversleep_until is not None:
            if tick < oversleep_until:
                current = previous
            else:
                c["_oversleep_until_tick"] = None
        elif was_sleeping and waking_now and random.random() < OVERSLEEP_CHANCE:
            lo, hi = OVERSLEEP_EXTRA_TICKS
            c["_oversleep_until_tick"] = tick + random.randint(lo, hi)
            current = previous

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

    # Proactive survival/maintenance scheduling (Wants plan Phase D) --
    # this module's own docstring used to say body needs "are NOT
    # scheduled -- they fire as urgent interruptions," but in reality
    # people mostly eat because it's lunchtime, not because they're
    # already starving. Entering a scheduled eat/hygiene block now ALSO
    # raises a real, moderate-priority active_intentions entry (type
    # matches what body_intentions.py's reactive checks already use, so
    # strategy.py's existing dispatch picks it up identically) alongside
    # the current_intention set above. The reactive path is untouched and
    # still fires independently -- and at a higher category priority --
    # for a character who ignores this nudge and gets truly hungry/dirty.
    if current["activity"] in ("eat", "hygiene"):
        from brain.intentions import add_intention
        if current["activity"] == "eat":
            add_intention(c, {
                "type":     "eat_food",
                "category": "schedule",
                "priority": 55,
                "reason":   "It's about your usual mealtime.",
                "source":   "schedule",
            })
        else:
            add_intention(c, {
                "type":     "take_shower",
                "category": "schedule",
                "priority": 50,
                "reason":   "You're due to get ready before work.",
                "source":   "schedule",
            })
