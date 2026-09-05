"""
character_gen.py — procedural character generation.
Entry point: generate_character(defs, overrides={}) -> dict
"""
import random
import uuid

TICKS_PER_YEAR = 365 * 24  # ~8760 ticks per simulated year

# ── Education rank (ascending) ────────────────────────────────────────────────
# Mirrors jobs.py::apply_for_job()'s edu_rank dict exactly -- job_templates'
# degree_required and school_templates' education_level both use this
# vocabulary (preschool/primary/trade_school/certificate/...), not the old
# elementary/some_college one that used to live here and had no matching
# content anywhere.
_EDU_RANK = {
    "none": 0, "none_completed": 0, "preschool": 0, "primary": 0,
    "middle_school": 0, "high_school": 1, "trade_school": 2, "certificate": 2,
    "associate": 3, "bachelor": 4, "master": 5, "doctorate": 6, "professional": 6,
}

# Fraction of characters who get a distinctive speech/writing quirk (see
# speech_style_registry in definitions.json) -- most sims talk/write in
# an unremarkable, generic way; this is deliberately a minority.
SPEECH_STYLE_CHANCE = 0.15

# ── Helpers ───────────────────────────────────────────────────────────────────

def _random_sex():
    return random.choice(["male", "female"])

def _random_age(defs):
    dist = defs.get("age_distribution", {})
    brackets = dist.get("brackets", []) if isinstance(dist, dict) else []
    if brackets:
        valid = [b for b in brackets if b.get("probability", 0) > 0]
        if valid:
            weights = [b["probability"] for b in valid]
            bracket = random.choices(valid, weights=weights, k=1)[0]
            return random.randint(bracket.get("min_age", 5), bracket.get("max_age", 80))
    return random.randint(5, 80)

def _age_group(age):
    if age < 13:   return "child"
    if age < 18:   return "teen"
    if age < 30:   return "adult"
    if age < 60:   return "adult"
    return "elderly"

def _random_name(defs, sex):
    names = defs.get("names", {})
    first_list = names.get("first", {}).get(sex, ["Alex"])
    last_list  = names.get("last", ["Smith"])
    first = random.choice(first_list) if first_list else "Alex"
    last  = random.choice(last_list)  if last_list  else "Smith"
    return first, last

def _random_ssn():
    """Format XXX-XX-XXXX, flavor-only identity data (not validated against
    any real SSA allocation rules)."""
    return f"{random.randint(0, 999):03d}-{random.randint(0, 99):02d}-{random.randint(0, 9999):04d}"

def _attained_education(age):
    if age < 10:  return "primary"
    if age < 13:  return "middle_school"
    if age < 18:  return "high_school"
    r = random.random()
    if r < 0.10:  return "high_school"
    if r < 0.22:  return "certificate"
    if r < 0.34:  return "associate"
    if r < 0.65:  return "bachelor"
    if r < 0.80:  return "certificate"
    if r < 0.88:  return "bachelor"
    if r < 0.93:  return "master"
    if r < 0.98:  return "doctorate"
    return "professional"

def _random_skills(defs, job=None):
    # skill_templates may not be defined; return empty list gracefully
    all_skills = defs.get("skill_templates", {})
    if not all_skills:
        return []
    if isinstance(all_skills, dict):
        if job and isinstance(job, dict):
            sector = job.get("industry", "")
            sector_skills = all_skills.get(sector, [])
            if sector_skills:
                return random.sample(sector_skills, min(3, len(sector_skills)))
        flat = [s for sl in all_skills.values() if isinstance(sl, list) for s in sl]
        return random.sample(flat, min(3, len(flat))) if flat else []
    return []

# How low a zone's cleanliness (0-100, 100=spotless) has to fall before
# this character reacts to it -- same shape as body_intentions.py's
# per-trait shower_threshold (lazy tolerates more mess, organized reacts
# sooner). Kept in one place rather than recomputed inline at every call
# site, since the mess-reaction check runs from several places (self,
# nagging, a parent judging a child's room by the PARENT's own threshold).
def cleanliness_threshold_for_traits(traits):
    tr = set(traits or [])
    threshold = 40
    if "lazy" in tr or "careless" in tr:
        threshold = 65
    if "organized" in tr:
        threshold = 25
    return threshold


def _random_traits(defs, sex=None, age=None):
    from systems.schema_defaults import COGNITION_CORE_TRAITS
    from systems.trait_chance import cognition_type_of, weighted_trait_pick

    pool = defs.get("trait_templates", {})
    pool = {k: v for k, v in pool.items() if not k.startswith("_")} if isinstance(pool, dict) else {}
    # Cognition core traits (Logical/Balanced/Self-Aware) are assigned
    # separately below, one per character, and excluded from the general
    # trait pool so the weighted pick can't also pick one as a "regular" trait.
    pool = {k: v for k, v in pool.items() if k not in COGNITION_CORE_TRAITS}

    cognition_trait = random.choice(list(COGNITION_CORE_TRAITS.keys()))
    if not pool:
        return [cognition_trait]

    cognition_key = COGNITION_CORE_TRAITS[cognition_trait]
    # Minimal character-shaped dict so per-trait `conditions` (sex/age) can
    # be evaluated at generation time -- household/friend-based
    # num_influencers conditions have nothing to check yet at this point
    # and simply fail closed (see trait_chance.py).
    pseudo_char = {"sex": sex, "age": age if age is not None else 0, "traits": [cognition_trait]}
    picked = weighted_trait_pick(pool, pseudo_char, cognition_key, 3, existing=[cognition_trait])
    return [cognition_trait] + picked

# ── Values (systems/schema_defaults.py::VALUE_CATEGORIES) ──────────────────────
# Fully random per category for unrelated/adult-generated characters.
# parent_values (a list of 1-2 parent c["values"] dicts, passed by
# baby.py/relative_gen.py for an actual birth/derivation) nudges each
# category's importance toward the parents' average with jitter, and
# biases conform toward a parent's with above-chance probability -- nature
# + nurture, not a straight copy, matching how trait inheritance elsewhere
# in this codebase (e.g. relative_gen.py) already avoids exact cloning.
_VALUE_PARENT_JITTER      = 0.15   # +/- random spread around parent average
_VALUE_PARENT_CONFORM_BIAS = 0.70  # chance conform matches a (random) parent's


def _seed_values(defs, parent_values=None):
    from systems.schema_defaults import VALUE_CATEGORIES

    if not parent_values:
        return {cat: {"importance": round(random.uniform(0.0, 1.0), 2),
                       "conform": random.random() < 0.5}
                for cat in VALUE_CATEGORIES}

    values = {}
    for cat in VALUE_CATEGORIES:
        parent_importances = [pv.get(cat, {}).get("importance", 0.5) for pv in parent_values]
        avg = sum(parent_importances) / len(parent_importances)
        importance = avg + random.uniform(-_VALUE_PARENT_JITTER, _VALUE_PARENT_JITTER)
        importance = max(0.0, min(1.0, round(importance, 2)))

        if random.random() < _VALUE_PARENT_CONFORM_BIAS:
            conform = random.choice(parent_values).get(cat, {}).get("conform", True)
        else:
            conform = random.random() < 0.5

        values[cat] = {"importance": importance, "conform": conform}
    return values

# ── Curiosity (systems/schema_defaults.py's 0-100 curiosity field) ─────────────
# Trait-correlated jitter, mirroring _seed_values()'s style -- no parent-nudge
# (unlike values, curiosity isn't modeled as generationally transmitted here;
# easy to add later if wanted).
_CURIOSITY_BASELINE_RANGE = (30, 70)
_CURIOSITY_TRAIT_BOOST_RANGE = (15, 25)
_CURIOSITY_TRAIT_BOOST_TRAITS = ("curious", "intellectual")


def _seed_curiosity(traits):
    curiosity = random.randint(*_CURIOSITY_BASELINE_RANGE)
    if any(t in traits for t in _CURIOSITY_TRAIT_BOOST_TRAITS):
        curiosity += random.randint(*_CURIOSITY_TRAIT_BOOST_RANGE)
    return max(0, min(100, curiosity))


def _random_hobbies(defs):
    pool = defs.get("hobby_templates", {})
    keys = [k for k in pool if not k.startswith("_")] if isinstance(pool, dict) else list(pool)
    if not keys: return []
    return random.sample(keys, min(2, len(keys)))

def _random_orientation():
    r = random.random()
    if r < 0.88: return "heterosexual"
    if r < 0.94: return "homosexual"
    if r < 0.98: return "bisexual"
    return "asexual"

def _random_problems(defs):
    pool = defs.get("problems_registry", [])
    if not pool: return []
    if random.random() < 0.7: return []
    return random.sample(pool, min(1, len(pool)))

def _random_natural_talents(defs):
    pool = defs.get("natural_talents_registry", [])
    if not pool: return []
    return random.sample(pool, min(2, len(pool)))

def _random_hairstyle(defs, sex):
    hs = defs.get("hairstyle_templates", {})
    styles = hs.get("styles", {})
    pool = [k for k, v in styles.items()
            if not k.startswith("_") and (
                v.get("gender") in (sex, "unisex", None)
                or v.get("gender") is None
            )] if isinstance(styles, dict) else []
    if not pool:
        pool = [k for k in styles if not k.startswith("_")] if isinstance(styles, dict) else []
    if not pool: return None
    return random.choice(pool)

def _pick_from_registry(registry, max_picks, skip_chance):
    if not registry or random.random() < skip_chance:
        return []
    return random.sample(registry, min(max_picks, len(registry)))

# Sense-related physical traits (see brain/perception.py's
# SENSE_TRAIT_MODIFIERS). Kept as a small in-code pool rather than a
# definitions.json registry for this first slice — mirrors how
# stance_templates/trait_templates started before being promoted to
# editable JSON. Vision and hearing are rolled independently (a character
# can have both a vision quirk and a hearing quirk, or neither).
_VISION_TRAIT_POOL  = ["poor_eyesight", "keen_eyesight"]
_HEARING_TRAIT_POOL = ["poor_hearing", "keen_hearing"]

def _random_physical_traits(defs):
    constitutional = list(defs.get("physical_trait_templates", {}).keys())
    return (
        _pick_from_registry(_VISION_TRAIT_POOL, 1, 0.75)
        + _pick_from_registry(_HEARING_TRAIT_POOL, 1, 0.75)
        + _pick_from_registry(constitutional, 2, 0.70)
    )

# ── Job assignment ────────────────────────────────────────────────────────────

def _assign_job(defs, age_group, education):
    if age_group == "child":
        return {}
    if age_group == "elderly" and random.random() < 0.60:
        return {"id": "retired", "title": "Retired", "industry": None,
                "average_salary": 0, "hourly_wage": 0, "salary": 0,
                "work_mode": "none", "income_class": "Low"}
    jobs = defs.get("job_templates", {})
    if not jobs: return {}
    my_rank = _EDU_RANK.get(education, 0)
    # Illegal jobs (see systems/crime.py) are deliberately excluded from the
    # normal random hire pool -- nobody starts life as a Crime Boss purely
    # by chance. Entry into crime is an opportunity-driven runtime path
    # (maybe_recruit_into_crime), not something generation hands out.
    candidates = [
        (jid, j) for jid, j in jobs.items()
        if _EDU_RANK.get(j.get("degree_required", "none"), 0) <= my_rank
        and not j.get("illegal")
    ]
    if age_group == "teen":
        candidates = [
            (jid, j) for jid, j in candidates
            if j.get("service_job") or j.get("degree_required") in ("none", "high_school", None)
        ]
    if not candidates: return {}
    jid, job = random.choice(candidates)
    return {
        "id":              jid,
        "title":           job.get("name", jid),
        "industry":        job.get("industry"),
        "income_class":    job.get("income_class"),
        "average_salary":  job.get("average_salary", 0),
        "hourly_wage":     job.get("hourly_wage", 0),
        "salary":          job.get("salary", 0),
        "work_mode":       job.get("work_mode", "On-site"),
        "physical_demand": job.get("physical_demand", 50),
        "social_demand":   job.get("social_demand", 50),
        "hazard_level":    job.get("hazard_level", "Low"),
        "illegal":         job.get("illegal", False),
        "adult_industry":  job.get("adult_industry", False),
    }

def _assign_school(defs, age, age_group):
    schools = defs.get("school_templates", {})
    if not schools: return None
    eligible = [
        k for k, s in schools.items()
        if s.get("min_age", 0) <= age <= s.get("max_age", 99)
    ]
    return random.choice(eligible) if eligible else None

# ── Work history ──────────────────────────────────────────────────────────────

def _build_work_history(defs, age, education, job):
    """
    Generate plausible pre-sim work history for a character.
    Returns (work_history, industry_experience, current_job_start_tick, job_template_id)
    """
    work_history        = []
    industry_experience = {}
    current_job_start_tick = None
    job_template_id        = None

    if age < 18 or not job:
        return work_history, industry_experience, current_job_start_tick, job_template_id

    working_years  = max(0, age - 18)
    remaining_years = working_years
    num_past = min(3, working_years // 4)

    all_jobs = defs.get("job_templates", {})

    for _ in range(int(num_past)):
        if remaining_years <= 1:
            break
        years_at = random.randint(1, max(1, int(remaining_years * 0.6)))
        remaining_years -= years_at
        cand = [
            (k, v) for k, v in all_jobs.items()
            if _EDU_RANK.get(v.get("degree_required", "none"), 0) <= max(0, _EDU_RANK.get(education, 0) - 1)
        ]
        if not cand:
            continue
        pk, pv = random.choice(cand)
        industry = pv.get("industry") or ""
        elapsed  = int(years_at * TICKS_PER_YEAR)
        work_history.append({
            "job_template_id": pk,
            "job_id":          None,
            "company_id":      None,
            "title":           pv.get("name", pk),
            "industry":        industry,
            "start_tick":      None,
            "end_tick":        None,
            "years":           years_at,
            "reason_left":     random.choice(["quit", "laid_off", "career_change"]),
        })
        if industry:
            industry_experience[industry] = industry_experience.get(industry, 0) + elapsed

    # Current job tenure
    current_years = max(0, remaining_years)
    job_id = job.get("id") if isinstance(job, dict) else None
    if job_id:
        job_template_id        = job_id
        current_job_start_tick = -(int(current_years * TICKS_PER_YEAR))
        industry = job.get("industry") or "" if isinstance(job, dict) else ""
        if industry and current_years > 0:
            industry_experience[industry] = (
                industry_experience.get(industry, 0) + int(current_years * TICKS_PER_YEAR)
            )

    return work_history, industry_experience, current_job_start_tick, job_template_id


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_character(defs, overrides=None, world=None):
    """Generate a fully randomised character dict. `world`, when passed by
    a caller that already holds one (editor.py/family.py/baby.py/
    social_sandbox.py all generate inside a world_lock() span), lets the
    starting bank card open a real ledger account (see banking.py) instead
    of just carrying a placeholder account number nothing backs."""
    overrides = overrides or {}

    sex       = overrides.get("sex")       or _random_sex()
    age       = overrides.get("age")       or _random_age(defs)
    age_group = _age_group(age)

    _rand_first, _rand_family = _random_name(defs, sex)
    first_name  = overrides.get("first_name")  or _rand_first
    family_name = overrides.get("family_name") or _rand_family
    full_name   = overrides.get("name") or f"{first_name} {family_name}"
    ssn         = overrides.get("ssn")  or _random_ssn()

    base_models = defs.get("character_base_models", {})
    model = (
        overrides.get("model")
        or base_models.get(sex, {}).get(age_group)
        or f"{sex}_{age_group}_base"
    )

    values          = overrides.get("values")              or _seed_values(defs, overrides.get("parent_values"))
    traits          = overrides.get("traits")             or _random_traits(defs, sex=sex, age=age)
    curiosity       = overrides.get("curiosity")           if overrides.get("curiosity") is not None else _seed_curiosity(traits)
    physical_traits = overrides.get("physical_traits")    or _random_physical_traits(defs)
    hobbies      = overrides.get("hobbies")            or _random_hobbies(defs)
    orientation  = overrides.get("sexual_orientation") or _random_orientation()
    problems     = overrides.get("problems")           or _random_problems(defs)
    nat_talents  = overrides.get("natural_talents")    or _random_natural_talents(defs)
    hairstyle    = overrides.get("current_hairstyle")  or _random_hairstyle(defs, sex)
    education    = overrides.get("education")          or _attained_education(age)
    job          = overrides.get("job")
    if job is None:
        job = _assign_job(defs, age_group, education)
    skills       = overrides.get("skills")             or _random_skills(defs, job)
    current_school = overrides.get("current_school") or (
        _assign_school(defs, age, age_group)
        if age_group in ("child", "teen") or (age_group == "adult" and age < 26)
        else None
    )

    from systems.refurnishing import random_redecorate_threshold_days
    redecorate_threshold_days = random_redecorate_threshold_days()

    from systems.subscriptions import generate_online_profile
    online_profile = generate_online_profile(defs)

    abnormal  = _pick_from_registry(defs.get("abnormal_traits_registry", []), 2, 0.70)
    phobias   = _pick_from_registry(defs.get("phobias_registry",          []), 2, 0.75)
    fetishes  = _pick_from_registry(defs.get("fetishes_registry",         []), 2, 0.80)
    allergies = _pick_from_registry(defs.get("allergies_registry",        []), 2, 0.75)

    if age_group == "child":
        immune_score = random.randint(75, 95)
    elif age_group == "elderly":
        immune_score = random.randint(55, 80)
    else:
        immune_score = random.randint(80, 100)

    cid = overrides.get("id") or f"char_{uuid.uuid4().hex[:8]}"

    # Work history
    has_job = bool(job and job.get("id"))
    if overrides.get("work_history") is not None:
        work_history           = overrides["work_history"]
        industry_experience    = overrides.get("industry_experience", {})
        current_job_start_tick = overrides.get("current_job_start_tick")
        job_template_id        = overrides.get("job_template_id")
    else:
        work_history, industry_experience, current_job_start_tick, job_template_id = (
            _build_work_history(defs, age, education, job if has_job else None)
        )

    # Ensure job_template_id is always set when employed (e.g. teens skipped _build_work_history)
    if has_job and not job_template_id:
        job_template_id = job.get("id")

    # Wealth
    if has_job:
        salary = job.get("average_salary", 0) or 0
        w_lo = max(200, int((salary / 12) * 0.5))
        w_hi = max(w_lo + 1, int((salary / 12) * 3))
        wealth = max(200, random.randint(w_lo, w_hi))
    else:
        wealth = random.randint(200, 800)

    character = {
        # Identity
        "id":           cid,
        "name":         full_name,
        "first_name":   first_name,
        "family_name":  family_name,
        "ssn":          ssn,
        "sex":          sex,
        "age":          age,
        "age_group":    age_group,
        "model":        model,
        "template":     overrides.get("template", f"{sex}_{age_group}"),
        # Position
        "x":        overrides.get("x", 0),
        "y":        overrides.get("y", 0),
        "rotation": 0,
        "facing":   "south",
        # Personality & social
        "values":              values,
        "curiosity":           curiosity,
        "traits":             traits,
        "cleanliness_threshold": cleanliness_threshold_for_traits(traits),
        "redecorate_threshold_days": redecorate_threshold_days,
        "online_profile":     online_profile,
        "phone_data_gb_remaining": 0,
        "physical_traits":    physical_traits,
        "hobbies":            hobbies,
        "sexual_orientation": orientation,
        "gender_identity":    "cisgender",
        "occupation":         job.get("title", "none") if has_job else "none",
        "job":                job,
        "education":          education,
        "skills":             skills,
        "current_school":     current_school,
        "hourly_wage":        job.get("hourly_wage", 0.0) if has_job else 0.0,
        "wealth":             wealth,
        # Employment & work history
        "employed":                has_job,
        "job_searching":           not has_job and age_group not in ("child",),
        "job_template_id":         job_template_id,
        "company_id":              None,
        "current_job_start_tick":  current_job_start_tick,
        "work_history":            work_history,
        "industry_experience":     industry_experience,
        # Body
        "health": {
            "conditions":  [],
            "stress":      0.0,
            "energy":      1.0,
            "hunger":      0.0,
            "hydration":   1.0,
            "hygiene":     1.0,
            "bladder":     0.0,
            "fatigue":     0.0,
            "sick":        False,
        },
        "immune_score":    immune_score,
        "problems":        problems,
        "natural_talents": nat_talents,
        "abnormal_traits": abnormal,
        "phobias":         phobias,
        "fetishes":        fetishes,
        "allergies":       allergies,
        # Appearance
        "appearance": {
            "traits":         [],
            "height":         None,
            "build":          None,
            "hair_color":     None,
            "hair_style":     None,
            "eye_color":      None,
            "clothing_style": None,
        },
        "current_hairstyle": hairstyle,
        # Social
        "relationships":   {},
        "social_models":   {},
        "memories":        [],
        "conversation_memory": [],
        "pending_reflections": [],
        "intentions":      [],
        "activity":        None,
        "activity_queue":  [],
        "suspended_hobby_sessions": [],
        "reaction_queue":     [],
        "reaction_cooldowns": {},
        "animation_reaction": None,
        "item_knowledge":      {},
        "attention": {
            "focus":       None,
            "history":     [],
            "salience":    {},
            "last_update": 0,
        },
        # Legal
        "legal": {
            "status":     "free",
            "jail_until": None,
            "record":     [],
        },
        # Household
        "household_id":  overrides.get("household_id"),
        "home_id":       overrides.get("home_id"),
        # Economy
        "money":         wealth,
        "ses":           0.5,
        "mobility_score": 0,
        "portfolio":     {},
        "watched_stocks": [],
        "last_stock_check": 0,
        "inventory":     [],
        # Clothing
        "equipped": {
            "hat":          None,
            "upper_layer1": None,
            "upper_layer2": None,
            "pants":        None,
            "shoes":        None,
            "gloves":       None,
        },
        # Conflict
        "grievances":              [],
        "social_contract_ids":     [],
        "cold_shoulder_towards":   [],
        "_confrontation_emitted":  [],
        "recent_behavior_tags":    [],
        # Misc
        "job_searching":           not has_job and age_group not in ("child",),
        "look_target":             None,
    }

    # Apply any remaining overrides
    for k, v in overrides.items():
        if k not in ("id","sex","age","name","model","traits","hobbies",
                     "sexual_orientation","problems","natural_talents",
                     "current_hairstyle","education","job","skills",
                     "current_school","work_history","industry_experience",
                     "current_job_start_tick","job_template_id",
                     "x","y","household_id","home_id","template",
                     "worn","starting_inventory"):
            character[k] = v

    # Attractiveness score (age bell-curve + noise, baked in at generation)
    import math as _math
    age_factor = _math.exp(-((age - 27) ** 2) / (2 * 18 ** 2))
    character["attractiveness"] = round(
        max(0.10, min(0.99, random.gauss(0.50, 0.18) * 0.6 + age_factor * 0.4)), 3
    )

    # Physical body features — fertility signals and build
    character["body_features"] = _gen_body_features(character)

    # Weight (kg) — BMI 22 baseline off the height just rolled above, ±jitter
    # (see systems/nutrition.py for the BMI band spectrum this feeds).
    height_m = character["body_features"]["height_cm"] / 100.0
    character["weight_kg"] = round(22.0 * height_m ** 2 * random.uniform(0.85, 1.15), 1)

    # Impulse state — derive self_control + sexism_level from traits
    try:
        from systems.impulse import init_impulse_state
        init_impulse_state(character)
    except Exception:
        pass

    # Exercise personality — mutually exclusive, or none (35% chance of no tag)
    _assign_exercise_personality(character)

    # Attraction profile — libido, quirks, initiation style, etc.
    try:
        from systems.attraction import generate_attraction_profile as _gen_ap
        _gen_ap(character, defs)
    except Exception:
        character.setdefault("attraction_profile", None)

    # Ideal sexual partner profile — desired/undesired traits + physical
    # window, folded into compute_attraction() (see attraction.py).
    try:
        from systems.attraction import generate_ideal_partner as _gen_ideal
        _gen_ideal(character, defs)
    except Exception:
        character.setdefault("ideal_partner", None)

    # Sports team assignment — a "X Supporter"/team-sport hobby among the
    # ones just picked above gets a real pro team or an invented local
    # club (see systems/sports.py). Needs a real world dict (not just
    # defs) since local-team rosters are per-simulation state; skipped
    # when generating outside a live world (e.g. Character Creator preview).
    if world is not None:
        try:
            from systems.sports import sync_sports_hobbies
            sync_sports_hobbies(character, world)
        except Exception:
            pass
        try:
            from systems.crime import sync_gun_hobbies
            sync_gun_hobbies(character, world)
        except Exception:
            pass
        try:
            from systems.diary import sync_diary_hobby
            sync_diary_hobby(character, world)
        except Exception:
            pass

    # Speech/writing quirk (see speech_style_registry) -- most characters
    # have none; a minority talk/write distinctly differently.
    try:
        pool = list(defs.get("speech_style_registry", {}).keys())
        if pool and random.random() < SPEECH_STYLE_CHANCE:
            character["speech_style"] = random.choice(pool)
    except Exception:
        pass

    # Weighted-by-prevalence mental/physical health condition assignment
    # -- both registries already had real content, nothing ever assigned
    # it (see systems/mental_health_gen.py). Runs before the antisocial-
    # personality trait sync below since that sync just reacts to
    # whatever this rolled.
    try:
        from systems.mental_health_gen import assign_all_conditions
        assign_all_conditions(character, defs)
    except Exception:
        pass

    try:
        from systems.sociopathy import sync_antisocial_trait
        sync_antisocial_trait(character)
    except Exception:
        pass

    # Sexual preferences — positions, kinks (adults only)
    if age_group not in ("child", "teen"):
        try:
            _gen_sexual_preferences(character, defs)
        except Exception:
            pass

    # Starting phone — personal_items.py::make_smartphone() existed but
    # was never called from character generation, so no simulation ever
    # actually had a phone in play. Adults and teens get one; weighted
    # toward the budget tier, matching realistic ownership spread.
    if age_group in ("adult", "elderly", "teen"):
        try:
            from systems.personal_items import make_smartphone
            model = random.choices(
                ["smartphone_budget", "smartphone_midrange", "smartphone_premium"],
                weights=[0.55, 0.30, 0.15],
            )[0]
            phone = make_smartphone(owner_id=character["id"], model=model,
                                     world={"definitions": defs})
            character["inventory"].append(phone)
        except Exception:
            pass

    # Starting wallet ($100 cash + ID card, per the banking-round spec) --
    # make_wallet()/make_id_card()/make_bank_card() existed but, like
    # make_smartphone() before the block above, were never called from
    # character generation itself (only a one-off world-seed demo script
    # used them). Every character gets one, unconditionally -- age-gating
    # like the phone block above isn't needed here since even a child
    # plausibly has a wallet with a couple dollars and an ID card.
    try:
        from systems.personal_items import make_wallet, make_id_card, make_bank_card, STARTER_BANKS
        id_card = make_id_card(character["id"], character["name"], owner_id=character["id"])

        # Real account when a live world is available (see this function's
        # docstring) -- balance starts at $0, the $100 starting cash stays
        # in the wallet per the original spec, not auto-deposited. Falls
        # back to make_bank_card()'s own placeholder account_number
        # (uninitialized -- no real ledger entry) when generating without
        # a world, e.g. Character Creator preview/validation contexts.
        bank_name = random.choice(STARTER_BANKS)
        account_number = None
        if world is not None:
            from systems.banking import bank_key_for_name, open_account
            bank_key = bank_key_for_name(bank_name)
            if bank_key:
                account_number = open_account(world, bank_key, character["id"], initial_balance=0.0)
        bank_card = make_bank_card(bank=bank_name, account_number=account_number, owner_id=character["id"])

        wallet = make_wallet(cash=100.0, owner_id=character["id"], contents=[id_card, bank_card])
        character["inventory"].append(wallet)
    except Exception:
        pass

    # Starting worn clothing + carried equipment (Character Creator's
    # Outfit/Equipment tab) — worn is set directly rather than via
    # put_on_clothing (which requires the item to already be in
    # inventory), so recompute_nudity_state must be called explicitly.
    worn_overrides = overrides.get("worn") or {}
    if worn_overrides:
        from systems.clothing import CLOTHING_SLOTS, recompute_nudity_state
        from systems.personal_items import make_item
        worn = {slot: None for slot in CLOTHING_SLOTS}
        for slot, template_id in worn_overrides.items():
            if template_id and slot in CLOTHING_SLOTS:
                try:
                    worn[slot] = make_item(template_id, world={"definitions": defs},
                                            owner_id=character["id"])
                except ValueError:
                    pass
        character["worn"] = worn
        recompute_nudity_state(character)

    for template_id in overrides.get("starting_inventory") or []:
        try:
            from systems.personal_items import make_item
            character["inventory"].append(
                make_item(template_id, world={"definitions": defs}, owner_id=character["id"]))
        except ValueError:
            pass

    # Bio -- no default/generation path existed for a plain generate_character()
    # call before this (only relative-derivation via family.py/relative_gen.py
    # ever set one). Deterministic and grounded in this character's own
    # traits/job/education/hobbies, not an LLM call: generate_character()
    # runs synchronously and is sometimes called while api/editor.py's
    # spawn_character (etc.) holds world_lock() -- a blocking LLM call in
    # that critical section would stall the whole tick loop for however
    # long it takes to respond. Only fills in if overrides didn't already
    # supply one (Character Creator templates can still set a static bio).
    if not character.get("bio"):
        character["bio"] = _fallback_bio_for_character(character)

    return character


def _fallback_bio_for_character(character):
    """Deterministic 1-2 sentence bio grounded in the character's own
    generated data. Mirrors relative_gen.py::_fallback_bio()'s shape but
    for a primary character (no source/relation context to build off)."""
    name = character.get("first_name") or (character.get("name") or "").split(" ")[0] or "They"
    age = character.get("age")
    age_clause = f"{name}, {age}." if age is not None else f"{name}."

    core_traits = {"cognition_logical", "cognition_balanced", "cognition_selfaware"}
    traits = [t for t in character.get("traits", []) if t not in core_traits]
    trait_clause = f"Known for being {traits[0].replace('_', ' ')}." if traits else ""

    job = character.get("job")
    job_title = job.get("title") if isinstance(job, dict) else None
    education = character.get("education")
    if job_title:
        work_clause = f"Works as a {job_title.lower()}."
    elif education and education not in ("none", "none_completed"):
        work_clause = f"Has a background in {education.replace('_', ' ')} education."
    else:
        work_clause = ""

    hobbies = character.get("hobbies") or []
    hobby_clause = f"Spends free time on {hobbies[0].replace('_', ' ')}." if hobbies else ""

    return " ".join(p for p in (age_clause, work_clause, trait_clause, hobby_clause) if p)





def _assign_exercise_personality(c):
    """Assign at most one exercise personality trait."""
    existing = set(c.get("traits", []) + c.get("personality_traits", []))
    EXERCISE_TRAITS = ("exercise_overdoer", "exercise_consistent", "exercise_social_only")
    if any(t in existing for t in EXERCISE_TRAITS):
        return  # already has one

    # 65% chance of having a distinct exercise style
    if random.random() > 0.65:
        return

    # Weights: consistent is most common, social & overdoer less so
    trait = random.choices(
        EXERCISE_TRAITS,
        weights=[0.20, 0.50, 0.30]
    )[0]
    c.setdefault("traits", []).append(trait)

def _gen_body_features(c):
    """
    Assign randomised body features at character generation.
    Female chars get breast_size / hip_ratio / thigh_build (fertility signals).
    All chars get height_cm and build.
    """
    sex = c.get("sex", "male")
    age = c.get("age", 25)

    # Height (cm) — sex-differentiated normal distribution
    if sex == "female":
        height_cm = round(random.gauss(164, 7))
    else:
        height_cm = round(random.gauss(177, 8))
    height_cm = max(140, min(210, height_cm))

    # Build — weighted by age (younger chars slightly more likely to be slim/athletic)
    if age < 30:
        build_weights = {"slim": 0.25, "average": 0.30, "athletic": 0.30, "stocky": 0.10, "heavy": 0.05}
    elif age < 50:
        build_weights = {"slim": 0.15, "average": 0.35, "athletic": 0.20, "stocky": 0.20, "heavy": 0.10}
    else:
        build_weights = {"slim": 0.10, "average": 0.30, "athletic": 0.15, "stocky": 0.25, "heavy": 0.20}
    builds = list(build_weights.keys())
    build  = random.choices(builds, weights=[build_weights[b] for b in builds])[0]

    features = {"height_cm": height_cm, "build": build}

    if sex in ("female", "intersex"):
        features["breast_size"] = random.choices(
            ["small", "medium", "large", "very_large"],
            weights=[0.20, 0.45, 0.25, 0.10]
        )[0]
        features["hip_ratio"] = random.choices(
            ["narrow", "average", "wide", "hourglass"],
            weights=[0.15, 0.40, 0.30, 0.15]
        )[0]
        features["thigh_build"] = random.choices(
            ["slim", "toned", "thick", "full"],
            weights=[0.20, 0.35, 0.30, 0.15]
        )[0]

    return features

def _gen_sexual_preferences(c, defs):
    """Assign random sexual preferences from definitions registries."""
    positions = list(defs.get("positions_registry", {}).keys())
    kinks     = list(defs.get("kinks_registry",     {}).keys())

    # Pick 1-3 liked positions, 0-1 disliked
    liked    = random.sample(positions, min(random.randint(1, 3), len(positions))) if positions else []
    disliked = random.sample([p for p in positions if p not in liked],
                             min(random.randint(0, 1), max(0, len(positions) - len(liked)))) if positions else []

    # Kinks: probability of having any = 0.65; pick 0-3
    all_kinks     = []
    hard_no_kinks = []
    kinks_reg     = defs.get("kinks_registry", {})
    if kinks and random.random() < 0.65:
        num = random.randint(1, min(3, len(kinks)))
        all_kinks = random.sample(kinks, num)
    # Hard-no: a few kinks the character explicitly rejects
    remaining = [k for k in kinks if k not in all_kinks]
    if remaining and random.random() < 0.40:
        hard_no_kinks = random.sample(remaining, min(random.randint(1, 2), len(remaining)))

    c.setdefault("sexual_preferences", {
        "positions_liked":    liked,
        "positions_disliked": disliked,
        "kinks":              all_kinks,
        "kinks_hard_no":      hard_no_kinks,
        "partner_experience": {},
    })
    # ── Celebrity idol (teens and young adults) ────────────────────────────
    age = c.get("age", 30)
    if 10 <= age <= 25:
        try:
            from systems.crushes import add_celebrity_idol
            import random as _r
            celeb_reg = defs.get("celebrity_registry", {})
            if celeb_reg:
                age_approp = [
                    cid for cid, cd in celeb_reg.items()
                    if cd.get("appeal_age_range", [0, 99])[0] <= age
                    <= cd.get("appeal_age_range", [0, 99])[1]
                ]
                if age_approp:
                    chosen_id = _r.choice(age_approp)
                    add_celebrity_idol(c, chosen_id, {"definitions": defs})
        except Exception:
            pass


