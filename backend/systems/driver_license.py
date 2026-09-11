"""
systems/driver_license.py

Drives a character's driver's-license pursuit forward, exactly the way
jobs.py owns c["job_application"]'s multi-stage pipeline -- a real
lesson/test cycle with waits and off-grid trips between stages, not a
single-shot expectation.

c["driver_license_pursuit"] = {
    "lessons_taken", "lessons_target", "practice_sessions",
    "test_attempts", "next_action_tick", "pending_action"
        ("lesson" | "test" | "practice" | None),
    "awaiting_travel_return",
}
Cleared to None once the real driver_license item is granted -- the item
becomes the sole source of truth after that, same philosophy as
c["job"] after hire.

Test pass-rate note: first-attempt US road-test failure rates are
commonly cited in the 40-50% range across states -- no single
authoritative national figure exists. BASE_TEST_PASS below is a
documented approximation, not precise data (same convention this
project already uses for e.g. mental_health_gen.py's base_rate fields).
"""

import random

from systems.personal_items import has_valid_license

TICKS_PER_DAY = 86400


def _days_to_ticks(lo_days, hi_days):
    return random.randint(int(lo_days * TICKS_PER_DAY), int(hi_days * TICKS_PER_DAY))


LESSON_COOLDOWN_DAYS = (2, 6)
TEST_RETRY_COOLDOWN_DAYS = (14, 30)  # approximate DMV retest waiting period

BASE_TEST_PASS = 0.52
_PRACTICE_ROLL_CHANCE = 0.02  # per driver_license-cadence poll, per unlicensed pursuer


def _start_pursuit(c, world):
    lessons_target = max(3, round(random.gauss(5.0, 1.3)))
    state = {
        "lessons_taken":          0,
        "lessons_target":         lessons_target,
        "practice_sessions":      0,
        "test_attempts":          0,
        "next_action_tick":       world.get("tick", 0),
        "pending_action":         None,
        "awaiting_travel_return": False,
    }
    c["driver_license_pursuit"] = state
    return state


def _dmv_cost_range(world):
    defs = world.get("definitions", {})
    tmpl = defs.get("company_templates", {}).get("dmv", {})
    lo, hi = tmpl.get("cost_range", [15, 40])
    return lo, hi


def _driving_school_cost_range(world):
    defs = world.get("definitions", {})
    tmpl = defs.get("company_templates", {}).get("driving_school", {})
    lo, hi = tmpl.get("cost_range", [40, 80])
    return lo, hi


def _pay_from_household(c, world, cost):
    h = world.get("households", {}).get(c.get("household_id"))
    if h:
        h["wealth"] = max(0, h.get("wealth", 0) - cost)


def _dispatch_lesson(c, world, state):
    from systems.offgrid import send_offgrid
    if send_offgrid(c, world, "driving_lesson", random.randint(45, 75)):
        state["pending_action"] = "lesson"
        state["awaiting_travel_return"] = True
    else:
        state["next_action_tick"] = world["tick"] + random.randint(3600, 7200)


def _on_lesson_return(c, world, state):
    state["lessons_taken"] += 1
    state["awaiting_travel_return"] = False
    state["pending_action"] = None
    state["next_action_tick"] = world["tick"] + _days_to_ticks(*LESSON_COOLDOWN_DAYS)
    lo, hi = _driving_school_cost_range(world)
    _pay_from_household(c, world, random.uniform(lo, hi))


def _test_pass_chance(state):
    # More preparation measurably improves the odds -- not flavor.
    lessons_bonus  = min(0.30, max(0, state["lessons_taken"] - 3) * 0.05)
    practice_bonus = min(0.15, state["practice_sessions"] * 0.05)
    return min(0.95, BASE_TEST_PASS + lessons_bonus + practice_bonus)


def _dispatch_test(c, world, state):
    from systems.offgrid import send_offgrid
    if send_offgrid(c, world, "driving_test", 45):
        state["pending_action"] = "test"
        state["awaiting_travel_return"] = True
    else:
        state["next_action_tick"] = world["tick"] + random.randint(3600, 7200)


def _grant_license(c, world):
    from systems.personal_items import make_driver_license, get_item, add_item
    from systems.containers import add_to_container

    calendar_year = world.get("calendar", {}).get("year")
    birth_year = (calendar_year - c.get("age", 0)) if calendar_year is not None else None
    license_item = make_driver_license(c["id"], c.get("name", ""), owner_id=c["id"], birth_year=birth_year)

    wallet = get_item(c, "wallet")
    if not wallet or add_to_container(wallet, license_item).get("success") is not True:
        add_item(c, license_item)

    c["driver_license_pursuit"] = None
    from systems.expectations import satisfy_expectation
    satisfy_expectation(c, "acquire_driver_license", world)


def _on_test_return(c, world, state):
    state["awaiting_travel_return"] = False
    state["pending_action"] = None
    state["test_attempts"] += 1
    lo, hi = _dmv_cost_range(world)
    _pay_from_household(c, world, random.uniform(lo, hi))

    if random.random() < _test_pass_chance(state):
        _grant_license(c, world)
    else:
        state["next_action_tick"] = world["tick"] + _days_to_ticks(*TEST_RETRY_COOLDOWN_DAYS)


def on_driver_license_return(c, world, reason):
    """Single entry point offgrid.py::process_return() calls back into --
    branches on which of the three driver_license reasons resolved."""
    state = c.get("driver_license_pursuit")
    if not state or not state.get("awaiting_travel_return"):
        return  # e.g. the companion side of a practice_driving return
    if reason == "driving_lesson":
        _on_lesson_return(c, world, state)
    elif reason == "driving_test":
        _on_test_return(c, world, state)
    elif reason == "practice_driving":
        state["awaiting_travel_return"] = False
        state["pending_action"] = None
        state["practice_sessions"] += 1


def advance_driver_license(c, world):
    """Polled on its own cadence from sim_loop.py -- the function that
    actually ticks the lesson/test pipeline forward, mirroring jobs.py::
    advance_job_application()'s role for the interview pipeline."""
    exp = c.get("expectations", {}).get("acquire_driver_license")
    if not exp or exp["status"] == "satisfied":
        return

    if has_valid_license(c):
        # Licensed via some other path (generation-time backfill, debug
        # tooling, ...) -- nothing left to pursue.
        from systems.expectations import satisfy_expectation
        satisfy_expectation(c, "acquire_driver_license", world)
        return

    state = c.get("driver_license_pursuit")
    if state is None:
        state = _start_pursuit(c, world)
    if state.get("awaiting_travel_return"):
        return  # resolved by on_driver_license_return() instead
    if world["tick"] < state.get("next_action_tick", 0):
        return

    if state["lessons_taken"] < state["lessons_target"]:
        _dispatch_lesson(c, world, state)
    else:
        _dispatch_test(c, world, state)


# =========================================================
# PRACTICE DRIVING WITH A COMPANION (off-grid, informal)
# =========================================================

def _eligible_companion(c, other, world):
    if other.get("id") == c.get("id"):
        return False
    if not has_valid_license(other):
        return False
    if other.get("off_grid") or other.get("travel_state") or other.get("alive") is False:
        return False
    if other.get("household_id") and other.get("household_id") == c.get("household_id"):
        return True
    rel = c.get("relationships", {}).get(other["id"])
    if not rel:
        return False
    if rel.get("friendship", 0) > 50:
        return True
    if rel.get("kinship") in ("parent", "spouse", "sibling"):
        return True
    return False


def _find_practice_companion(c, world):
    candidates = [
        oc for oc in world.get("characters", {}).values()
        if _eligible_companion(c, oc, world)
    ]
    return random.choice(candidates) if candidates else None


def _send_practice_session(c, companion, world):
    if c.get("off_grid") or c.get("travel_state") or companion.get("off_grid") or companion.get("travel_state"):
        return False
    from systems.offgrid import send_offgrid
    duration = random.randint(30, 60)
    if not send_offgrid(c, world, "practice_driving", duration):
        return False
    if not send_offgrid(companion, world, "practice_driving", duration):
        # Roll back the learner's own dispatch -- send_offgrid() already
        # mutated their off-grid state.
        c["off_grid"] = False
        c["off_grid_reason"] = None
        c["return_tick"] = None
        return False
    c["driver_license_pursuit"]["pending_action"] = "practice"
    c["driver_license_pursuit"]["awaiting_travel_return"] = True
    return True


def maybe_practice_with_companion(c, world):
    """Informal practice with a licensed friend/family member -- boosts
    the eventual test pass-chance only (see _test_pass_chance()), never
    reduces lessons_target: supplements formal instruction, doesn't
    replace it."""
    state = c.get("driver_license_pursuit")
    if not state or state.get("awaiting_travel_return"):
        return
    if has_valid_license(c) or random.random() > _PRACTICE_ROLL_CHANCE:
        return
    companion = _find_practice_companion(c, world)
    if not companion:
        return
    _send_practice_session(c, companion, world)
