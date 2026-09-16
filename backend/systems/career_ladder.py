"""
systems/career_ladder.py

A real per-company career ladder: 2-3 alternative promotion titles per
company (reusing job_complexity.py's own Senior/Lead/Lead Senior naming
convention, deterministic, no LLM call needed for content this simple),
each reachable via one of 3 ambition levels trading hours-required for
wage-increase. See jobs.py::_hire() and offgrid.py's work-shift
completion branch for where this gets consumed.
"""

import random

from systems.job_complexity import _normalize_title

_AMBITION_LEVELS = ("low", "medium", "high")
# (hours multiplier, wage-increase multiplier) -- both scale together off
# a per-title base, so higher ambition costs more hours for a bigger jump.
_LEVEL_MULTIPLIERS = {
    "low":    (1.0, 1.0),
    "medium": (1.8, 1.8),
    "high":   (3.0, 3.0),
}
_BASE_HOURS_REQUIRED = 480.0
_BASE_WAGE_INCREASE_PCT = 8.0
_WAGE_VARIANCE_PCT = 3.0

_TITLE_PREFIXES = ("Senior ", "Lead ", "Lead Senior ")


def _generate_ladder_titles(current_title):
    base = _normalize_title(current_title) or "employee"
    base = base.title()
    return [f"{prefix}{base}" for prefix in _TITLE_PREFIXES]


def _get_or_create_career_ladder(world, company_key, current_title):
    """Lazily generated the first time any character at this company
    needs one -- world["companies"][company_key]["career_ladder"] =
    {title: {"low"|"medium"|"high": {hours_required, wage_increase_pct,
    wage_variance_pct}}}."""
    company = world.setdefault("companies", {}).setdefault(company_key, {})
    ladder = company.setdefault("career_ladder", {})
    for title in _generate_ladder_titles(current_title):
        if title in ladder:
            continue
        levels = {}
        for level in _AMBITION_LEVELS:
            hours_mult, wage_mult = _LEVEL_MULTIPLIERS[level]
            levels[level] = {
                "hours_required": round(_BASE_HOURS_REQUIRED * hours_mult),
                "wage_increase_pct": round(_BASE_WAGE_INCREASE_PCT * wage_mult, 1),
                "wage_variance_pct": _WAGE_VARIANCE_PCT,
            }
        ladder[title] = levels
    return ladder


_HIGH_AMBITION_TRAITS = {"ambitious", "driven", "competitive"}
_LOW_AMBITION_TRAITS = {"lazy", "content", "unambitious"}


def choose_career_path(c, world):
    """One real, LLM-driven pick per sim+job -- see choice.py::choose().
    Stores the result in c["career_progress"] with hours_worked starting
    at 0. No-op for an unemployed character or one with no real company."""
    if not c.get("employed"):
        return
    contract = c.get("employment_contract") or {}
    company_key = contract.get("company_id") or c.get("company_id")
    if not company_key:
        return

    current_title = (c.get("job") or {}).get("title") or c.get("profession") or "worker"
    ladder = _get_or_create_career_ladder(world, company_key, current_title)

    options = []
    for title, levels in ladder.items():
        for level, data in levels.items():
            options.append({
                "id": f"{title}:{level}",
                "label": f"Aim to become {title} ({level} ambition)",
                "tags": [level],
            })
    if not options:
        return

    traits = set(c.get("traits", []) or []) | set(c.get("personality_traits", []) or [])
    occasion = None
    if traits & _HIGH_AMBITION_TRAITS:
        occasion = "high"
    elif traits & _LOW_AMBITION_TRAITS:
        occasion = "low"

    from systems.choice import choose
    picked = choose(c, world, "career path", options, occasion=occasion)
    if not picked:
        return
    title, level = picked["id"].rsplit(":", 1)
    c["career_progress"] = {
        "company_id": company_key,
        "title": title,
        "ambition": level,
        "hours_worked": 0.0,
        "selected_tick": world.get("tick", 0),
    }


def advance_career_progress(c, world, shift_hours):
    """Called from offgrid.py's work-shift completion with the REAL
    shift length in hours -- accumulates toward the chosen promotion,
    firing it once hours_worked reaches hours_required."""
    progress = c.get("career_progress")
    if not progress:
        return
    progress["hours_worked"] = progress.get("hours_worked", 0.0) + max(0.0, shift_hours)

    company = world.get("companies", {}).get(progress.get("company_id"), {})
    ladder = company.get("career_ladder", {})
    level_data = (ladder.get(progress.get("title")) or {}).get(progress.get("ambition"))
    if not level_data:
        return
    if progress["hours_worked"] >= level_data["hours_required"]:
        _apply_promotion(c, world, progress["title"], level_data)


def _apply_promotion(c, world, title, level_data):
    """Wage bump = wage_increase_pct +/- a one-time-rolled variance,
    computed on the day of promotion. Clears career_progress so the next
    choose_career_path() call picks a fresh target."""
    old_wage = c.get("hourly_wage", 0.0) or 0.0
    variance_pct = level_data.get("wage_variance_pct", 0.0)
    variance = random.uniform(-variance_pct, variance_pct)
    pct_increase = level_data.get("wage_increase_pct", 0.0) + variance
    new_wage = round(old_wage * (1 + pct_increase / 100.0), 2)

    c["hourly_wage"] = new_wage
    job = c.get("job")
    if job:
        job["title"] = title
        job["hourly_wage"] = new_wage

    contract = c.get("employment_contract")
    if contract:
        contract["hourly_wage"] = new_wage
        contract["salary"] = round(new_wage * contract.get("hours_per_week", 40) * 52, 2)

    c["career_progress"] = {}

    from brain.memory import store_memory
    store_memory(c, f"Got promoted to {title}!", 0.8, ["job", "promotion"], "job", world.get("tick", 0))
