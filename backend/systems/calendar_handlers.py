"""
systems/calendar_handlers.py

The work that used to sit inside sim_loop.tick() behind calendar-boundary checks and
tick-modulo checks, now driven by the clock and the scheduler instead
(docs/distributed_architecture_plan.md, step 2):

  time.week   weekly schedule regeneration, bills, pensions, premiums, ...
  time.hour   household activity log -> narrated hourly summary
  time.day    household hourly summaries -> daily summary
  time.month  adult/elderly belief adoption, taxes, debt, card cycle, government budget
  scheduled   popularity decay (every 60 ticks), post engagement (every 3600),
              the orphaned-carried-prop sweep (every 30), and the background-job
              service pass (every 5: loop-guard reflections, behaviour theories,
              household narrations)

None of these run unless their boundary/timer fires; tick() no longer checks for them.
Handlers get the world (they run in the tick thread at the end of the tick's flush, or
from the scheduler) and rebuild the character list themselves.
"""

from core.event_bus import subscribe
from core import scheduler


def _characters(world):
    return [c for c in world.get("characters", {}).values() if not c.get("is_workplace_npc")]


# ── weekly ────────────────────────────────────────────────────────────────────

def on_week(data, world):
    import sim_loop as S
    characters = _characters(world)
    for c in characters:
        c["schedule"] = S.generate_week_schedule(c, world)
        S.adjust_for_household(c, world)
        S.reset_weekly_counts(c)
        S.distribute_lt_needs(c, world=world)  # no-op if already distributed
    S.tick_exercise(world)
    S.tick_pregnancy(world)   # weekly fitness decay + streak tracking
    S.tick_baby_weekly(world)
    S.tick_conditioning_weekly(world)
    S.apply_expenses(world)   # issues this week's household bills (rent/food/hobbies/credit cards/loans)
    from systems.retirement import pay_weekly_pension
    from systems.insurance import pay_weekly_premium
    for c in characters:
        pay_weekly_pension(c, world)    # retired characters draw their own real pension/disability check
        pay_weekly_premium(c, world)    # insured characters pay this week's premium (or lapse if they can't)
    S.recall_overdue_loans(world)   # returns any borrowed item past its due date to its real owner
    S.schedule_upcoming_legislation(world)   # keeps a real upcoming bill queued at all times
    try:
        from core.definitions import load_definitions
        defs = load_definitions(world.get("sim_id", "default"))
        S.evaluate_weekly_designations(world, defs)
        # Trait/belief adoption is evaluated weekly for children/teens (more malleable --
        # mirrors peer_influence.py's CHILD_TRAIT_ACQUISITION_AGE_GROUPS), monthly for
        # everyone else (on_month below).
        learners = [c for c in characters if c.get("age_group") in ("child", "teen")]
        if learners:
            S.resolve_cognitive_adoption(world, defs, learners)
    except Exception:
        pass

    from systems.household_summary import update_household_weekly_summaries
    update_household_weekly_summaries(world)


# ── hourly / daily ────────────────────────────────────────────────────────────

def on_hour(data, world):
    from systems.household_summary import update_household_hourly_summaries
    update_household_hourly_summaries(world)


def on_day(data, world):
    from systems.household_summary import update_household_daily_summaries
    update_household_daily_summaries(world)


# ── monthly ───────────────────────────────────────────────────────────────────

def on_month(data, world):
    import sim_loop as S
    characters = _characters(world)
    try:
        from core.definitions import load_definitions
        defs = load_definitions(world.get("sim_id", "default"))
        learners = [c for c in characters if c.get("age_group") in ("adult", "elderly")]
        if learners:
            S.resolve_cognitive_adoption(world, defs, learners)
    except Exception:
        pass

    # income_tax_rate (socioeconomics.py) was computed but never actually charged to anyone
    # before this -- see systems/government_debt.py.
    for c in characters:
        S.assess_monthly_tax(c, world)
        S.apply_debt_consequences(c, world)
        S.tick_monthly_card_cycle(c)

    # Spend whatever tax was just collected across budget categories, nudging the matching
    # real environment stats -- see systems/government_budget.py.
    S.tick_government_budget(world)

    from systems.politics import tick_environment_opinion_drift
    tick_environment_opinion_drift(world)


subscribe("time.week", on_week)
subscribe("time.hour", on_hour)
subscribe("time.day", on_day)
subscribe("time.month", on_month)


# ── scheduled jobs ────────────────────────────────────────────────────────────

def _popularity_decay(world, entry):
    import sim_loop as S
    S.tick_popularity_decay(world)


def _post_engagement(world, entry):
    import sim_loop as S
    S.tick_post_engagement(world)


def _orphan_props(world, entry):
    from systems.occupancy import release_orphan_carried_props
    release_orphan_carried_props(world)


def _background_services(world, entry):
    """Collect/submit the background-LLM jobs that finish on their own schedule."""
    from systems.loop_guard import service_all as loop_guard_service
    loop_guard_service(world)
    from systems.behavior_patterns import service_theories
    service_theories(world)
    from systems.household_summary import service_narrations
    service_narrations(world)


scheduler.register_recurring("popularity_decay", _popularity_decay, every=60)
scheduler.register_recurring("post_engagement", _post_engagement, every=3600)
scheduler.register_recurring("orphan_props", _orphan_props, every=30, offset=5)
scheduler.register_recurring("background_services", _background_services, every=5, offset=2)
