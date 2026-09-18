"""
systems/retirement.py

Per the user's explicit ask (live case: Brian Garcia, 65/elderly, with
dementia and an anxiety disorder, still full-time employed at a
physically demanding "High hazard" retail job) -- there was no
retirement concept anywhere in this codebase before this. Two paths in:

  - Age-based: past RETIREMENT_AGE, still employed -> retires with a
    real weekly pension, calculated from actual work history (years of
    experience x average salary across every job they've held -- see
    systems/jobs.py::_record_job_end(), which now records a salary per
    entry), not a flat guess.
  - Disability-based ("retired sick"): total_handicap() (systems/
    handicap.py) crosses a real threshold while still employed -- the
    character can no longer work at all, regardless of age, and draws a
    flat default disability check instead of an earned pension (there's
    no "years of service" story to base one on here).

Either path removes the job (recording it into work_history first, so
the pension math and the character's real employment record both stay
accurate) and drops the now-inapplicable go_to_work expectation outright
rather than leaving it to accumulate misses forever.
"""

RETIREMENT_AGE               = 65   # real-world convention
DISABILITY_HANDICAP_THRESHOLD = 70  # total_handicap() (0-100) at/above this = can't keep working
DEFAULT_DISABILITY_CHECK     = 300.0  # flat weekly -- no earned-pension math applies here

PENSION_REPLACEMENT_RATE = 0.5   # documented approximation, not actuarial
FULL_CAREER_YEARS         = 40   # years of experience for 100% of the replacement rate


def _years_of_experience(c):
    return sum(h.get("years", 0) for h in c.get("work_history", []))


def _average_salary(c):
    salaries = [h["average_salary"] for h in c.get("work_history", []) if h.get("average_salary")]
    if not salaries:
        return 0.0
    return sum(salaries) / len(salaries)


def _compute_pension(c):
    years = _years_of_experience(c)
    avg_salary = _average_salary(c)
    if avg_salary <= 0 or years <= 0:
        return DEFAULT_DISABILITY_CHECK   # no real work history to base a pension on -- fall back
    annual_pension = min(1.0, years / FULL_CAREER_YEARS) * avg_salary * PENSION_REPLACEMENT_RATE
    return round(annual_pension / 52, 2)


def _do_retire(c, world, reason):
    from systems.jobs import _record_job_end
    _record_job_end(c, world, reason=f"retired_{reason}")

    c["retired"] = True
    c["retirement_reason"] = reason   # "age" | "disability"
    c["employed"] = False
    # Confirmed live crash: schema_defaults.py::ensure_character_defaults()
    # unconditionally assumes c["job"] is always a real dict -- {} is
    # this codebase's real established "no job" convention, NOT None.
    c["job"] = {}
    c.pop("job_template_id", None)
    # occupation/profession/hourly_wage staleness on job separation is
    # fixed once, at the shared root -- see jobs.py::_record_job_end(),
    # already called just above.

    # go_to_work no longer applies once retired -- there's no job left
    # to go to, so the expectation is removed outright rather than left
    # to keep accumulating "missed" penalties forever.
    (c.get("expectations") or {}).pop("go_to_work", None)

    c["weekly_pension"] = _compute_pension(c) if reason == "age" else DEFAULT_DISABILITY_CHECK


def maybe_retire(c, world):
    """Age-based retirement. Self-gated (checks c["retired"] itself) --
    safe to call every tick for every employed character, cheap no-op
    once retired."""
    if c.get("retired"):
        return
    if not c.get("employed") or c.get("age", 0) < RETIREMENT_AGE:
        return
    _do_retire(c, world, "age")


def maybe_retire_disabled(c, world):
    """Disability-based retirement -- independent of age."""
    if c.get("retired"):
        return
    if not c.get("employed"):
        return
    from systems.handicap import total_handicap
    if total_handicap(c) < DISABILITY_HANDICAP_THRESHOLD:
        return
    _do_retire(c, world, "disability")


def pay_weekly_pension(c, world):
    """Called from the same Monday-midnight weekly cycle as economy.py's
    apply_expenses() -- a retired character draws their own real pension
    (or flat disability check) into their bank account instead of a wage."""
    if not c.get("retired"):
        return

    from systems.personal_items import get_item
    from systems.banking import BANK_NAME_TO_KEY, deposit

    wallet = get_item(c, "wallet")
    if not wallet:
        return
    card = next((i for i in wallet.get("items", []) if i.get("object_type") == "bank_card"), None)
    if not card:
        return
    bank_key = BANK_NAME_TO_KEY.get(card.get("bank"))
    if not bank_key:
        return
    amount = c.get("weekly_pension", DEFAULT_DISABILITY_CHECK)
    deposit(world, bank_key, card.get("account_number"), amount)
