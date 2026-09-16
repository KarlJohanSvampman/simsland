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

from datetime import date

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
            if len(members) > 1:
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

    for nd in c.get("expectations", {}).values():
        period = _current_period_key(nd["cadence"], calendar)
        if period is None:
            continue   # "once" -- no recurring boundary to roll over

        if nd["current_period_key"] == period:
            continue   # still the same period, nothing rolled over

        was_first_period = nd["current_period_key"] is None
        if not was_first_period and not nd["satisfied_this_period"]:
            nd["missed_count"] += 1
            nd["streak"] = 0
            nd["status"] = "missed"
            _apply_miss_feedback(c, nd, world)

        nd["current_period_key"] = period
        nd["satisfied_this_period"] = False
        if nd["status"] != "missed":
            nd["status"] = "pending"

        # Confirmed live bug (player report: "go_to_work" flagged missed
        # in the middle of the night with no work scheduled that day at
        # all): the miss check above only ever looked at whether the
        # PERIOD rolled over, never at whether the character actually had
        # a real work block scheduled during it. Pre-satisfying the
        # instant a work-free day's period starts means the NEXT
        # rollover has nothing to miss -- this doesn't touch how a real
        # missed work day (one that DID have a scheduled block) gets
        # detected, which still runs through the normal path above.
        if nd["template_id"] == "go_to_work" and not _has_scheduled_work_today(c, world):
            nd["satisfied_this_period"] = True
            nd["status"] = "satisfied"

    # Surface every still-outstanding expectation as a real intention --
    # brain/intentions.py::add_intention() already replaces same-type
    # entries and brain/context_builder.py::build_intentions() already
    # narrates the top ones (with their "reason") to the LLM, so this is
    # the only new call needed; a unique per-instance type
    # ("expectation:<template_id>") is required so two different
    # expectations never clobber each other (add_intention replaces by
    # type). Not injected for "satisfied" ones -- nothing left to act on
    # until the next period.
    for nd in c.get("expectations", {}).values():
        if nd["status"] != "satisfied":
            _refresh_intention(c, nd, world)


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
        "type":     f"expectation:{nd['template_id']}",
        "source":   "expectation",
        "category": nd.get("category", "schedule"),
        "priority": priority,
        "reason":   reason,
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
