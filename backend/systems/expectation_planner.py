"""
systems/expectation_planner.py

Preliminary plans for expectations -- reuses activity_queue.py's task
queue wholesale (same {id, type, params, depends_on, status} shape
hobby_planner.py already builds onto), rather than a second queue
engine. An expectation with a direct expectation_templates["activity_type"]
mapping (e.g. "make_dinner" -> "cook_recipe") queues one "hobby_session"
task pointing at it -- activity_queue.py's _dispatch_hobby() already
knows how to start ANY named systems/activities.py::ACTIVITIES entry
this way, not just real hobbies (see cooking_process.py's own use of the
identical path). On a hard blocker (no direct mapping, or the mapped
activity_type doesn't exist), falls back to persistent_desires.add_desire()
-- the same "possible solution to pursue later" fallback plan_hobby()
already uses, not a dead end.

Completion hook: activities.py::complete_activity() stashes the started
task's full params dict onto c["_active_hobby_params"] (already true for
every hobby_session-dispatched activity, no activity_queue.py change
needed) -- this module's on_expectation_activity_complete() reads
params.get("expectation_id") off that dict BEFORE it gets popped, and
calls expectations.py::satisfy_expectation() (or, for requires_others
expectations where the required people weren't actually present,
leaves it unsatisfied so the next period-rollover correctly counts it
as missed -- see systems/expectations.py -- and, once wired, grievances
::add_grievance() against whoever was missing, Phase 4).
"""


def plan_expectation(c, world, expectation_id):
    """Queue a single task to act on this expectation. Returns True if
    something was queued, False if there's no direct activity mapping
    (caller should fall back to add_desire -- see
    plan_or_desire_expectation below)."""
    nd = c.get("expectations", {}).get(expectation_id)
    if not nd:
        return False

    defs = world.get("definitions", {})
    template = defs.get("expectation_templates", {}).get(nd["template_id"], {})
    activity_type = template.get("activity_type")
    if not activity_type:
        return False

    from systems.activities import ACTIVITIES
    if activity_type not in ACTIVITIES:
        return False

    from systems.activity_queue import queue_task
    queue_task(c, "hobby_session", {"activity": activity_type, "expectation_id": expectation_id})
    return True


def plan_or_desire_expectation(c, world, expectation_id):
    """The real entry point -- queues a concrete plan when possible,
    otherwise registers a persistent desire (the "possible solution to
    pursue" for a genuinely blocked expectation, mirroring
    hobby_planner.py::plan_hobby()'s exact fallback)."""
    if plan_expectation(c, world, expectation_id):
        return True

    from systems.persistent_desires import add_desire
    add_desire(c, f"fulfill_{expectation_id}", target=expectation_id, importance=0.5)
    return False


def on_expectation_activity_complete(c, world, hobby_params):
    """Call from activities.py::complete_activity(), BEFORE
    c["_active_hobby_params"] is popped -- hobby_params is that dict (or
    None). Resolves the expectation this completing activity was for, if
    any, and satisfies it (respecting requires_others -- see
    _others_present)."""
    if not hobby_params:
        return

    expectation_id = hobby_params.get("expectation_id")
    if not expectation_id:
        return

    nd = c.get("expectations", {}).get(expectation_id)
    if not nd:
        return

    if nd.get("requires_others") and not _others_present(c, world):
        # Left unsatisfied on purpose -- the next period rollover in
        # systems/expectations.py::update_expectations() will correctly
        # count this as missed. Record WHO was supposed to be here and
        # wasn't, so that miss can attribute real blame (see
        # systems/expectations.py::_apply_miss_feedback ->
        # systems/grievances.py::add_grievance) instead of just being a
        # bare frustration bump with no cause.
        nd["last_missed_blame"] = _missing_household_members(c, world)
        return

    from systems.expectations import satisfy_expectation
    satisfy_expectation(c, expectation_id, world)


def _others_present(c, world):
    """True only if EVERY other living household member is co-present --
    "family dinner TOGETHER" means together, not just one other person
    showing up. Anyone missing is who gets blamed (see
    _missing_household_members below)."""
    return not _missing_household_members(c, world)


def _missing_household_members(c, world):
    """Every OTHER living household member currently NOT co-present --
    the responsible-party list for a requires_others miss. Empty list
    means everyone who should be here is here (i.e. _others_present())."""
    household_id = c.get("household_id")
    if not household_id:
        return []
    household = world.get("households", {}).get(household_id, {})
    characters = world.get("characters", {})

    from systems.action_router import _co_present_characters
    present_ids = {o["id"] for o in _co_present_characters(c, world)}

    return [
        mid for mid in household.get("members", [])
        if mid != c["id"]
        and mid in characters
        and characters[mid].get("alive") is not False
        and mid not in present_ids
    ]
