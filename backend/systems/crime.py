"""
systems/crime.py

A real path into crime -- see the "Criminal careers" plan. Illegal
job_templates (drug_dealer_low, mobster, hitman, ...) are deliberately
excluded from both the normal generation-time hire (character_gen.py::
_assign_job) and the normal runtime job-board flow (jobs.py::
apply_for_job) -- entry is opportunity-driven, through this module, not
something a character stumbles into or applies to off a listing.

Phase B (this section): maybe_recruit_into_crime() -- a daily-cadence
roll for unemployed/legally-employed teens+adults, weighted by financial
desperation, risk-factor traits, and (the dominant factor) already
knowing someone in a criminal job or faction. _hire_into_criminal_job()
mirrors jobs.py::process_interview()'s real hire field shape (flat
job_id/job_template_id/hourly_wage/employed/...) AND character_gen.py's
nested c["job"] shape, since both exist in this codebase and different
systems read one or the other -- see _is_in_illegal_job() below, which
checks both so it stays correct regardless of how a character got hired.
"""

import random
import uuid

RISK_TRAITS = {
    "impulsive", "aggressive", "greedy", "hot_tempered",
    "reckless", "ambitious", "manipulative", "ruthless",
}

BASE_RECRUIT_CHANCE   = 0.0008
UNEMPLOYED_BONUS      = 0.004
DESPERATION_WEALTH    = 500.0
DESPERATION_BONUS     = 0.01
DEBT_BONUS            = 0.005
RISK_TRAIT_BONUS      = 0.006
CRIMINAL_CONTACT_BONUS = 0.03

_ENTRY_JOBS_BY_TRAIT = {
    "aggressive":   ["street_robber", "street_fighter"],
    "hot_tempered": ["street_robber", "street_fighter"],
    "greedy":       ["drug_dealer_low", "burglar"],
    "manipulative": ["drug_dealer_low", "fraudster"],
    "reckless":     ["car_thief", "burglar"],
    "impulsive":    ["street_robber", "car_thief"],
    "ruthless":     ["street_fighter", "burglar"],
    "ambitious":    ["drug_dealer_low", "fraudster"],
}
_DEFAULT_ENTRY_JOBS = ["drug_dealer_low", "car_thief", "burglar", "street_robber", "street_fighter"]


def _is_in_illegal_job(c, world):
    job = c.get("job") or {}
    if job.get("illegal"):
        return True
    tid = c.get("job_template_id")
    if tid:
        defs = world.get("definitions", {})
        if defs.get("job_templates", {}).get(tid, {}).get("illegal"):
            return True
    return False


def _has_criminal_contact(c, world):
    characters = world.get("characters", {})
    for other_id in c.get("relationships", {}):
        other = characters.get(other_id)
        if not other:
            continue
        if _is_in_illegal_job(other, world) or other.get("faction_memberships"):
            return True
    return False


def maybe_recruit_into_crime(c, world):
    """Daily-cadence opportunity roll -- see module docstring. No-ops for
    children/elderly and anyone already in a criminal job."""
    if c.get("age_group") not in ("teen", "adult"):
        return False
    if _is_in_illegal_job(c, world):
        return False

    chance = BASE_RECRUIT_CHANCE

    if not c.get("employed"):
        chance += UNEMPLOYED_BONUS

    household = world.get("households", {}).get(c.get("household_id"))
    if household and household.get("wealth", 0) < DESPERATION_WEALTH:
        chance += DESPERATION_BONUS
    if c.get("government_debt", 0) > 0:
        chance += DEBT_BONUS

    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    matching_traits = traits & RISK_TRAITS
    chance += len(matching_traits) * RISK_TRAIT_BONUS

    has_contact = _has_criminal_contact(c, world)
    if has_contact:
        chance += CRIMINAL_CONTACT_BONUS

    if random.random() > chance:
        return False

    pool = _DEFAULT_ENTRY_JOBS
    for trait in matching_traits:
        if trait in _ENTRY_JOBS_BY_TRAIT:
            pool = _ENTRY_JOBS_BY_TRAIT[trait]
            break

    job_id = random.choice(pool)
    _hire_into_criminal_job(c, world, job_id)
    return True


def _hire_into_criminal_job(c, world, job_id, company_id=None):
    """No public listing/interview -- criminal work isn't advertised.
    Sets both the flat runtime-hire fields (jobs.py::process_interview's
    real shape) and the nested c["job"] dict (character_gen.py's shape)
    so either kind of consumer reads it correctly."""
    defs = world.get("definitions", {})
    tmpl = defs.get("job_templates", {}).get(job_id)
    if not tmpl:
        return None

    tick = world.get("tick", 0)

    c["employed"]               = True
    c["job_searching"]          = False
    c["job_id"]                 = None  # not a real posted listing
    c["job_template_id"]        = job_id
    c["company_id"]             = company_id
    c["profession"]             = job_id
    c["hourly_wage"]            = tmpl.get("hourly_wage", 0)
    c["current_job_start_tick"] = tick

    c["job"] = {
        "id":              job_id,
        "title":           tmpl.get("name", job_id),
        "industry":        tmpl.get("industry"),
        "income_class":    tmpl.get("income_class"),
        "average_salary":  tmpl.get("average_salary", 0),
        "hourly_wage":     tmpl.get("hourly_wage", 0),
        "salary":          tmpl.get("salary", 0),
        "work_mode":       tmpl.get("work_mode", "On-site"),
        "physical_demand": tmpl.get("physical_demand", 50),
        "social_demand":   tmpl.get("social_demand", 50),
        "hazard_level":    tmpl.get("hazard_level", "Low"),
        "illegal":         tmpl.get("illegal", False),
        "adult_industry":  tmpl.get("adult_industry", False),
        "criminal_tier":   tmpl.get("criminal_tier"),
        "hired_tick":      tick,
    }

    try:
        from brain.memory import store_memory
        store_memory(c, f"Started working as a {tmpl.get('name', job_id)}.", .7,
                     ["job", "criminal"], "crime", tick)
    except Exception:
        pass

    if job_id == "drug_producer":
        c["production_drug_type"] = random.choice(["amphetamine", "heroin", "weed"])
        _recruit_production_crew(c, world)

    if job_id in VIOLENT_GUN_JOBS and random.random() < VIOLENT_GUN_HIRE_CHANCE:
        grant_starter_firearm(c, world)

    return c["job"]


# =========================================================
# DRUG PRODUCTION -- more people, not a solo operator (Phase B of the
# drug-economy plan, Confirmed Decision #3)
# =========================================================

PRODUCTION_CREW_SIZE = (1, 3)
_PRODUCTION_SUPPORT_ROLES = ["street_fighter", "getaway_driver", "drug_dealer_low"]


def _recruit_production_crew(c, world):
    """A production operation involves more people -- rolls 1-3 real
    supporting hires, preferring the producer's own household/close
    contacts (reuses systems/sports.py's identical contact-scan helper
    rather than a second implementation) and falling back to any
    eligible character in the world if there aren't enough."""
    n = random.randint(*PRODUCTION_CREW_SIZE)
    characters = world.get("characters", {})

    from systems.sports import _household_and_close_contacts
    contact_ids = _household_and_close_contacts(world, c["id"])
    pool = [characters[cid] for cid in contact_ids if cid in characters]
    pool = [p for p in pool if p.get("age_group") in ("teen", "adult") and not _is_in_illegal_job(p, world)]

    if len(pool) < n:
        seen = {p["id"] for p in pool}
        extra = [p for p in characters.values()
                 if p.get("age_group") in ("teen", "adult")
                 and p["id"] not in seen and p["id"] != c["id"]
                 and not _is_in_illegal_job(p, world)]
        random.shuffle(extra)
        pool += extra

    for recruit in pool[:n]:
        role = random.choice(_PRODUCTION_SUPPORT_ROLES)
        _hire_into_criminal_job(recruit, world, role)


# =========================================================
# GANG WARS (Phase C of the drug-economy plan)
#
# rival_faction_ids is confirmed (grep) to never actually get populated
# anywhere in this codebase -- process_rival_tensions() (faction_ai.py)
# already falls back to template-level rival_types for exactly this
# reason, so this reuses that same dual check rather than depending on
# a field nothing ever writes to. Also skips process_rival_tensions'
# shared-territory requirement: spawn_faction() leaves territory empty
# unless a neighborhood_id is passed, and seed_factions_from_companies()
# (the only real caller in this codebase) never passes one -- gating on
# it would mean this never fires in practice.
# =========================================================

GANG_WAR_BASE_CHANCE = 0.05
GANG_WAR_PRODUCTION_BONUS = 0.15


def _are_rival_factions(fac_a, fac_b, world):
    if fac_b["id"] in fac_a.get("rival_faction_ids", []):
        return True
    defs = world.get("definitions", {})
    rival_types = defs.get("faction_templates", {}).get(fac_a.get("template_id", ""), {}).get("rival_types", [])
    return fac_b.get("template_id") in rival_types


def _faction_has_producer(fac, world):
    characters = world.get("characters", {})
    for cid in fac.get("members", []):
        c = characters.get(cid)
        if c and (c.get("job_template_id") or (c.get("job") or {}).get("id")) == "drug_producer":
            return True
    return False


def tick_gang_wars(world):
    """Daily-cadence pass: real violence between rival criminal
    factions, weighted up when one side runs drug production (Confirmed
    Decisions #5/#6 of the drug-economy plan)."""
    factions = list(world.get("factions", {}).values())
    for i, fac in enumerate(factions):
        if not fac.get("active") or fac.get("type") not in ("criminal", "criminal_organized"):
            continue
        for rival in factions[i + 1:]:
            if not rival.get("active") or rival.get("type") not in ("criminal", "criminal_organized"):
                continue
            if not _are_rival_factions(fac, rival, world):
                continue
            _maybe_gang_violence(fac, rival, world)


def _maybe_gang_violence(fac_a, fac_b, world):
    chance = GANG_WAR_BASE_CHANCE
    if _faction_has_producer(fac_a, world) or _faction_has_producer(fac_b, world):
        chance += GANG_WAR_PRODUCTION_BONUS

    if random.random() > chance:
        return

    characters = world.get("characters", {})
    members_a = [characters[cid] for cid in fac_a.get("members", []) if cid in characters]
    members_b = [characters[cid] for cid in fac_b.get("members", []) if cid in characters]
    if not members_a or not members_b:
        return

    _escalate_gang_violence(random.choice(members_a), random.choice(members_b), world)


def _escalate_gang_violence(char_a, char_b, world):
    """Real member-vs-member violence -- mirrors _escalate_team_rivalry's
    shape (grievance both ways, fighting-strength-weighted winner, loser
    takes a real injury) but feeds the gang_violence crime type."""
    from systems.grievances import add_grievance
    from systems.rival_cascade import _fighting_strength
    from systems.health import apply_injury

    tick = world.get("tick", 0)

    add_grievance(char_a, char_b["id"], "gang_violence", world, details={"context": "gang_war"})
    add_grievance(char_b, char_a["id"], "gang_violence", world, details={"context": "gang_war"})

    a_str, b_str = _fighting_strength(char_a), _fighting_strength(char_b)
    total = a_str + b_str or 1.0
    winner, loser = (char_a, char_b) if random.random() < (a_str / total) else (char_b, char_a)

    template = random.choice(["stab_wound", "shattered_bone", "deep_laceration"])
    apply_injury(loser, world, template, "gang_violence", tick=tick)

    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(winner, world, "angry_verbal")
        trigger_reaction(loser, world, "scared_verbal")
    except Exception:
        pass

    world.setdefault("incidents", []).append({
        "id":             f"inc_{uuid.uuid4().hex[:8]}",
        "type":           "gang_violence",
        "tick":           tick,
        "participants":   [char_a["id"], char_b["id"]],
        "arrest_checked": False,
    })

    try:
        from core.event_bus import emit
        emit("fight_physical", {
            "parties": [char_a["id"], char_b["id"]],
            "winner": winner["id"], "loser": loser["id"],
            "context": "gang_war", "tick": tick,
        })
    except Exception:
        pass


# =========================================================
# GUNS (Phase G)
#
# "Does this household own a gun" is always computed by scanning
# inventories -- never a stored flag, one source of truth. Two grant
# paths, both reusing the same helper: shooting_sports hobby pickup
# (sync_gun_hobbies, since no hobby's required_items get auto-stocked
# today -- confirmed via grep, this is the one gap this plan fixes),
# and violent/gun-adjacent criminal hire (above).
# =========================================================

VIOLENT_GUN_JOBS = {
    "street_robber", "robber_establishments", "hitman", "torpedo",
    "mobster", "mobster_boss", "street_fighter", "weapons_dealer",
}
VIOLENT_GUN_HIRE_CHANCE = 0.55
RIFLE_VS_FIREARM_CHANCE = 0.15


def grant_starter_firearm(c, world, rifle_chance=RIFLE_VS_FIREARM_CHANCE):
    """No-ops if this character already owns one. Returns True if a real
    firearm/rifle + ammunition were actually added."""
    from systems.personal_items import get_item_by_template, make_item, add_item
    if get_item_by_template(c, "firearm") or get_item_by_template(c, "rifle"):
        return False
    template_id = "rifle" if random.random() < rifle_chance else "firearm"
    add_item(c, make_item(template_id, world=world))
    add_item(c, make_item("ammunition", world=world))
    return True


def household_owns_firearm(world, household_id):
    if not household_id:
        return False
    from systems.personal_items import get_item_by_template
    for c in world.get("characters", {}).values():
        if c.get("household_id") != household_id:
            continue
        if get_item_by_template(c, "firearm") or get_item_by_template(c, "rifle"):
            return True
    return False


def sync_gun_hobbies(c, world):
    """Called wherever hobbies get (re)assigned -- see systems/sports.py's
    identical sync-on-pickup pattern (sync_sports_hobbies)."""
    if "shooting_sports" in c.get("hobbies", []):
        grant_starter_firearm(c, world)


# =========================================================
# CAREER PROGRESSION + REAL FACTION MEMBERSHIP (Phase C)
#
# The drug track's 5 named tiers (Street Dealer, Middle Management,
# Organized Crime Initiate/Member/Leadership) map onto real, already-
# authored data: the first two are solo job_template promotions
# (drug_dealer_low -> drug_dealer_mid); the last three are REAL
# recruitment into a world["factions"] entry (see faction_ai.py::
# join_faction, previously dead -- nothing ever called it) at the
# bottom of that faction's own typical_roles list, then upward movement
# through it, bucketed into initiate/member/leadership.
# =========================================================

TIER_UP_THRESHOLD = {
    "drug_dealer_low": 40.0,   # -> drug_dealer_mid
    "drug_dealer_mid": 80.0,   # -> real faction recruitment
}

FACTION_ROLE_TIERS = {
    "street_gang":  {"initiate": ["runner"],    "member": ["enforcer", "lieutenant"], "leadership": ["leader"]},
    "crime_family": {"initiate": ["associate"], "member": ["soldier", "capo"],        "leadership": ["underboss", "boss"]},
}
FACTION_PROMOTE_THRESHOLD = {"initiate": 120.0, "member": 220.0}
STANDING_DAILY_DECAY = 0.99


def _find_recruitable_faction(world, template_id):
    for fac in world.get("factions", {}).values():
        if fac.get("template_id") == template_id and fac.get("active"):
            return fac
    return None


def tick_criminal_career_progression(world):
    """Daily-cadence pass over every character currently in a criminal
    job -- see module docstring."""
    for c in world.get("characters", {}).values():
        _progress_character(c, world)


def _progress_character(c, world):
    if not _is_in_illegal_job(c, world):
        return

    c["criminal_standing"] = max(0.0, c.get("criminal_standing", 0.0) * STANDING_DAILY_DECAY)
    standing = c["criminal_standing"]

    # Already a member of a real criminal faction -- progress up its own
    # role ladder as standing keeps climbing, and stop there. Takes
    # priority over the solo tier-up checks below: job_template_id
    # doesn't change on recruitment (a gang member's day-job title stays
    # whatever got them recruited -- the faction role is the real rank
    # now), so without this early return a still-"drug_dealer_mid"
    # member would just keep re-triggering (harmlessly no-op'd) faction
    # recruitment forever instead of ever climbing its ladder.
    in_criminal_faction = False
    for mem in c.get("faction_memberships", []):
        fac = world.get("factions", {}).get(mem["faction_id"])
        if not fac:
            continue
        tiers = FACTION_ROLE_TIERS.get(fac.get("template_id"))
        if not tiers:
            continue
        in_criminal_faction = True
        current_bucket = next((b for b, roles in tiers.items() if mem["role"] in roles), None)
        if current_bucket == "initiate" and standing >= FACTION_PROMOTE_THRESHOLD["initiate"]:
            mem["role"] = tiers["member"][0]
        elif current_bucket == "member" and standing >= FACTION_PROMOTE_THRESHOLD["member"]:
            mem["role"] = tiers["leadership"][0]
            if c["id"] not in fac.setdefault("leaders", []):
                fac["leaders"].append(c["id"])
    if in_criminal_faction:
        return

    job_tid = c.get("job_template_id") or (c.get("job") or {}).get("id")
    threshold = TIER_UP_THRESHOLD.get(job_tid)
    if threshold is None or standing < threshold:
        return

    if job_tid == "drug_dealer_low":
        _hire_into_criminal_job(c, world, "drug_dealer_mid")
    elif job_tid == "drug_dealer_mid":
        fac = _find_recruitable_faction(world, "street_gang") or _find_recruitable_faction(world, "crime_family")
        if fac:
            bottom_role = FACTION_ROLE_TIERS[fac["template_id"]]["initiate"][0]
            from systems.faction_ai import join_faction
            join_faction(c, fac, role=bottom_role, world=world)


# =========================================================
# COMMITTING CRIMES -- shared per-shift resolution (Phase D)
#
# Hooked into offgrid.py's existing `reason == "work"` branch (every
# job, legal or not, already goes off-grid through that exact path) for
# any character whose job is illegal. Only creates the incident record --
# whether it actually leads to an arrest is entirely law.py::
# maybe_arrest_from_incidents()'s job (Phase F), reusing the same
# crime_solve_rate roll every other crime type already uses, not a
# second, disconnected risk system.
# =========================================================

CRIME_SHIFT_ROLL_CHANCE = 0.35  # not every shift is a scorable "job" -- some are quiet/logistics

CRIME_PROFILES = {
    "drug_dealer_low":      {"incident_type": "drug_dealing", "cash_range": (30, 150),   "standing_gain": 3.0},
    "drug_dealer_mid":      {"incident_type": "drug_dealing", "cash_range": (150, 600),  "standing_gain": 5.0},
    # Production margins are deliberately well above dealing (Confirmed
    # Decision #2 of the drug-economy plan) -- fewer, bigger scores per
    # shift, not a steady retail trickle.
    "drug_producer":        {"incident_type": "drug_production", "cash_range": (800, 2500), "standing_gain": 8.0},
    "smuggler":              {"incident_type": "smuggling",       "cash_range": (400, 1200), "standing_gain": 5.0},
    "car_thief":            {"incident_type": "car_theft",    "cash_range": (200, 800),  "standing_gain": 4.0},
    "burglar":              {"incident_type": "burglary",     "cash_range": (150, 700),  "standing_gain": 4.0},
    "street_robber":        {"incident_type": "robbery",      "cash_range": (20, 200),   "standing_gain": 3.0},
    "robber_establishments": {"incident_type": "robbery",     "cash_range": (500, 3000), "standing_gain": 6.0},
    "street_fighter":       {"incident_type": "assault",      "cash_range": (50, 250),   "standing_gain": 3.0},
    "fraudster":            {"incident_type": "fraud",        "cash_range": (100, 900),  "standing_gain": 3.5},
    "hacker":               {"incident_type": "hacking",      "cash_range": (150, 1200), "standing_gain": 3.5},
    "arsonist":             {"incident_type": "arson",        "cash_range": (300, 1500), "standing_gain": 5.0},
    "mobster":              {"incident_type": "assault",      "cash_range": (100, 400),  "standing_gain": 4.0},
    "torpedo":              {"incident_type": "assault",      "cash_range": (150, 500),  "standing_gain": 4.5},
    "getaway_driver":       {"incident_type": None,           "cash_range": (50, 300),   "standing_gain": 2.0},
    "weapons_dealer":       {"incident_type": None,           "cash_range": (100, 600),  "standing_gain": 3.0},
    "pimp":                 {"incident_type": None,           "cash_range": (100, 500),  "standing_gain": 2.5},
    "mobster_boss":         {"incident_type": None,           "cash_range": (0, 0),      "standing_gain": 2.0},
    # hitman/prostitute are deliberately absent -- both earn through their
    # own bespoke Phase E mechanics (commissioned contracts / the real
    # escort-hire pipeline), not a passive per-shift roll.
}


def resolve_criminal_shift(c, world):
    """Called from offgrid.py's reason=="work" handling. Returns a short
    summary suffix, or None if this shift didn't produce anything
    scorable (most shifts -- see CRIME_SHIFT_ROLL_CHANCE)."""
    job_tid = c.get("job_template_id") or (c.get("job") or {}).get("id")
    profile = CRIME_PROFILES.get(job_tid)
    if not profile:
        return None
    if random.random() > CRIME_SHIFT_ROLL_CHANCE:
        return None

    if job_tid == "burglar":
        # A real sneak-entry roll (systems/stealth.py) instead of an
        # abstract chance -- shared with Private Investigator
        # infiltration (tick_pi_assignments below).
        from systems.persona import generate_persona
        generate_persona(c, world, tags=["utility_worker", "delivery_worker", "inspector"])

        from systems.stealth import attempt_sneak_entry
        entry = attempt_sneak_entry(c, world)
        if not entry["entered"]:
            if entry["detected"]:
                world.setdefault("incidents", []).append({
                    "id": f"inc_{uuid.uuid4().hex[:8]}", "type": "burglary",
                    "tick": world.get("tick", 0), "participants": [c["id"]],
                    "arrest_checked": False,
                })
                return " Nearly got caught breaking in -- had to bail."
            return " Couldn't get in -- no good opening tonight."

    if job_tid == "drug_producer":
        # A production front needs a legit-looking cover too -- e.g. a
        # "lab worker"/"utility" persona for whatever front business
        # hides the operation.
        from systems.persona import generate_persona
        generate_persona(c, world, tags=["lab_worker", "utility_worker"])

    lo, hi = profile.get("cash_range", (0, 0))
    cash = random.uniform(lo, hi) if hi > 0 else 0.0
    if cash:
        household = world.get("households", {}).get(c.get("household_id"))
        if household:
            household["wealth"] = household.get("wealth", 0) + cash

    c["criminal_standing"] = c.get("criminal_standing", 0.0) + profile.get("standing_gain", 0.0)

    if profile.get("incident_type"):
        world.setdefault("incidents", []).append({
            "id":             f"inc_{uuid.uuid4().hex[:8]}",
            "type":           profile["incident_type"],
            "tick":           world.get("tick", 0),
            "participants":   [c["id"]],
            "arrest_checked": False,
        })

    return f" Made ${cash:.0f} on the side." if cash else None


# =========================================================
# PRIVATE INVESTIGATOR (Phase E) -- resolves world["pi_assignments"]
# entries created by systems/darknet.py's private_investigation
# category. Shares the stealth framework with Burglar above.
# =========================================================

PI_INFILTRATION_CHANCE = 0.4   # otherwise a car stakeout
PI_STAKEOUT_QUALITY = (0.3, 0.6)
PI_INFILTRATION_QUALITY = (0.6, 0.95)


def tick_pi_assignments(world):
    """Daily-cadence pass over pending PI assignments -- the
    investigator either stakes out (binoculars, lower risk/quality) or
    sneaks in to plant a device (systems/stealth.py, higher risk/
    quality). Either successful run creates a real, client-readable
    world["surveillance_feeds"] entry."""
    characters = world.get("characters", {})
    assignments = world.get("pi_assignments", [])

    for assignment in assignments:
        if assignment.get("status") != "pending":
            continue
        investigator = characters.get(assignment["investigator_id"])
        target = characters.get(assignment["target_id"])
        if not investigator or not target:
            assignment["status"] = "failed"
            continue

        assignment["status"] = "completed"

        from systems.stealth import has_entry_tool, attempt_sneak_entry
        method, quality = "stakeout", 0.0

        if has_entry_tool(investigator) and random.random() < PI_INFILTRATION_CHANCE:
            from systems.persona import generate_persona
            generate_persona(investigator, world, tags=["utility_worker", "delivery_worker", "inspector"])

            entry = attempt_sneak_entry(investigator, world)
            if entry["entered"]:
                quality = random.uniform(*PI_INFILTRATION_QUALITY)
                method = "planted_device"
            if entry["detected"]:
                world.setdefault("incidents", []).append({
                    "id": f"inc_{uuid.uuid4().hex[:8]}", "type": "burglary",
                    "tick": world.get("tick", 0), "participants": [investigator["id"]],
                    "arrest_checked": False,
                })
        else:
            from systems.personal_items import get_item_by_template
            has_binoculars = bool(get_item_by_template(investigator, "binoculars"))
            lo, hi = PI_STAKEOUT_QUALITY
            quality = min(1.0, random.uniform(lo, hi) * (1.2 if has_binoculars else 0.7))

        investigator["criminal_standing"] = investigator.get("criminal_standing", 0.0) + 2.0

        if quality > 0:
            _record_surveillance(world, assignment, target, quality, method)

    world["pi_assignments"] = [a for a in assignments if a["status"] == "pending"]


def _record_surveillance(world, assignment, target, quality, method):
    world.setdefault("surveillance_feeds", []).append({
        "id":        f"surv_{uuid.uuid4().hex[:8]}",
        "client_id": assignment["client_id"],
        "target_id": target["id"],
        "method":    method,
        "quality":   round(quality, 2),
        "report":    _summarize_target(target, quality),
        "tick":      world.get("tick", 0),
    })


# =========================================================
# CORRUPT PROFESSIONALS (Phase G)
#
# Certain LEGAL job_templates become periodically eligible for a real,
# opportunity-driven offer from an existing criminal faction -- they
# keep their real job, this is favor-for-cash side work, not a hire.
# Three real, compounding consequences as corruption climbs: harder to
# quit, more likely to get caught (law.py), and real physical risk.
# =========================================================

CORRUPTIBLE_JOBS = {"lawyer", "bank_teller", "accountant", "mayor", "police_officer"}
CORRUPTION_OFFER_CHANCE = 0.01
CORRUPTION_GAIN_PER_FAVOR = 8.0
CORRUPTION_CASH_RANGE = (500, 3000)
CORRUPTION_VIOLENCE_RISK_MAX = 0.03  # at corruption=100, ~3%/day


def maybe_offer_corruption(c, world):
    """Daily-cadence opportunity roll for eligible legal professionals.
    Resolved synchronously (mirrors this session's established
    commission_crime()/booty-call-style precedent for opportunity rolls)
    rather than an async proposal nobody's LLM turn might ever answer."""
    job_tid = c.get("job_template_id") or (c.get("job") or {}).get("id")
    if job_tid not in CORRUPTIBLE_JOBS:
        return False
    if random.random() > CORRUPTION_OFFER_CHANCE:
        return False

    accept_chance = 0.3 + (c.get("corruption", 0.0) / 150.0)
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    if traits & {"greedy", "ambitious", "manipulative"}:
        accept_chance += 0.15
    if random.random() > max(0.05, min(0.9, accept_chance)):
        return False

    cash = random.uniform(*CORRUPTION_CASH_RANGE)
    from systems.personal_items import add_cash
    add_cash(c, cash)
    c["corruption"] = min(100.0, c.get("corruption", 0.0) + CORRUPTION_GAIN_PER_FAVOR)

    world.setdefault("incidents", []).append({
        "id": f"inc_{uuid.uuid4().hex[:8]}", "type": "bribery",
        "tick": world.get("tick", 0), "participants": [c["id"]],
        "arrest_checked": False,
    })

    try:
        from brain.memory import store_memory
        store_memory(c, "Took a favor for cash -- crossed a line.", .75,
                     ["crime", "corruption"], "crime", world.get("tick", 0))
    except Exception:
        pass

    return True


def attempt_quit_corruption(c, world):
    """Success chance DECREASES as corruption rises -- the faction has
    more leverage the deeper someone's in. Returns True on success
    (corruption resets to 0), False otherwise -- a real, playable-out
    struggle, not an instant escape."""
    corruption = c.get("corruption", 0.0)
    if corruption <= 0:
        return True
    quit_chance = max(0.05, 0.9 - (corruption / 120.0))
    if random.random() < quit_chance:
        c["corruption"] = 0.0
        return True
    return False


def tick_corruption_risk(world):
    """Daily-cadence pass: real physical risk that scales with
    corruption -- the faction silencing a liability, or a rival gang
    making an example."""
    for c in world.get("characters", {}).values():
        corruption = c.get("corruption", 0.0)
        if corruption <= 0:
            continue
        if random.random() > (corruption / 100.0) * CORRUPTION_VIOLENCE_RISK_MAX:
            continue
        _apply_corruption_violence(c, world)


def _apply_corruption_violence(c, world):
    tick = world.get("tick", 0)
    if random.random() < 0.15:
        from systems.health import _trigger_death
        _trigger_death(c, world, "corruption_silencing")
    else:
        from systems.health import apply_injury
        template = random.choice(["stab_wound", "shattered_bone", "deep_laceration"])
        apply_injury(c, world, template, "corruption_warning", tick=tick)

    world.setdefault("incidents", []).append({
        "id": f"inc_{uuid.uuid4().hex[:8]}", "type": "gang_violence",
        "tick": tick, "participants": [c["id"]], "arrest_checked": False,
    })


def _summarize_target(target, quality):
    """A rough intel report -- richer with higher quality (a successful
    device plant) than a distant stakeout."""
    parts = [f"{target.get('name', 'Target')} was observed"]
    occupation = target.get("occupation") or (target.get("job") or {}).get("title")
    if occupation and occupation != "none":
        parts.append(f"working as {occupation}")
    if quality > 0.6:
        if target.get("household_id"):
            parts.append("returning to their residence")
        if target.get("faction_memberships"):
            parts.append("with apparent gang ties")
    return ", ".join(parts) + "."


# =========================================================
# ARREST FALLOUT (Phase F -- called from law.py::schedule_trial)
# =========================================================

ARREST_STANDING_PENALTY = 30.0
DEMOTION_STANDING_THRESHOLD = 20.0
DEMOTION_CHANCE = 0.3


def apply_arrest_penalty(c, world):
    """An arrest costs standing, not just jail time; a low-standing
    bottom-rung faction member risks getting cut loose back to freelance
    -- light-touch demotion, not a full expulsion-drama system."""
    if c.get("criminal_standing", 0.0) <= 0 and not c.get("faction_memberships"):
        return

    c["criminal_standing"] = max(0.0, c.get("criminal_standing", 0.0) - ARREST_STANDING_PENALTY)

    for mem in list(c.get("faction_memberships", [])):
        fac = world.get("factions", {}).get(mem["faction_id"])
        if not fac:
            continue
        tiers = FACTION_ROLE_TIERS.get(fac.get("template_id"))
        if not tiers or mem["role"] not in tiers.get("initiate", []):
            continue  # established members/leaders aren't cut loose this easily
        if c["criminal_standing"] < DEMOTION_STANDING_THRESHOLD and random.random() < DEMOTION_CHANCE:
            from systems.faction_ai import leave_faction
            leave_faction(c, mem["faction_id"], world=world)


# =========================================================
# STREET ROBBER -- wires the previously-dead steal_from interaction
# (Phase E). Routed from action_router.py::_route_steal_from().
# =========================================================

STEAL_METHOD_SUCCESS = {
    "pickpocket":           0.55,
    "snatch":                0.65,
    "demand_at_knifepoint":  0.85,
    "demand_at_gunpoint":    0.92,
}
STEAL_CASH_RANGE = (20, 150)
STEAL_STANDING_GAIN = 5.0


def resolve_steal_from(actor, target, method, world):
    """A real, player-visible mugging -- not the shared shift roll
    (Confirmed Decision #7). Any actor can attempt this, not just a
    street_robber, but only a street_robber's success feeds their own
    criminal_standing."""
    from systems.personal_items import wallet_cash, spend_cash, add_cash

    tick = world.get("tick", 0)
    success = random.random() < STEAL_METHOD_SUCCESS.get(method, 0.5)

    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(target, world, "scared_verbal" if method.startswith("demand") else "startled")
    except Exception:
        pass

    stolen = 0.0
    if success:
        available = wallet_cash(target)
        take = min(available, random.uniform(*STEAL_CASH_RANGE))
        if take > 0 and spend_cash(target, take):
            add_cash(actor, take)
            stolen = take

    from brain.relationships import ensure_relationship
    rel = ensure_relationship(target, actor["id"])
    rel["trust"] = max(-100, rel.get("trust", 0) - 40)
    rel["hostility"] = min(100, rel.get("hostility", 0) + 30)

    try:
        from systems.reputation import apply_reputation_event
        apply_reputation_event(actor, "robbery", world, magnitude_override=-0.10)
    except Exception:
        pass

    world.setdefault("incidents", []).append({
        "id":             f"inc_{uuid.uuid4().hex[:8]}",
        "type":           "robbery",
        "tick":           tick,
        "participants":   [actor["id"], target["id"]],
        "arrest_checked": False,
    })

    if success and (actor.get("job_template_id") or (actor.get("job") or {}).get("id")) == "street_robber":
        actor["criminal_standing"] = actor.get("criminal_standing", 0.0) + STEAL_STANDING_GAIN

    try:
        from brain.memory import store_memory
        if success:
            store_memory(target, f"Was robbed by {actor.get('name', 'someone')} (${stolen:.0f} taken).", .85,
                         ["crime", "robbery", "victim"], "crime", tick)
            store_memory(actor, f"Robbed {target.get('name', 'someone')} for ${stolen:.0f}.", .8,
                         ["crime", "robbery"], "crime", tick)
        else:
            store_memory(actor, f"Tried to rob {target.get('name', 'someone')} but they got away.", .6,
                         ["crime", "robbery", "failed"], "crime", tick)
    except Exception:
        pass

    return {"success": success, "stolen": stolen}


# =========================================================
# HIRED KILLER / TORPEDO -- commissioned contracts (Phase E)
#
# A real, money-driven commission, not a menu action: opens a real
# proposals.py record for the ledger/narrative, same as any other favor
# ask, but resolves acceptance synchronously here (mirrors this
# session's own established fix for the identical async-proposal-timing
# problem in sexual_release.py's booty-call path) instead of waiting
# indefinitely on the provider's own LLM turn. Torpedo is real but never
# lethal (a beating/intimidation, health.py::apply_injury). Hired Killer
# is the one deliberately high-stakes, rare mechanic in this whole plan
# -- gated by real cost, a real accept-chance, and a real, low but
# genuine success rate before it reaches health.py::_trigger_death(); a
# botched hit is a real, survivable outcome, not guaranteed.
# =========================================================

COMMISSION_COST = {"torpedo": 300.0, "hitman": 5000.0}
COMMISSION_ACCEPT_BASE = 0.6
HIT_SUCCESS_CHANCE = {"torpedo": 0.85, "hitman": 0.55}
COMMISSION_STANDING_GAIN = {"torpedo": 6.0, "hitman": 10.0}


def commission_crime(commissioner, target, provider, world, kind="torpedo"):
    """provider must actually hold the matching job (kind == job_template_id).
    Returns {"ok": bool, "reason"?: str, "outcome"?: "beaten"|"killed"|"botched"}."""
    if kind not in COMMISSION_COST:
        return {"ok": False, "reason": "unknown_kind"}

    job_tid = provider.get("job_template_id") or (provider.get("job") or {}).get("id")
    if job_tid != kind:
        return {"ok": False, "reason": "wrong_provider"}

    from systems.personal_items import wallet_cash, spend_cash, add_cash
    cost = COMMISSION_COST[kind]
    if wallet_cash(commissioner) < cost:
        return {"ok": False, "reason": "cant_afford"}

    try:
        from systems.proposals import propose_request
        propose_request(commissioner, provider, world, f"commission_{kind}",
                         f"wants {target.get('name', 'someone')} dealt with", "high")
    except Exception:
        pass

    from brain.relationships import ensure_relationship
    rel = ensure_relationship(provider, commissioner["id"])
    accept_chance = COMMISSION_ACCEPT_BASE + (rel.get("trust", 0) / 200.0)
    if random.random() > max(0.05, min(0.95, accept_chance)):
        return {"ok": False, "reason": "declined"}

    spend_cash(commissioner, cost)
    add_cash(provider, cost)
    provider["criminal_standing"] = provider.get("criminal_standing", 0.0) + COMMISSION_STANDING_GAIN[kind]

    outcome = _resolve_hit(provider, target, world, kind)

    world.setdefault("incidents", []).append({
        "id":             f"inc_{uuid.uuid4().hex[:8]}",
        "type":           "murder_for_hire" if kind == "hitman" else "assault",
        "tick":           world.get("tick", 0),
        "participants":   [commissioner["id"], provider["id"]],
        "arrest_checked": False,
    })

    return {"ok": True, "outcome": outcome}


def _resolve_hit(provider, target, world, kind):
    tick = world.get("tick", 0)
    success = random.random() < HIT_SUCCESS_CHANCE.get(kind, 0.7)

    if kind == "torpedo":
        from systems.health import apply_injury
        if success:
            template = "fall_fracture" if random.random() < 0.5 else "strained_muscle"
            apply_injury(target, world, template, "torpedo_beating", tick=tick)
            return "beaten"
        return "botched"

    # hitman
    from systems.health import apply_injury
    if success:
        from systems.health import _trigger_death
        _trigger_death(target, world, "hired_hit")
        return "killed"
    template = "stab_wound" if random.random() < 0.5 else "shattered_bone"
    apply_injury(target, world, template, "botched_hit", tick=tick)
    return "botched"
