"""
character_gen.py — procedural character generation.
Entry point: generate_character(defs, overrides={}) -> dict
"""
import random
import uuid

TICKS_PER_YEAR = 365 * 24  # ~8760 ticks per simulated year

# ── Education rank (ascending) ────────────────────────────────────────────────
_EDU_RANK = {
    "none":           0,
    "elementary":     1,
    "middle_school":  2,
    "high_school":    3,
    "some_college":   4,
    "associate":      5,
    "bachelor":       6,
    "master":         7,
    "doctorate":      8,
    "professional":   9,
}

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

def _attained_education(age):
    if age < 10:  return "elementary"
    if age < 13:  return "middle_school"
    if age < 18:  return "high_school"
    r = random.random()
    if r < 0.10:  return "high_school"
    if r < 0.22:  return "some_college"
    if r < 0.34:  return "associate"
    if r < 0.65:  return "bachelor"
    if r < 0.80:  return "some_college"
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

def _random_traits(defs):
    pool = defs.get("trait_templates", {})
    keys = [k for k in pool if not k.startswith("_")] if isinstance(pool, dict) else list(pool)
    if not keys: return []
    return random.sample(keys, min(3, len(keys)))

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
    candidates = [
        (jid, j) for jid, j in jobs.items()
        if _EDU_RANK.get(j.get("degree_required", "none"), 0) <= my_rank
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

def generate_character(defs, overrides=None):
    """Generate a fully randomised character dict."""
    overrides = overrides or {}

    sex       = overrides.get("sex")       or _random_sex()
    age       = overrides.get("age")       or _random_age(defs)
    age_group = _age_group(age)

    first_name, family_name = _random_name(defs, sex)
    full_name = overrides.get("name") or f"{first_name} {family_name}"

    base_models = defs.get("character_base_models", {})
    model = (
        overrides.get("model")
        or base_models.get(sex, {}).get(age_group)
        or f"{sex}_{age_group}_base"
    )

    traits       = overrides.get("traits")             or _random_traits(defs)
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
        "traits":             traits,
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
            "pain":        0.0,
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
        "recent_perception_memory": [],
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
                     "x","y","household_id","home_id","template"):
            character[k] = v

    # Attractiveness score (age bell-curve + noise, baked in at generation)
    import math as _math
    age_factor = _math.exp(-((age - 27) ** 2) / (2 * 18 ** 2))
    character["attractiveness"] = round(
        max(0.10, min(0.99, random.gauss(0.50, 0.18) * 0.6 + age_factor * 0.4)), 3
    )

    # Physical body features — fertility signals and build
    character["body_features"] = _gen_body_features(character)

    # Attraction profile — libido, quirks, initiation style, etc.
    try:
        from systems.attraction import generate_attraction_profile as _gen_ap
        _gen_ap(character, defs)
    except Exception:
        character.setdefault("attraction_profile", None)

    # Sexual preferences — positions, kinks (adults only)
    if age_group not in ("child", "teen"):
        try:
            _gen_sexual_preferences(character, defs)
        except Exception:
            pass

    return character




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
