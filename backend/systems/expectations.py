"""
systems/expectations.py

Recurring self-expectations ("checkboxes") -- what a character tries to
live up to (of themselves, and of others, since someone else's failure
can cost the character their own checkbox), at daily/weekly/monthly/
yearly/once cadences (definitions.json's expectation_templates).

Design note (deviates slightly from the plan's literal field names, same
intent): due-tracking is CALENDAR-PERIOD-anchored (a "daily" expectation
tracks which real calendar day it was last satisfied in, a "weekly" one
tracks ISO week, etc.) rather than a rolling next_due_tick computed by
tick-duration -- this avoids drift and is trivially testable by just
setting world["calendar"] directly, unlike lt_needs.py's pure
tick-duration approach (which this system otherwise mirrors for the
satisfy/frustration/stress feedback shape).

c["expectations"][template_id] = {
    "template_id", "cadence", "category", "of_self", "requires_others",
    "current_period_key",       # e.g. "2026-08-29" for daily, "2026-W35" weekly
    "satisfied_this_period",    # bool
    "last_satisfied_tick",
    "streak", "missed_count",
    "frustration",              # 0-1, mirrors lt_needs.py's shape
    "status",                   # "pending" | "satisfied" | "missed"
    "last_missed_blame",        # [char_id, ...] -- populated by callers that
                                 # know who specifically didn't show (see
                                 # systems/expectation_planner.py)
    "last_miss_reason",         # short real-cause string, read off the
                                 # character's own state at miss-detection
                                 # time (see _diagnose_miss_reason) --
                                 # folded into the "missed" intention's
                                 # reason text so it says WHY, not just that.
}

assign_expectations() is idempotent and safe to call every update pass
(see update_expectations() below) rather than needing hooks scattered
across job/marriage/birth life-event handlers -- any household/
employment change gets picked up naturally on the next cadence tick.
"""

from datetime import date, timedelta

MISS_STRESS_DELTA     = 5.0   # mirrors lt_needs.py::satisfy_lt_need()'s -5 stress, inverted
SATISFY_STRESS_DELTA  = 5.0
FRUSTRATION_DELTA     = 0.4   # mirrors lt_needs.py's FRUSTRATION_DECAY_ON_SATISFY


# =========================================================
# ROLE TAGS (drives which expectation_templates apply)
# =========================================================

def _character_tags(c, world=None):
    """Computed from LIVE state (age/employment/household composition),
    not a stored archetype field -- mirrors character_gen.py's own
    job/hobby assignment, which always derives from live data rather
    than a label."""
    tags = set()

    age_group = c.get("age_group")
    if age_group in ("adult", "elderly"):
        tags.add("adult")
    if age_group in ("child", "teen"):
        tags.add("child_or_teen")
    if c.get("employed"):
        tags.add("employed")
    # 16 is a common US learner-eligibility age (real state minimums for a
    # full license vary 16-18) -- documented approximation, not a precise
    # rule. Deliberately its own tag, not age_group=="teen" (13-17), since
    # driving age cuts across that boundary.
    if c.get("age", 0) >= 16:
        tags.add("driving_age")

    if world is not None:
        household = world.get("households", {}).get(c.get("household_id"))
        if household:
            members = household.get("members", [])
            characters = world.get("characters", {})
            has_child_in_household = any(
                characters.get(mid, {}).get("age_group") in ("child", "teen")
                for mid in members
            )
            if has_child_in_household and age_group in ("adult", "elderly"):
                tags.add("parent")
                tags.add("provider_archetype")
            # Confirmed live bug: a 6-year-old sharing a household with
            # anyone else (no age check at all here) qualified for
            # make_dinner's "cohabiting" tag on its own -- make_dinner's
            # tags are OR-matched (parent/provider_archetype/cohabiting),
            # so a child was picking up a real adult obligation, complete
            # with real missed-expectation stress/grievance consequences,
            # purely for living with someone. "cohabiting" is meant for
            # roommate-style shared-duty expectations, which a young
            # child can't meaningfully hold regardless of who they live
            # with.
            if len(members) > 1 and age_group != "child":
                tags.add("cohabiting")

    return tags


def assign_expectations(c, defs, world=None):
    """Adds any expectation_templates entry this character's current
    tags qualify for and doesn't already have. Never removes an
    existing entry -- a character who stops qualifying (e.g. kids move
    out) keeps their history/streak rather than losing it silently."""
    templates = defs.get("expectation_templates", {})
    if not templates:
        return

    existing = c.setdefault("expectations", {})
    tags = _character_tags(c, world)

    for tid, t in templates.items():
        if tid in existing:
            continue
        template_tags = set(t.get("tags", []))
        if template_tags and not (template_tags & tags):
            continue

        existing[tid] = {
            "template_id":           tid,
            "cadence":               t.get("cadence", "daily"),
            "category":              t.get("category", "schedule"),
            "of_self":               t.get("of_self", True),
            "requires_others":       t.get("requires_others", False),
            "current_period_key":    None,
            "satisfied_this_period": False,
            "last_satisfied_tick":   None,
            "streak":                0,
            "missed_count":          0,
            "frustration":           0.0,
            "status":                "pending",
            "last_missed_blame":     [],
            # Real time window for the CURRENT period -- computed by
            # update_expectations()/_compute_window() at each rollover,
            # None until then (or permanently, for anything not
            # schedule-linked -- see _SCHEDULE_LINKED_EXPECTATIONS).
            "window_start_tick":     None,
            "window_end_tick":       None,
        }


def synthesize_expectation(c, expectation_id, cadence, category, of_self,
                            requires_others=False, blame_ids=None, grievance_event_type=None):
    """Directly construct a real, non-registry-backed expectation entry
    -- see systems/jobs.py's contract-responsibility synthesis (and
    later, systems/insurance.py's equivalent). Bypasses assign_
    expectations()'s registry-only path but produces the EXACT same
    shape that path would, so update_expectations()/satisfy_expectation()
    work on it identically to any registry-driven expectation -- the
    only two additions are last_missed_blame (pre-populated, since a
    contract already knows who's responsible for a promise made TO this
    character -- no dynamic discovery needed) and grievance_event_type
    (read by _attribute_blame()'s registry-optional fallback above)."""
    entry = {
        "template_id":           expectation_id,
        "cadence":               cadence,
        "category":              category,
        "of_self":               of_self,
        "requires_others":       requires_others,
        "current_period_key":    None,
        "satisfied_this_period": False,
        "last_satisfied_tick":   None,
        "streak":                0,
        "missed_count":          0,
        "frustration":           0.0,
        "status":                "pending",
        "last_missed_blame":     list(blame_ids or []),
        "grievance_event_type":  grievance_event_type,
        "window_start_tick":     None,
        "window_end_tick":       None,
    }
    c.setdefault("expectations", {})[expectation_id] = entry
    return entry


# =========================================================
# CALENDAR PERIOD KEYS
# =========================================================

def _current_period_key(cadence, calendar):
    if not calendar:
        return None
    if cadence == "daily":
        return f"{calendar['year']:04d}-{calendar['month']:02d}-{calendar['day']:02d}"
    if cadence == "weekly":
        y, w, _ = date(calendar["year"], calendar["month"], calendar["day"]).isocalendar()
        return f"{y:04d}-W{w:02d}"
    if cadence == "monthly":
        return f"{calendar['year']:04d}-{calendar['month']:02d}"
    if cadence == "yearly":
        return f"{calendar['year']:04d}"
    return None   # "once" -- no recurring period; handled by whatever
                   # instantiates/completes it directly (e.g. a plan).


# =========================================================
# UPDATE (called on a slow cadence -- see sim_loop.py/agent_loop.py)
# =========================================================

# Small, explicit map: template_id -> the real schedule-block "activity"
# name (systems/scheduling.py) this expectation's real time window
# should derive from, when the character has a matching block today.
# Anything not listed here (or with no matching block that day) falls
# back to window_end_tick=None -- the existing whole-period rollover
# check (unchanged) is what catches a miss for those, exactly like
# before this feature existed.
_SCHEDULE_LINKED_EXPECTATIONS = {
    "make_dinner":            "eat",
    "family_dinner_together": "eat",
    "go_to_work":             "work",
}


def _hhmm_to_tick(hhmm, calendar, world):
    """Real absolute tick for an "HH:MM" schedule-block boundary,
    relative to the character's real current calendar time today."""
    h, m = (int(x) for x in hhmm.split(":"))
    now_h, now_m = calendar.get("hour", 0), calendar.get("minute", 0)
    return world.get("tick", 0) + ((h * 60 + m) - (now_h * 60 + now_m)) * 60


_WEEKDAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _calendar_moment_to_tick(world, calendar, target_date, hour=0, minute=0):
    """Real absolute tick for an arbitrary real calendar date+time,
    relative to the character's real current calendar moment -- a
    generalization of _hhmm_to_tick's "today" assumption to any date."""
    today = date(calendar["year"], calendar["month"], calendar["day"])
    days_delta = (target_date - today).days
    now_minutes = calendar.get("hour", 0) * 60 + calendar.get("minute", 0)
    target_minutes = hour * 60 + minute
    return world.get("tick", 0) + days_delta * 86400 + (target_minutes - now_minutes) * 60


def _fallback_window(cadence, calendar, world):
    """Real, calendar-derived window for any cadence with no specific
    schedule-block anchor -- per the user's explicit ask, EVERY
    expectation gets a real start/end, capped at 7 real days even for a
    monthly/yearly one (which uses the last 7 days before its real
    deadline as the real "due soon" window, rather than the whole
    month/year)."""
    today = date(calendar["year"], calendar["month"], calendar["day"])

    if cadence == "daily":
        start = _calendar_moment_to_tick(world, calendar, today, 0, 0)
        return start, start + 86400

    if cadence == "weekly":
        wd = _WEEKDAY_INDEX.get((calendar.get("weekday") or "").lower(), 0)
        week_start = today - timedelta(days=wd)
        start = _calendar_moment_to_tick(world, calendar, week_start, 0, 0)
        return start, start + 7 * 86400

    if cadence == "monthly":
        next_month = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        window_start_date = next_month - timedelta(days=7)
        start = _calendar_moment_to_tick(world, calendar, window_start_date, 0, 0)
        end = _calendar_moment_to_tick(world, calendar, next_month, 0, 0)
        return start, end

    if cadence == "yearly":
        year_end = date(today.year + 1, 1, 1)
        window_start_date = year_end - timedelta(days=7)
        start = _calendar_moment_to_tick(world, calendar, window_start_date, 0, 0)
        end = _calendar_moment_to_tick(world, calendar, year_end, 0, 0)
        return start, end

    return None, None


def _compute_window(c, world, template_id, calendar, cadence=None):
    """A real (window_start_tick, window_end_tick) for the CURRENT
    period -- a matching real schedule block today (make_dinner/
    family_dinner_together/go_to_work) wins when one exists; otherwise
    falls back to a real calendar-derived window for the expectation's
    own cadence (see _fallback_window) so every expectation gets a real
    timespan, not just the schedule-linked handful."""
    activity = _SCHEDULE_LINKED_EXPECTATIONS.get(template_id)
    if activity:
        weekday = (calendar.get("weekday") or "").lower()
        day_blocks = (c.get("schedule") or {}).get("week", {}).get(weekday, [])
        matches = [b for b in day_blocks if b.get("activity") == activity]
        if matches:
            # "eat" maps to both lunch and dinner blocks in scheduling.py
            # -- the LATER one is what "make dinner"/"family dinner
            # together" actually mean; for "work" there's only ever one
            # real block, so [-1] is a no-op there.
            block = matches[-1]
            start = _hhmm_to_tick(block["start"], calendar, world)
            end = _hhmm_to_tick(block["end"], calendar, world)
            return start, end
    return _fallback_window(cadence, calendar, world)


def _has_scheduled_work_today(c, world):
    """Per the user's explicit ask: "go_to_work" should never come up
    missed on a day the character wasn't even scheduled to work in the
    first place (a day off in a shift rotation, a weekend for a Mon-Fri
    job, ...). systems/scheduling.py's own week keys are lowercase full
    weekday names (WEEKDAYS); world["calendar"]["weekday"] is produced by
    strftime("%A") (capitalized) -- lowered here to match."""
    weekday = (world.get("calendar", {}).get("weekday") or "").lower()
    day_blocks = (c.get("schedule") or {}).get("week", {}).get(weekday, [])
    return any(b.get("activity") == "work" for b in day_blocks)


def update_expectations(c, world):
    defs = world.get("definitions", {})
    assign_expectations(c, defs, world)

    calendar = world.get("calendar", {})
    if not calendar:
        return

    tick = world.get("tick", 0)

    for nd in c.get("expectations", {}).values():
        period = _current_period_key(nd["cadence"], calendar)
        if period is None:
            # "once" cadence -- no real recurring calendar period, but
            # still gets a real, regenerating 7-day window per the
            # user's explicit ask ("all of them ought to have a
            # timespan... and then we generate a new one") until it's
            # actually satisfied, at which point it's truly done and
            # left alone (matching "once" semantics).
            if nd["status"] == "satisfied":
                continue
            window_end = nd.get("window_end_tick")
            if window_end is None or tick >= window_end:
                if window_end is not None and not nd["satisfied_this_period"] and nd["status"] != "missed":
                    nd["missed_count"] += 1
                    nd["streak"] = 0
                    nd["status"] = "missed"
                    _apply_miss_feedback(c, nd, world)
                nd["window_start_tick"] = tick
                nd["window_end_tick"] = tick + 7 * 86400
                nd["satisfied_this_period"] = False
                nd["status"] = "pending"
            continue

        if nd["current_period_key"] != period:
            was_first_period = nd["current_period_key"] is None
            # Guarded by status != "missed" -- a real schedule-derived
            # window (see below) may have already caught this miss
            # earlier in the SAME period, immediately when the window
            # closed rather than waiting for rollover; don't double-count
            # it here too.
            if not was_first_period and not nd["satisfied_this_period"] and nd["status"] != "missed":
                nd["missed_count"] += 1
                nd["streak"] = 0
                nd["status"] = "missed"
                _apply_miss_feedback(c, nd, world)

            nd["current_period_key"] = period
            nd["satisfied_this_period"] = False
            nd["window_start_tick"], nd["window_end_tick"] = _compute_window(
                c, world, nd["template_id"], calendar, cadence=nd["cadence"],
            )
            # A brand-new window is open, so this period is pending -- whatever was
            # missed last period lives on in missed_count/frustration. It used to
            # stay "missed" (red) until satisfied, so a weekly expectation with six
            # days still to go read as failed the moment its window opened.
            nd["status"] = "pending"
            nd["not_applicable"] = False

            # Confirmed live bug (player report: "go_to_work" flagged
            # missed in the middle of the night with no work scheduled
            # that day at all): the miss check above only ever looked at
            # whether the PERIOD rolled over, never at whether the
            # character actually had a real work block scheduled during
            # it. Pre-satisfying the instant a work-free day's period
            # starts means the NEXT rollover has nothing to miss -- this
            # doesn't touch how a real missed work day (one that DID have
            # a scheduled block) gets detected, which still runs through
            # the normal path above.
            if nd["template_id"] == "go_to_work" and not _has_scheduled_work_today(c, world):
                nd["satisfied_this_period"] = True
                nd["status"] = "satisfied"
                # Nothing was expected today -- not the same as having done it.
                nd["not_applicable"] = True

        # Real, immediate window-close miss detection -- for an
        # expectation with a real schedule-derived window this period
        # (Confirmed Decision #5), a miss is caught the moment the window
        # actually ends (e.g. right after dinner's own block passes),
        # not deferred until the whole period eventually rolls over.
        # Expectations with no real window (window_end_tick stays None)
        # are untouched -- they keep exactly today's rollover-only
        # behavior via the block above.
        window_end = nd.get("window_end_tick")
        if (window_end is not None and tick >= window_end
                and not nd["satisfied_this_period"] and nd["status"] not in ("missed", "satisfied")):
            nd["missed_count"] += 1
            nd["streak"] = 0
            nd["status"] = "missed"
            _apply_miss_feedback(c, nd, world)

    # Surface every still-outstanding expectation as a real intention --
    # brain/intentions.py::add_intention() already replaces same-type
    # entries and brain/context_builder.py::build_intentions() already
    # narrates the top ones (with their "reason") to the LLM, so this is
    # the only new call needed; a unique per-instance type
    # ("expectation:<template_id>") is required so two different
    # expectations never clobber each other (add_intention replaces by
    # type). Not injected for "satisfied" ones -- nothing left to act on
    # until the next period.
    from brain.intentions import remove_intention
    for nd in c.get("expectations", {}).values():
        if nd["status"] != "satisfied":
            _refresh_intention(c, nd, world)
        else:
            # Satisfied (or not applicable today): the intention would otherwise
            # linger with its old "you didn't get to ..." reason.
            remove_intention(c, f"expectation:{nd['template_id']}")


def _refresh_intention(c, nd, world):
    from brain.intentions import add_intention

    defs = world.get("definitions", {})
    template = defs.get("expectation_templates", {}).get(nd["template_id"], {})
    label = template.get("label", nd["template_id"])
    base_priority = template.get("base_priority", 40)

    if nd["status"] == "missed":
        reason = f"You didn't get to \"{label}\" and it's still bothering you."
        cause = nd.get("last_miss_reason")
        if cause:
            reason += f" ({cause.capitalize()}.)"
    else:
        reason = f"You still need to {label[0].lower()}{label[1:]}."

    # Ramps with overdue-ness, same spirit as calendar_events.py's
    # threshold-priority table -- the longer something goes unmet, the
    # harder it presses on the character's attention.
    priority = min(100, base_priority
                   + nd.get("missed_count", 0) * 10
                   + int(nd.get("frustration", 0) * 30))

    add_intention(c, {
        "type":            f"expectation:{nd['template_id']}",
        "source":          "expectation",
        "category":        nd.get("category", "schedule"),
        "priority":        priority,
        "reason":          reason,
        # Real time-remaining urgency (brain/intentions.py::
        # final_priority()) reads window_end_tick directly when set --
        # window_start_tick is carried alongside purely for display (the
        # Inspector's intention-detail modal), every expectation now gets
        # both (see _compute_window/_fallback_window above).
        "window_start_tick": nd.get("window_start_tick"),
        "window_end_tick":   nd.get("window_end_tick"),
        # Real stats -- how well this expectation has been kept up with,
        # and what it's cost when missed (streak/missed_count/
        # frustration/status all live on c["expectations"][template_id]
        # itself, not the intention -- surfaced here too so the
        # Inspector's detail view can show them without a second lookup).
        "streak":           nd.get("streak", 0),
        "missed_count":     nd.get("missed_count", 0),
        "frustration":      round(nd.get("frustration", 0.0), 2),
        "expectation_status": nd.get("status"),
    })


def _diagnose_miss_reason(c, world, nd=None):
    """A real, specific cause for why an expectation was just missed,
    read off the character's actual state at the moment the miss is
    detected -- the generic "it's still bothering you" reason string gave
    no indication of WHY, which a live report flagged as confusing (the
    period-rollover check that calls this runs on the same cadence the
    expectation's own period recurs on, so "at the moment" here really
    does mean close to when the miss actually happened, not some
    arbitrarily later check).

    go_to_work specifically gets an even more precise snapshot -- real
    player report: this generic fallback was showing up for MOST go_to_
    work misses, since the period-rollover check (once per real day)
    often runs long after whatever actually blocked them at their real
    scheduled shift start already ended. brain/agent_loop.py stamps
    c["_last_work_miss_reason"] at the EXACT tick their shift was due to
    start, which is a far more accurate "why" than whatever they happen
    to be doing at the once-a-day rollover check."""
    if nd and nd.get("template_id") == "go_to_work":
        snapshot = c.get("_last_work_miss_reason")
        if snapshot:
            return snapshot
    if c.get("off_grid"):
        where = (c.get("off_grid_reason") or "away somewhere").replace("_", " ")
        return f"you were {where}"
    act = c.get("activity") or {}
    if act.get("type") == "sleep":
        return "you were asleep"
    if act.get("type"):
        return f"you were busy {act['type'].replace('_', ' ')}"
    claustro = c.get("claustrophobia") or {}
    if claustro.get("panic", 0) > 20:
        return "you were stuck somewhere and starting to panic"
    if c.get("stress", 0) >= 90:
        return "you were too overwhelmed to get to it"
    return "you just got caught up with other things"


def _apply_miss_feedback(c, nd, world):
    c["stress"] = min(100.0, c.get("stress", 0.0) + MISS_STRESS_DELTA)
    nd["frustration"] = min(1.0, nd.get("frustration", 0.0) + FRUSTRATION_DELTA)
    nd["last_miss_reason"] = _diagnose_miss_reason(c, world, nd)
    _attribute_blame(c, nd, world)


def _attribute_blame(c, nd, world):
    """When a requires_others expectation missed because specific
    people didn't show (systems/expectation_planner.py stamps
    last_missed_blame at the moment that's detected), turn that into a
    real grievance against each of them -- systems/grievances.py already
    implements the rest (decaying per-target weight, auto-firing
    confrontation_desired past CONFRONT_THRESHOLD, which conflict_pipeline
    ::start_conflict() already consumes) with no further changes needed.
    This is deliberately the ONLY new call site -- see the plan."""
    blame = nd.get("last_missed_blame") or []
    if not blame:
        return

    defs = world.get("definitions", {})
    template = defs.get("expectation_templates", {}).get(nd["template_id"], {})
    # A synthesized, non-registry expectation (see systems/jobs.py's
    # contract-responsibility synthesis) has no registry template to
    # look up -- falls back to a grievance_event_type stamped directly
    # on the expectation entry itself at creation time. Every existing
    # registry-driven expectation is unaffected (the template lookup
    # still wins whenever a real template exists and sets the field).
    event_type = template.get("grievance_event_type") or nd.get("grievance_event_type")
    if not event_type:
        return

    from systems.grievances import add_grievance
    characters = world.get("characters", {})
    for blamed_id in blame:
        if blamed_id not in characters:
            continue
        add_grievance(c, blamed_id, event_type, world,
                      details={"expectation_id": nd["template_id"]})

    nd["last_missed_blame"] = []


def satisfy_expectation(c, expectation_id, world):
    """Completion hook -- mirrors lt_needs.py::satisfy_lt_need()'s exact
    shape/magnitudes. Returns False if the character has no such
    expectation (e.g. stale id from an interrupted plan)."""
    nd = c.get("expectations", {}).get(expectation_id)
    if not nd:
        return False

    nd["satisfied_this_period"] = True
    nd["status"] = "satisfied"
    nd["last_satisfied_tick"] = world.get("tick", 0)
    nd["streak"] = nd.get("streak", 0) + 1
    nd["frustration"] = max(0.0, nd.get("frustration", 0.0) - FRUSTRATION_DELTA)
    c["stress"] = max(0.0, c.get("stress", 0.0) - SATISFY_STRESS_DELTA)
    return True
