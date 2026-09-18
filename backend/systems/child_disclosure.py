"""
systems/child_disclosure.py

For an assault incident against a child that went unwitnessed (see
emergency.py::auto_report_incidents' real witness/self-report roll --
unreported_final=True), the offense doesn't just vanish. A real,
lingering trauma record is stamped on the child, feeding two things:
(1) a near-term traumatic-memory line for school-day narration, and
(2) a real daily roll, on any day the child actually has school on
their own generated schedule, that they tell a trusted adult -- the
actual, delayed moment this becomes a real, reported incident and a
real CPS welfare-check dispatch (reusing systems/child_welfare.py's own
dispatch machinery directly, not a new mechanism).

The offender's own resolve (systems/offense_rationalization.py) decides
whether he admits or insists the child is lying -- but per the user's
own framing, denial doesn't block removal: a child who visibly fears
the offender gets taken regardless.
"""

import random

from brain.memory import store_memory

_BASE_DISCLOSURE_CHANCE = 0.12
_TRAUMA_RECENCY_DAYS = 14  # after this many days, the near-term context line stops firing
_FEAR_REMOVAL_THRESHOLD = 20


def stamp_unreported_trauma(world, inc):
    """Called once, right when an assault incident against a child
    finally gets marked unreported_final -- see emergency.py."""
    victim_id = next((p for p in inc.get("participants", []) if p != inc.get("offender_id")), None)
    if not victim_id:
        return
    victim = world.get("characters", {}).get(victim_id)
    if not victim or victim.get("age_group") != "child":
        return

    victim["_unreported_trauma"] = {
        "incident_id": inc["id"],
        "offender_id": inc.get("offender_id"),
        "tick":        world.get("tick", 0),
        "severity":    0.9,
    }
    store_memory(
        victim, "Something bad happened and I haven't told anyone.", 0.85,
        ["trauma", "unreported", "assault"], "child_welfare", world.get("tick", 0),
    )


def get_school_trauma_context(c, world):
    """Near-term traumatic-memory line, threaded into school-day
    narration -- fires only while the trauma is still recent."""
    trauma = c.get("_unreported_trauma")
    if not trauma:
        return None
    from systems.law import TICKS_PER_DAY
    age_days = (world.get("tick", 0) - trauma.get("tick", 0)) / TICKS_PER_DAY
    if age_days > _TRAUMA_RECENCY_DAYS:
        return None
    return "Something happened recently that's been weighing on you -- you haven't told anyone."


def _has_school_today(c, world):
    schedule = c.get("schedule") or {}
    week = schedule.get("week") or {}
    cal = world.get("calendar", {})
    day_key = cal.get("day_of_week") or cal.get("weekday")
    blocks = week.get(day_key) or []
    return any(b.get("activity") == "school" for b in blocks)


def _confront_offender(offender, victim, world):
    """The offender is questioned -- his own pre-generated resolve score
    (offense_rationalization.py) decides admit vs. deny. Either way, a
    real incident now exists and feeds the normal arrest pipeline; a
    child who visibly fears the offender is removed regardless of
    whether he admitted anything."""
    rationalization = offender.get("_offense_rationalization") or {}
    resolve = rationalization.get("resolve", 0.5)
    admits = random.random() > resolve

    rel = victim.get("relationships", {}).get(offender["id"], {})
    fear_signal = rel.get("creeped_out", 0) + max(0, -rel.get("trust", 0)) + rel.get("fear", 0)
    child_fears_offender = fear_signal > _FEAR_REMOVAL_THRESHOLD

    store_memory(
        offender,
        "I admitted what I did when they asked." if admits else "I told them the kid was lying.",
        0.85, ["law", "confrontation"], "legal", world.get("tick", 0),
    )

    if admits or child_fears_offender:
        from systems.child_welfare import (
            _find_placement_relative, _place_with_relative, _send_child_to_cps_care,
        )
        from systems.child_care import _find_parents_for_child
        relative = _find_placement_relative(victim, world)
        if relative:
            _place_with_relative(victim, relative, world)
        else:
            parents = _find_parents_for_child(victim, world)
            _send_child_to_cps_care(victim, world, parents)

    # A real, reported incident now exists regardless of admission --
    # feeds the same arrest pipeline as any other reported crime.
    from systems.emergency import report_assault_incident
    inc = report_assault_incident(world, offender, victim)
    inc["reported"] = True
    inc["arrest_checked"] = False
    return inc


def maybe_disclose_at_school(c, world):
    """Called from the daily sweep below -- a small, real chance a child
    with unreported trauma tells a trusted adult on a day they actually
    have school."""
    trauma = c.get("_unreported_trauma")
    if not trauma:
        return False
    if not _has_school_today(c, world):
        return False
    if random.random() >= _BASE_DISCLOSURE_CHANCE:
        return False

    offender = world.get("characters", {}).get(trauma.get("offender_id"))
    store_memory(c, "Told a teacher what happened.", 0.9,
                 ["trauma", "disclosed", "assault"], "child_welfare", world.get("tick", 0))

    from systems.child_welfare import _dispatch_cps_worker
    _dispatch_cps_worker(c, world)

    if offender:
        _confront_offender(offender, c, world)

    del c["_unreported_trauma"]
    return True


def tick_child_disclosure(world):
    """Day-gated sweep (mirrors reminders.py's own shape) -- every child
    with a real unresolved unreported_trauma record gets one real
    disclosure roll per real day they have school."""
    stamp_key = "_last_child_disclosure_day"
    from systems.law import TICKS_PER_DAY
    today = world.get("tick", 0) // TICKS_PER_DAY
    if world.get(stamp_key) == today:
        return
    world[stamp_key] = today

    for c in list(world.get("characters", {}).values()):
        if c.get("age_group") == "child" and c.get("_unreported_trauma"):
            maybe_disclose_at_school(c, world)
