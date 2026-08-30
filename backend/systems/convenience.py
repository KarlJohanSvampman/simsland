"""
systems/convenience.py

Tracks things a character has come to rely on -- a steady job, a stable
home, personal freedom/autonomy -- as an ONGOING goal distinct from
systems/expectations.py's recurring checkboxes: nobody "checks off"
convenience, it just accumulates the longer a stable state holds, and
LOSING it is a bigger stressor than never having had it (mirrors real
grief-over-disruption rather than a missed task).

c["conveniences"][category] = {
    "established":     bool,   # currently in a stable, relied-upon state
    "disrupted_count":  int,   # lifetime losses
    "frustration":     0.0-1.0,
}

disrupt_convenience() is the single entry point every disruption source
calls (see systems/eviction.py, core/event_handlers.py's character_fired
subscriber, systems/social_contracts.py's authority-contract factory).
When a specific person caused the disruption, it's routed into
systems/grievances.py -- same reuse pattern as
systems/expectations.py::_attribute_blame(). When there's no one to
blame (a market crash, an eviction from accumulated household debt), it
instead seeds a "rebuild this" desire via systems/persistent_desires.py,
which is what actually makes it feed back into intentions -- the
"possible solution to pursue" fallback used throughout this plan.
"""

CONVENIENCE_CATEGORIES = ("employment", "housing", "autonomy")

# 30 sim-days at TICK_RATE_SECONDS=1 (1 tick == 1 sim-second, confirmed
# by reading_process.py's 300-tick == 5-sim-minute constant).
ESTABLISH_TICKS = 30 * 86400

DISRUPT_STRESS_DELTA      = 10.0  # 2x expectations.py's MISS_STRESS_DELTA -- losing hurts more than missing
DISRUPT_FRUSTRATION_DELTA = 0.5


def _conv(c, category):
    return c.setdefault("conveniences", {}).setdefault(
        category, {"established": False, "disrupted_count": 0, "frustration": 0.0}
    )


def update_convenience(c, world):
    """Per-character, per-tick (cheap dict-lookups only) -- ramps
    employment/housing toward "established" once they've held stable long
    enough, and clears "established" if the underlying state is just
    gone (no disruption event fired, e.g. this character was never
    employed at all -- nothing to grieve, just not established yet)."""
    tick = world.get("tick", 0)

    emp = _conv(c, "employment")
    if c.get("employed"):
        if not emp["established"]:
            start = c.get("current_job_start_tick")
            if start is not None and tick - start >= ESTABLISH_TICKS:
                emp["established"] = True
    else:
        emp["established"] = False

    hou = _conv(c, "housing")
    household = world.get("households", {}).get(c.get("household_id"))
    if household and household.get("home_id"):
        if not hou["established"]:
            since = household.get("home_since_tick")
            if since is not None and tick - since >= ESTABLISH_TICKS:
                hou["established"] = True
    else:
        hou["established"] = False

    aut = _conv(c, "autonomy")
    if not aut["established"]:
        from systems.social_contracts import get_contracts_for_character
        still_restricted = any(
            con.get("contract_type", "chore") != "chore"
            for con in get_contracts_for_character(c["id"], world)
        )
        if not still_restricted:
            aut["established"] = True


def disrupt_convenience(c, category, world, cause=None, event_type=None):
    """Call when a character loses something in `category` they'd
    established. No-ops if it was never established (autonomy defaults
    established=True as a baseline, so it always fires there unless
    already mid-disruption). `cause`: a character id responsible, or
    None for a structural/no-one-to-blame loss. `event_type`: the
    systems/grievances.py SEVERITY key to use when cause is given."""
    conv = _conv(c, category)
    if not conv["established"]:
        return

    conv["established"] = False
    conv["disrupted_count"] = conv.get("disrupted_count", 0) + 1
    conv["frustration"] = min(1.0, conv.get("frustration", 0.0) + DISRUPT_FRUSTRATION_DELTA)
    c["stress"] = min(100.0, c.get("stress", 0.0) + DISRUPT_STRESS_DELTA)

    if cause and event_type and cause in world.get("characters", {}):
        from systems.grievances import add_grievance
        add_grievance(c, cause, event_type, world, details={"convenience": category})
    elif not cause:
        from systems.persistent_desires import add_desire
        add_desire(c, f"rebuild_{category}", target=category, importance=0.6)
