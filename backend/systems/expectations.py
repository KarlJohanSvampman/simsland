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


def _apply_miss_feedback(c, nd, world):
    c["stress"] = min(100.0, c.get("stress", 0.0) + MISS_STRESS_DELTA)
    nd["frustration"] = min(1.0, nd.get("frustration", 0.0) + FRUSTRATION_DELTA)
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
    event_type = template.get("grievance_event_type")
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
