"""
systems/jobs.py

Company-sourced job market with daily turnover, expiry, and work-history tracking.

Architecture:
  - job_templates      (definitions.json) — full catalog of every possible role
  - company_templates  (definitions.json) — each has typical_roles + max_staff
  - world["job_listings"]                 — currently open postings (ephemeral)
  - world["company_slots"]                — {company_key: {job_id: {filled, capacity}}}
  - character["work_history"]             — list of past jobs
  - character["current_job_start_tick"]   — tick when hired into current role
"""

import random
import uuid

from brain.memory import store_memory
from core.event_bus import emit

# How many ticks represent one simulated year (for experience calculation)
TICKS_PER_YEAR = 365 * 24   # assumes ~24 ticks/day


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_defs(world):
    """Return (job_templates, company_templates) dicts from the world's definitions."""
    defs = world.get("definitions", {})
    return defs.get("job_templates", {}), defs.get("company_templates", {})


def _ticks_to_years(ticks):
    return round(ticks / TICKS_PER_YEAR, 1)


# ---------------------------------------------------------------------------
# Company slot initialisation
# ---------------------------------------------------------------------------

def init_company_slots(world):
    """
    Build world["company_slots"] from company_templates the first time.
    Called once during world generation.
    """
    _, company_tmpl = _get_defs(world)
    slots = world.setdefault("company_slots", {})

    for ckey, co in company_tmpl.items():
        if ckey in slots:
            continue
        company_slots = {}
        max_staff = co.get("max_staff", 5)
        typical   = co.get("typical_roles", [])
        if not typical:
            continue
        # Distribute capacity evenly across roles
        per_role = max(1, max_staff // max(1, len(typical)))
        for role in typical:
            company_slots[role] = {
                "capacity": per_role,
                "filled":   0,
            }
        slots[ckey] = company_slots

    return slots


# ---------------------------------------------------------------------------
# Listing generation
# ---------------------------------------------------------------------------

def _listing_id():
    return f"job_{uuid.uuid4().hex[:6]}"


def _make_listing(ckey, job_id, job_tmpl, world_env):
    """Create a single job listing dict."""
    base_wage = job_tmpl.get("hourly_wage", job_tmpl.get("average_salary", 30000) / 2080)
    wage      = base_wage * world_env.get("average_salary_index", 1.0) * random.uniform(0.9, 1.12)
    return {
        "id":              _listing_id(),
        "company_id":      ckey,
        "job_template_id": job_id,
        "title":           job_tmpl.get("name", job_id),
        "industry":        job_tmpl.get("industry", ""),
        "sector":          job_tmpl.get("sector", ""),
        "degree_required": job_tmpl.get("degree_required", "none"),
        "hourly_wage":     round(wage, 2),
        "average_salary":  job_tmpl.get("average_salary", 0),
        "work_mode":       job_tmpl.get("work_mode", "On-site"),
        "work_hours":      job_tmpl.get("work_hours", [9, 17]),
        "work_days":       job_tmpl.get("work_days", [1,2,3,4,5]),
        "illegal":         job_tmpl.get("illegal", False),
        "adult_industry":  job_tmpl.get("adult_industry", False),
        "criminal_tier":   job_tmpl.get("criminal_tier", 0),
        "open":            True,
        "applicants":      [],
        "posted_tick":     0,
        "expires_tick":    -1,   # -1 = no expiry; set by tick_job_market
    }


def generate_job_listings(world):
    """
    Called once at world creation to populate initial open positions.
    Fills ~60-80% of each company's slots and posts the unfilled remainder.
    """
    job_tmpl, company_tmpl = _get_defs(world)
    if not job_tmpl or not company_tmpl:
        return

    init_company_slots(world)
    slots   = world["company_slots"]
    env     = world.get("environment", {})
    listings = world.setdefault("job_listings", [])

    for ckey, co_slots in slots.items():
        co = company_tmpl.get(ckey, {})
        for job_id, slot in co_slots.items():
            jt = job_tmpl.get(job_id)
            if not jt:
                continue
            cap = slot["capacity"]
            # Pre-fill 60-80% as background hires
            prefill = int(cap * random.uniform(0.6, 0.8))
            slot["filled"] = prefill
            # Post openings for the rest
            open_count = cap - prefill
            for _ in range(open_count):
                listing = _make_listing(ckey, job_id, jt, env)
                listing["posted_tick"] = world.get("tick", 0)
                listing["expires_tick"] = world.get("tick", 0) + random.randint(200, 600)
                listings.append(listing)


# ---------------------------------------------------------------------------
# Daily market tick
# ---------------------------------------------------------------------------

def tick_job_market(world):
    """
    Called once per simulated day.
    - Expires stale listings
    - Applies turnover: opens new positions based on company turnover_rate
    - Scales opening rate by unemployment (high unemployment → fewer new posts)
    """
    job_tmpl, company_tmpl = _get_defs(world)
    if not job_tmpl or not company_tmpl:
        return

    init_company_slots(world)
    slots     = world["company_slots"]
    env       = world.get("environment", {})
    tick      = world.get("tick", 0)
    unemp     = env.get("unemployment_rate", 5.5) / 100  # convert % to fraction
    listings  = world.setdefault("job_listings", [])

    # 1. Expire old listings
    listings[:] = [l for l in listings if l.get("expires_tick", -1) < 0 or l["expires_tick"] > tick]

    # 2. Turnover: some filled slots open up
    for ckey, co_slots in slots.items():
        co = company_tmpl.get(ckey, {})
        turnover = co.get("turnover_rate", 0.02)
        for job_id, slot in co_slots.items():
            if slot["filled"] <= 0:
                continue
            # Scale by inverse unemployment — in hot market, more openings
            effective_rate = turnover * (1 - unemp * 0.5)
            if random.random() < effective_rate:
                slot["filled"] = max(0, slot["filled"] - 1)

    # 3. Post new listings for unfilled slots
    for ckey, co_slots in slots.items():
        co = company_tmpl.get(ckey, {})
        for job_id, slot in co_slots.items():
            if slot["filled"] >= slot["capacity"]:
                continue
            # Don't double-post if an active listing already exists for this role/company
            already_listed = any(
                l["company_id"] == ckey and l["job_template_id"] == job_id and l["open"]
                for l in listings
            )
            if already_listed:
                continue
            jt = job_tmpl.get(job_id)
            if not jt:
                continue
            listing = _make_listing(ckey, job_id, jt, env)
            listing["posted_tick"]  = tick
            listing["expires_tick"] = tick + random.randint(150, 450)
            listings.append(listing)

    # 4. Keep list bounded
    world["job_listings"] = listings[-500:]


# ---------------------------------------------------------------------------
# Character job actions
# ---------------------------------------------------------------------------

def generate_job_listings_legacy(world):
    """Backwards-compat wrapper — calls generate_job_listings."""
    if not world.get("job_listings"):
        generate_job_listings(world)


def maybe_fire(c, world):
    if not c.get("employed"):
        return
    env        = world.get("environment", {})
    unemp      = env.get("unemployment_rate", 5.5) / 100
    fire_chance = 0.001 + unemp * 0.002
    if random.random() < fire_chance:
        _record_job_end(c, world, reason="laid_off")
        c["employed"]      = False
        c["job_searching"] = True
        c["job_id"]        = None
        store_memory(c, "Got laid off from work.", 0.85, ["job", "layoff", "stress"], "job", world["tick"])
        emit("character_fired", {"character_id": c["id"]})


def apply_for_job(c, world, job_id=None):
    """job_id: when given (a character/LLM explicitly picked a specific
    listing -- see action_router.py::_route_computer_apply_for_job),
    applies to exactly that one if still open/eligible. When omitted
    (the automatic per-economy-tick path, brain/agent_loop.py::
    update_economy), picks among eligible listings via
    systems/choice.py rather than always taking the highest wage."""
    if c.get("employed") or c.get("interview"):
        return
    if not world.get("job_listings"):
        generate_job_listings(world)

    edu_rank = {
        "none": 0, "none_completed": 0, "preschool": 0, "primary": 0,
        "middle_school": 0, "high_school": 1, "trade_school": 2, "certificate": 2,
        "associate": 3, "bachelor": 4, "master": 5, "doctorate": 6, "professional": 6,
    }
    my_rank = edu_rank.get(c.get("education", "none"), 0)

    # Illegal listings (drug_dealer/mobster/etc -- see systems/crime.py)
    # are deliberately invisible to the normal public job-board flow, same
    # as the generation-time exclusion in character_gen.py::_assign_job.
    # Entry into crime is an opportunity-driven runtime path
    # (maybe_recruit_into_crime), not something a character just applies
    # to off a listing.
    eligible = [
        j for j in world["job_listings"]
        if j.get("open")
        and edu_rank.get(j.get("degree_required", "none"), 0) <= my_rank
        and (c.get("age_group") != "child")
        and not j.get("illegal")
    ]
    if not eligible:
        return

    if job_id:
        job = next((j for j in eligible if j["id"] == job_id), None)
        if not job:
            return
    else:
        options = [
            {"id": j["id"], "label": j.get("title", j["id"]),
             "tags": [t for t in (j.get("industry"), j.get("work_mode")) if t]}
            for j in eligible
        ]
        from systems.choice import choose
        picked = choose(c, world, "job to apply for", options)
        if not picked:
            return
        job = next(j for j in eligible if j["id"] == picked["id"])

    from systems.validation import queue_choice_for_validation
    queue_choice_for_validation(c, world, "workplace", job.get("title", job["id"]))

    job.setdefault("applicants", []).append(c["id"])
    c["interview"] = {
        "job_id":     job["id"],
        "company_id": job.get("company_id"),
        "tick":       world["tick"] + random.randint(10, 30),
    }
    store_memory(c, f"Applied for {job['title']} and got an interview.", 0.55,
                 ["job", "interview"], "job", world["tick"])
    emit("interview_scheduled", {"character_id": c["id"], "job_id": job["id"]})


def process_interview(c, world):
    iv = c.get("interview")
    if not iv or world["tick"] < iv["tick"]:
        return

    job = next((j for j in world.get("job_listings", []) if j["id"] == iv["job_id"]), None)
    if not job or not job.get("open"):
        c["interview"] = None
        return

    env     = world.get("environment", {})
    unemp   = env.get("unemployment_rate", 5.5) / 100
    success = random.random() < (
        0.45
        + c.get("ses", 0.5) * 0.25
        + env.get("education_quality", 0.7) * 0.15
        - unemp * 0.2
    )

    if success:
        # Fill the company slot
        ckey = job.get("company_id")
        if ckey and ckey in world.get("company_slots", {}):
            slot = world["company_slots"][ckey].get(job["job_template_id"])
            if slot:
                slot["filled"] = min(slot["capacity"], slot["filled"] + 1)

        # Update character
        c["employed"]               = True
        c["job_searching"]          = False
        c["job_id"]                 = job["id"]
        c["job_template_id"]        = job.get("job_template_id")
        c["company_id"]             = ckey
        c["profession"]             = job.get("job_template_id", job.get("profession"))
        c["hourly_wage"]            = job["hourly_wage"]
        c["current_job_start_tick"] = world["tick"]
        # industry_experience_ticks accumulates across jobs in same industry
        if not c.get("industry_experience"):
            c["industry_experience"] = {}
        job["open"] = False

        store_memory(c, f"Got hired as {job['title']}.", 0.8, ["job", "success"], "job", world["tick"])
        emit("character_hired", {
            "character_id": c["id"],
            "job_id":       job["id"],
            "title":        job["title"],
            "company_id":   ckey,
        })
    else:
        store_memory(c, f"Failed the interview for {job['title']}.", 0.7,
                     ["job", "rejection", "stress"], "job", world["tick"])
        emit("interview_failed", {"character_id": c["id"], "job_id": job["id"]})

    c["interview"] = None


# ---------------------------------------------------------------------------
# Work history helpers
# ---------------------------------------------------------------------------

def _record_job_end(c, world, reason="quit"):
    """Move current job into work_history with elapsed time."""
    start_tick = c.get("current_job_start_tick")
    if start_tick is None:
        return

    elapsed = world["tick"] - start_tick
    years   = _ticks_to_years(elapsed)

    entry = {
        "job_template_id": c.get("job_template_id") or c.get("profession"),
        "job_id":          c.get("job_id"),
        "company_id":      c.get("company_id"),
        "title":           c.get("job", {}).get("title") if isinstance(c.get("job"), dict) else c.get("profession"),
        "industry":        c.get("job", {}).get("industry") if isinstance(c.get("job"), dict) else None,
        "start_tick":      start_tick,
        "end_tick":        world["tick"],
        "years":           years,
        "reason_left":     reason,
    }
    c.setdefault("work_history", []).append(entry)

    # Accumulate industry experience
    industry = entry.get("industry") or ""
    if industry:
        c.setdefault("industry_experience", {})[industry] = (
            c.get("industry_experience", {}).get(industry, 0) + elapsed
        )

    # Clear current-job fields
    c["current_job_start_tick"] = None
    c["company_id"]             = None
    c["job_template_id"]        = None


def quit_job(c, world):
    """Called when a character voluntarily leaves a job."""
    if not c.get("employed"):
        return
    _record_job_end(c, world, reason="quit")
    # Free the company slot
    ckey = c.get("company_id")
    if ckey and ckey in world.get("company_slots", {}):
        slot = world["company_slots"][ckey].get(c.get("job_template_id"))
        if slot:
            slot["filled"] = max(0, slot["filled"] - 1)
    c["employed"]      = False
    c["job_searching"] = True
    c["job_id"]        = None
    store_memory(c, "Quit my job.", 0.6, ["job", "quit"], "job", world["tick"])
    emit("character_quit_job", {"character_id": c["id"]})


def get_work_summary(c, world):
    """Return a human-readable work experience summary for LLM context."""
    lines = []
    start = c.get("current_job_start_tick")
    if c.get("employed") and start is not None:
        years_here = _ticks_to_years(world["tick"] - start)
        title = c.get("job", {}).get("title") if isinstance(c.get("job"), dict) else c.get("profession", "current job")
        company = c.get("company_id", "")
        lines.append(f"Currently: {title}{' at ' + company if company else ''} ({years_here}y)")

    for entry in reversed(c.get("work_history", [])[-4:]):
        t = entry.get("title") or entry.get("job_template_id", "?")
        y = entry.get("years", 0)
        co = entry.get("company_id", "")
        r  = entry.get("reason_left", "")
        lines.append(f"Previously: {t}{' at ' + co if co else ''} — {y}y ({r})")

    exp = c.get("industry_experience", {})
    if exp:
        top = sorted(exp.items(), key=lambda x: -x[1])[:3]
        lines.append("Industry exp: " + ", ".join(f"{k}: {_ticks_to_years(v)}y" for k, v in top))

    return "\n".join(lines) if lines else "No work history."
