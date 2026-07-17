"""
systems/attraction.py

Interpersonal attraction engine.

Each character has an attraction_profile (generated once at character creation)
that encodes their libido, orientation, quirks, and preference weights.

compute_attraction(c, other, world) returns a float 0-1 representing how
attracted c is to other at this moment.  The score feeds into:
  - relationship["attraction"] (persisted, smoothed)
  - initiation willingness in intimacy.py
  - envy/jealousy checks (see check_envy_events)
  - conflict-of-interest flags (romantic rivalry, power-dynamic attraction)

Envy and conflict-of-interest are checked separately:
  check_envy_events(world) — called daily, scans all attracted characters
  check_conflict_of_interest(world) — called daily, flags problematic attractions
"""

import random
import math

from systems.grievances import add_grievance

# ── Libido trait registry ─────────────────────────────────────────────────
# Maps trait name → modifier fields
LIBIDO_TRAITS = {
    "high_libido":        {"libido": +0.35, "arousal_threshold": -0.20, "initiation_bias": +0.3},
    "low_libido":         {"libido": -0.35, "arousal_threshold": +0.25, "initiation_bias": -0.3},
    "promiscuous":        {"libido": +0.20, "emotional_gate":    -0.40, "stage_gate_mod":  -1},
    "flirtatious":        {"libido": +0.10, "initiation_bias":   +0.15},
    "sexually_confident": {"sexual_anxiety": -0.50, "initiation_bias": +0.20, "rejection_resilience": +0.3},
    "sexually_insecure":  {"sexual_anxiety": +0.50, "initiation_bias": -0.30, "rejection_resilience": -0.4},
    "demisexual":         {"requires_trust":  0.70,  "libido":           0.0},
    "romantic":           {"emotional_gate": +0.30, "casual_reluctance": +0.40},
    # Pre-existing personality traits that influence sexuality
    "jealous":            {"envy_sensitivity": +0.50},
    "possessive":         {"envy_sensitivity": +0.40, "partner_monitoring": +0.50},
    "confident":          {"initiation_bias":  +0.10, "rejection_resilience": +0.15},
    "charismatic":        {"initiation_bias":  +0.10},
    "sensitive":          {"emotional_gate":   +0.20},
    "impulsive":          {"initiation_bias":  +0.20, "arousal_threshold": -0.10},
}

# Envy thresholds
ENVY_ATTRACTION_THRESHOLD   = 0.40   # must be this attracted to feel envy
ENVY_GRIEVANCE_SEVERITY     = 8.0    # base grievance severity for romantic envy
STATUS_ENVY_THRESHOLD       = 0.30   # wealth/status gap that triggers status envy
STATUS_ENVY_BASE_SEVERITY   = 5.0
CONFLICT_OF_INTEREST_RATIO  = 1.5    # supervisor/subordinate job_prestige ratio

# Orientation compatibility table
# key: (c_orientation, other_sex)
_COMPAT = {
    ("heterosexual", "male"):   1.0,
    ("heterosexual", "female"): 1.0,
    ("homosexual",   "male"):   1.0,
    ("homosexual",   "female"): 1.0,
    ("bisexual",     "male"):   1.0,
    ("bisexual",     "female"): 1.0,
    ("bisexual",     "other"):  0.8,
    ("heterosexual", "other"):  0.3,
    ("homosexual",   "other"):  0.3,
}

def _orientation_compat(c, other):
    orientation = c.get("sexual_orientation", "heterosexual")
    c_sex    = c.get("sex", "male")
    other_sex = other.get("sex", "male")
    # heterosexual: attracted to opposite sex
    if orientation == "heterosexual":
        return 1.0 if c_sex != other_sex else 0.0
    # homosexual: attracted to same sex
    if orientation == "homosexual":
        return 1.0 if c_sex == other_sex else 0.0
    # bisexual/pansexual: attracted to any
    return _COMPAT.get((orientation, other_sex), 0.7)


# ── Attraction profile ────────────────────────────────────────────────────

def generate_attraction_profile(c, defs):
    """
    Build and store c["attraction_profile"] from traits + a few random
    preference picks.  Call once during character generation.
    """
    traits = set(c.get("traits", []) + c.get("personality_traits", []))

    # Base libido 0-1 (Gaussian around 0.5, clamped)
    libido = max(0.05, min(0.95, random.gauss(0.5, 0.18)))

    arousal_threshold = max(0.10, min(0.90, random.gauss(0.45, 0.15)))
    sexual_anxiety    = max(0.00, min(1.00, random.gauss(0.25, 0.15)))
    emotional_gate    = max(0.00, min(0.80, random.gauss(0.25, 0.15)))
    initiation_bias   = max(-1.0, min(1.0,  random.gauss(0.0,  0.30)))
    envy_sensitivity  = max(0.00, min(1.00, random.gauss(0.30, 0.15)))
    rejection_resilience = max(0.00, min(1.00, random.gauss(0.50, 0.20)))
    requires_trust    = 0.0
    stage_gate_mod    = 0
    partner_monitoring = 0.0
    casual_reluctance = 0.0

    for trait in traits:
        mods = LIBIDO_TRAITS.get(trait, {})
        libido             += mods.get("libido",              0.0)
        arousal_threshold  += mods.get("arousal_threshold",   0.0)
        sexual_anxiety     += mods.get("sexual_anxiety",      0.0)
        emotional_gate     += mods.get("emotional_gate",      0.0)
        initiation_bias    += mods.get("initiation_bias",     0.0)
        envy_sensitivity   += mods.get("envy_sensitivity",    0.0)
        rejection_resilience += mods.get("rejection_resilience", 0.0)
        requires_trust      = max(requires_trust, mods.get("requires_trust", 0.0))
        stage_gate_mod     += mods.get("stage_gate_mod",      0)
        partner_monitoring += mods.get("partner_monitoring",  0.0)
        casual_reluctance  += mods.get("casual_reluctance",   0.0)

    # clamp all
    libido            = max(0.02, min(0.98, libido))
    arousal_threshold = max(0.05, min(0.95, arousal_threshold))
    sexual_anxiety    = max(0.00, min(1.00, sexual_anxiety))
    emotional_gate    = max(0.00, min(0.90, emotional_gate))
    initiation_bias   = max(-1.0, min(1.0,  initiation_bias))
    envy_sensitivity  = max(0.00, min(1.00, envy_sensitivity))
    rejection_resilience = max(0.00, min(1.00, rejection_resilience))
    stage_gate_mod    = max(-2,   min(2,    stage_gate_mod))

    # Initiation style derived from bias + anxiety
    if initiation_bias > 0.3 and sexual_anxiety < 0.4:
        initiation_style = "assertive"
    elif initiation_bias > 0.0 or sexual_anxiety < 0.3:
        initiation_style = "active"
    elif initiation_bias < -0.3 or sexual_anxiety > 0.6:
        initiation_style = "passive"
    else:
        initiation_style = "neutral"

    # Assign 1-3 random attraction quirks from defs
    quirks_pool = list(_quirks_as_dict(defs).keys())
    num_quirks  = random.randint(1, min(3, len(quirks_pool))) if quirks_pool else 0
    quirks      = random.sample(quirks_pool, num_quirks) if num_quirks else []

    # Preference weights
    weights = {
        "appearance":   round(max(0.05, random.gauss(0.35, 0.15)), 2),
        "personality":  round(max(0.10, random.gauss(0.40, 0.15)), 2),
        "status":       round(max(0.00, random.gauss(0.15, 0.10)), 2),
        "familiarity":  round(max(0.05, random.gauss(0.10, 0.05)), 2),
    }
    # normalise weights to sum to 1
    total = sum(weights.values()) or 1.0
    weights = {k: round(v / total, 3) for k, v in weights.items()}

    # ── Party & ONS disposition ──────────────────────────────────────────
    # High self-confidence, no sexual hangups, high libido, low emotional_gate
    # → more likely to seek out parties and engage in casual encounters.
    self_conf   = c.get("self_confidence", 0.60)
    repr_score  = c.get("repression_state", {}).get("repression_score", 0.0)
    sx_shame    = 1 if ("sexually_repressed" in traits or "sexual_shame" in traits) else 0
    # party_disposition: 0=homebody/reserved, 1=social butterfly/hedonist
    party_disposition = (
        self_conf           * 0.35
        + libido            * 0.30
        + initiation_bias   * 0.15   # already 0-1 range needed — map from -1..1
        + (1.0 - emotional_gate) * 0.20
        - repr_score        * 0.40
        - sx_shame          * 0.25
        - sexual_anxiety    * 0.20
    )
    party_disposition = max(0.0, min(1.0, party_disposition))

    # High party_disposition → reduce casual_reluctance (they're comfortable with strangers)
    casual_reluctance = max(0.0, casual_reluctance - party_disposition * 0.45)

    c["attraction_profile"] = {
        "libido":               round(libido, 3),
        "arousal_threshold":    round(arousal_threshold, 3),
        "sexual_anxiety":       round(sexual_anxiety, 3),
        "emotional_gate":       round(emotional_gate, 3),
        "initiation_style":     initiation_style,
        "initiation_bias":      round(initiation_bias, 3),
        "envy_sensitivity":     round(envy_sensitivity, 3),
        "rejection_resilience": round(rejection_resilience, 3),
        "requires_trust":       round(requires_trust, 3),
        "stage_gate_mod":       stage_gate_mod,
        "partner_monitoring":   round(min(1.0, partner_monitoring), 3),
        "casual_reluctance":    round(min(1.0, casual_reluctance), 3),
        "party_disposition":    round(party_disposition, 3),
        "quirks":               quirks,
        "weights":              weights,
    }
    return c["attraction_profile"]


# ── Quirk evaluation ──────────────────────────────────────────────────────

def _quirks_as_dict(defs):
    """Return attraction_quirks_registry as dict keyed by id, regardless of storage format."""
    reg = defs.get("attraction_quirks_registry", {})
    if isinstance(reg, list):
        return {q["id"]: q for q in reg if "id" in q}
    return reg  # already a dict


def _evaluate_quirks(c, other, defs):
    """
    Returns a float modifier (-1 to +1) from c's quirks applied to other.
    Uses condition-string matching against other's fields.
    """
    profile  = c.get("attraction_profile") or {}
    quirks   = profile.get("quirks", [])
    registry = _quirks_as_dict(defs)
    modifier = 0.0

    for qid in quirks:
        q = registry.get(qid, {})
        if not q:
            continue
        boost     = q.get("boost", 0.0)
        condition = q.get("condition", "")
        if _check_quirk_condition(condition, c, other):
            modifier += boost

    return max(-1.0, min(1.0, modifier))


def _check_quirk_condition(condition, c, other):
    """
    Evaluate a condition string against (c, other).
    c is the quirk-holder; other is the target being evaluated.
    """
    if not condition:
        return False

    other_traits = set(other.get("traits", []) + other.get("personality_traits", []))
    other_job    = other.get("job") or {}
    other_age    = other.get("age", 30)
    c_age        = c.get("age", 30)

    if condition == "job_wears_uniform":
        uniform_jobs = {"police", "officer", "military", "nurse", "doctor",
                        "security", "firefighter", "flight attendant", "chef", "guard"}
        title = other_job.get("title", "").lower()
        return any(u in title for u in uniform_jobs)

    elif condition == "high_seniority_job":
        return other_job.get("prestige_level", 1) >= 4

    elif condition == "creative_hobby_or_job":
        creative = {"music", "art", "painting", "photography", "writing", "dance",
                    "acting", "design", "crafts", "poetry"}
        hobbies  = set(h.lower() for h in other.get("hobbies", []))
        title    = other_job.get("title", "").lower()
        return bool(hobbies & creative) or any(c in title for c in creative)

    elif condition == "high_income_class":
        return other.get("wealth", 0) > 50000 or other_job.get("average_salary", 0) > 70000

    elif condition == "illegal_job_or_criminal":
        job_cat  = other_job.get("category", "").lower()
        return "criminal" in job_cat or "illegal" in job_cat or                other.get("legal", {}).get("record", []) != []

    elif condition == "age_10_plus_older":
        return other_age >= c_age + 10

    elif condition == "age_10_plus_younger":
        return other_age <= c_age - 10

    elif condition == "age_15_plus_older":
        return other_age >= c_age + 15

    elif condition == "age_15_plus_younger":
        return other_age <= c_age - 15

    elif condition == "has_tattoos":
        return "tattoos" in other.get("appearance", {}).get("traits", [])

    elif condition == "high_education":
        edu_rank = {"none":0,"elementary":1,"middle_school":2,"high_school":3,
                    "some_college":4,"associate":5,"bachelor":6,"master":7,
                    "doctorate":8,"professional":9}
        return edu_rank.get(other.get("education",""), 0) >= 5

    elif condition == "bachelor_plus_education":
        edu_rank = {"none":0,"elementary":1,"middle_school":2,"high_school":3,
                    "some_college":4,"associate":5,"bachelor":6,"master":7,
                    "doctorate":8,"professional":9}
        return edu_rank.get(other.get("education",""), 0) >= 6

    elif condition == "music_hobby_or_job":
        hobbies = set(h.lower() for h in other.get("hobbies", []))
        title   = other_job.get("title", "").lower()
        return any(m in hobbies or m in title for m in ("music","guitar","piano","singing","drums","violin"))

    elif condition == "athletic_build":
        build = other.get("appearance", {}).get("build") or other.get("body_type", "")
        return build in ("athletic", "muscular", "fit", "toned")

    elif condition == "has_trait_shy":
        return "shy" in other_traits or "nervous" in other_traits or "introverted" in other_traits

    elif condition == "has_trait_aggressive":
        return "aggressive" in other_traits or "hot_tempered" in other_traits

    elif condition == "has_trait_dishonest":
        return "dishonest" in other_traits or "deceitful" in other_traits or "manipulative" in other_traits

    elif condition == "has_trait_clingy":
        return "clingy" in other_traits or "dependent" in other_traits or "obsessive" in other_traits

    elif condition == "has_smoking_problem":
        return "smoking" in (other.get("problems") or [])

    elif condition == "high_odor":
        return other.get("body", {}).get("odor_level", 0.0) > 0.5

    elif condition == "has_trait_funny":
        return "playful" in other_traits or "humorous" in other_traits or "funny" in other_traits

    elif condition == "has_trait_confident":
        return "confident" in other_traits or "sexually_confident" in other_traits

    elif condition == "has_trait_kind":
        return "compassionate" in other_traits or "generous" in other_traits or "kind" in other_traits

    elif condition == "has_trait_arrogant":
        return "arrogant" in other_traits or "egotistical" in other_traits

    # Unknown condition — skip (don't crash)
    return False


def _check_quirk_trigger(trigger, other):
    """Legacy stub — kept for compatibility; logic moved to _check_quirk_condition."""
    return False


# ── Core attraction computation ───────────────────────────────────────────

def compute_attraction(c, other, world):
    """
    Return float 0-1: how attracted character c is to other right now.

    Components:
      1. Orientation gate (hard 0 if incompatible)
      2. Appearance compatibility
      3. Personality/trait resonance
      4. Status differential (if c values status)
      5. Quirk modifiers
      6. Relationship familiarity + trust
      7. Demisexual gate
      8. Current mood/arousal state boost
    """
    if c.get("id") == other.get("id"):
        return 0.0

    # 1. Orientation gate
    compat = _orientation_compat(c, other)
    if compat < 0.05:
        return 0.0

    profile = c.get("attraction_profile") or {}
    defs    = world.get("defs", {})
    weights = profile.get("weights", {"appearance": 0.35, "personality": 0.40,
                                      "status": 0.15, "familiarity": 0.10})

    # 2. Appearance score (uses age, grooming, fitness; rough proxy)
    appearance_score = _appearance_score(c, other)

    # 3. Personality resonance
    personality_score = _personality_resonance(c, other)

    # 4. Status differential
    status_score = _status_score(c, other)

    # 5. Familiarity + trust from existing relationship
    rel = c.get("relationships", {}).get(other["id"], {})
    familiarity = rel.get("familiarity", 0) / 100.0   # 0-1
    trust       = max(0, rel.get("trust", 0)) / 100.0  # 0-1
    familiarity_score = (familiarity * 0.6 + trust * 0.4)

    # Weighted base score
    base = (
        appearance_score   * weights.get("appearance",  0.35) +
        personality_score  * weights.get("personality", 0.40) +
        status_score       * weights.get("status",      0.15) +
        familiarity_score  * weights.get("familiarity", 0.10)
    )

    # 6. Quirk modifier
    quirk_mod = _evaluate_quirks(c, other, defs)
    base = max(0.0, min(1.0, base + quirk_mod * 0.3))

    # 7. Demisexual gate — requires strong trust bond
    requires_trust = profile.get("requires_trust", 0.0)
    if requires_trust > 0 and trust < requires_trust:
        # scale down attraction strongly until trust threshold
        base *= (trust / requires_trust) ** 2

    # 8. Orientation compatibility scale
    base *= compat

    # 9. Current arousal boost (if already aroused, things look better)
    arousal = c.get("arousal_level", 0.0)
    if arousal > 0.3:
        base = min(1.0, base + arousal * 0.1)

    return round(max(0.0, min(1.0, base)), 4)


# ── Fertility appeal — common-knowledge signal ───────────────────────────
# Men (and most characters) read fertility cues the same way: larger breasts,
# wider hips, fuller thighs signal reproductive health.  This is treated as
# publicly legible — every character "understands" the signal even if they don't
# act on it (orientation gating happens later in compute_attraction).

BREAST_SCORES  = {"small": 0.35, "medium": 0.55, "large": 0.80, "very_large": 0.95}
HIP_SCORES     = {"narrow": 0.30, "average": 0.50, "wide": 0.75, "hourglass": 0.95}
THIGH_SCORES   = {"slim": 0.40, "toned": 0.65, "thick": 0.80, "full": 0.90}


def compute_fertility_appeal(other):
    """
    Returns 0-1 fertility-signal score based on other's body_features.
    Only meaningful for female or intersex characters; returns 0.50 (neutral)
    for male characters without female features.
    """
    sex = other.get("sex", "male")
    if sex not in ("female", "intersex"):
        return 0.50   # neutral — no female fertility signals

    bf = other.get("body_features", {})
    breast = BREAST_SCORES.get(bf.get("breast_size", "medium"),  0.55)
    hips   = HIP_SCORES.get(   bf.get("hip_ratio",   "average"), 0.50)
    thighs = THIGH_SCORES.get( bf.get("thigh_build",  "toned"),  0.65)

    # Simple weighted average — all three signals matter equally
    return round((breast + hips + thighs) / 3.0, 4)


def _appearance_score(c, other):
    """
    Appearance score that c assigns to other.
    Incorporates:
      - base attractiveness (baked in at character gen)
      - age bell-curve
      - hygiene penalty
      - fertility appeal (breast/hip/thigh) — weighted heavily for
        heterosexual male attractors and lesbian female attractors
    """
    age = other.get("age", 30)
    age_factor = math.exp(-((age - 27) ** 2) / (2 * 15 ** 2))

    odor = other.get("body", {}).get("odor_level", 0.0)
    hygiene_penalty = odor * 0.4

    base_attractiveness = other.get("attractiveness", random.gauss(0.5, 0.15))
    base_attractiveness = max(0.0, min(1.0, base_attractiveness))

    # Fertility signal weight — high for hetero male / lesbian female attractors
    c_sex  = c.get("sex", "male")
    c_ori  = c.get("sexual_orientation", "heterosexual")
    other_sex = other.get("sex", "female")

    fertility_weight = 0.0
    if other_sex in ("female", "intersex"):
        if (c_sex == "male"   and c_ori in ("heterosexual", "bisexual")) or            (c_sex == "female" and c_ori in ("homosexual",  "bisexual")):
            fertility_weight = 0.30   # fertility signals carry significant weight

    fertility = compute_fertility_appeal(other) if fertility_weight > 0 else 0.0

    # Allocate weights: base + age + fertility must sum to 1 before penalty
    base_w = 0.55 - fertility_weight * 0.30   # shrinks to give room to fertility
    age_w  = 0.45 - fertility_weight * 0.70   # age matters less when fertility matters
    base_w = max(0.20, base_w)
    age_w  = max(0.15, age_w)
    total  = base_w + age_w + fertility_weight
    base_w /= total; age_w /= total; fertility_weight /= total

    # Fitness bonus — baked in by exercise system, pre-computed
    fitness_bonus = other.get("fitness_attractiveness_bonus", 0.0)

    # Body-fat penalty (systems/body_composition.py) — both extremes count
    # against appearance a little; a neutral band around the middle is
    # penalty-free, same "small additive term" shape as fitness_bonus above.
    BODY_FAT_NEUTRAL   = 0.40
    BODY_FAT_TOLERANCE = 0.15
    body_fat = other.get("body_composition", {}).get("body_fat_level", 0.35)
    body_fat_excess = max(0.0, abs(body_fat - BODY_FAT_NEUTRAL) - BODY_FAT_TOLERANCE)
    body_fat_penalty = min(0.15, body_fat_excess * 0.5)

    score = (base_attractiveness * base_w
             + age_factor        * age_w
             + fertility         * fertility_weight
             + fitness_bonus
             - hygiene_penalty
             - body_fat_penalty)
    return max(0.0, min(1.0, score))


def _personality_resonance(c, other):
    """
    Score based on trait compatibility.
    Complementary and matching traits both contribute.
    """
    c_traits     = set(c.get("traits", []) + c.get("personality_traits", []))
    other_traits = set(other.get("traits", []) + other.get("personality_traits", []))

    if not c_traits or not other_traits:
        return 0.5  # neutral if no data

    # Shared positive traits → resonance
    POSITIVE = {"honest", "loyal", "compassionate", "generous", "patient",
                "courageous", "creative", "optimistic", "charismatic", "confident",
                "playful", "adventurous", "romantic", "disciplined"}
    shared_positive = len(c_traits & other_traits & POSITIVE)

    # Trait repulsion: some trait combos clash
    REPELS = {
        ("honest",      "deceitful"),
        ("loyal",       "promiscuous"),
        ("calm",        "aggressive"),
        ("compassionate", "cruel"),
        ("generous",    "selfish"),
    }
    repulsion = sum(1 for (a, b) in REPELS
                    if (a in c_traits and b in other_traits) or
                       (b in c_traits and a in other_traits))

    score = 0.5 + shared_positive * 0.05 - repulsion * 0.08
    return max(0.0, min(1.0, score))


def _status_score(c, other):
    """How much c is impressed by other's status/wealth/job prestige."""
    # Use wealth as proxy for status
    c_wealth     = c.get("wealth", 1000.0) or 1.0
    other_wealth = other.get("wealth", 1000.0) or 1.0
    ratio = other_wealth / max(c_wealth, 1.0)
    # Slight attraction toward higher-status; too high a gap is intimidating
    if ratio > 5:
        score = 0.6   # very wealthy — impressive but maybe out of reach
    elif ratio > 2:
        score = 0.7   # notably wealthier
    elif ratio > 0.5:
        score = 0.5   # similar — neutral
    else:
        score = 0.35  # c is notably wealthier — slight reduction (less challenge)
    return score


# ── Smooth update of relationship.attraction ─────────────────────────────

def update_relationship_attraction(c, other, world, alpha=0.05):
    """
    Smooth-update c's relationship[other_id]["attraction"] toward the
    computed attraction score.  Call periodically (e.g. after interactions).
    alpha controls update speed (0.05 = slow drift).
    """
    from brain.relationships import ensure_relationship
    rel   = ensure_relationship(c, other["id"])
    score = compute_attraction(c, other, world)
    current = rel.get("attraction", 0.0)
    rel["attraction"] = round(current + alpha * (score * 100 - current), 3)


# ── Envy event detection ──────────────────────────────────────────────────

def check_envy_events(world):
    """
    Daily pass: detect envy-generating situations and add grievances.

    Types detected:
      1. Romantic envy — A attracted to B, but B is intimate/partnered with C → A envies C
      2. Partner jealousy — A is partnered with B, B shows interest in C → A envies C
      3. Status envy — A's wealth/reputation significantly below neighbor B's
    """
    chars = {c["id"]: c for c in world.get("characters", {}).values() if not c.get("is_offscreen")}

    # Build intimacy map: who is "taken" and by whom
    # We look at relationship labels for "partner", "spouse", intimate stages
    partner_map = {}   # char_id → partner_id
    for cid, c in chars.items():
        for oid, rel in c.get("relationships", {}).items():
            if oid not in chars:
                continue
            labels = rel.get("labels", [])
            intimacy_stage = rel.get("intimacy_stage", 0)
            if "partner" in labels or "spouse" in labels or intimacy_stage >= 4:
                if cid not in partner_map:
                    partner_map[cid] = oid

    # 1. Romantic envy
    for cid, c in chars.items():
        profile = c.get("attraction_profile") or {}
        envy_sens = profile.get("envy_sensitivity", 0.3)

        for oid, rel in c.get("relationships", {}).items():
            if oid not in chars:
                continue
            attraction_score = rel.get("attraction", 0) / 100.0
            if attraction_score < ENVY_ATTRACTION_THRESHOLD:
                continue

            # Is the object of attraction partnered with someone else?
            rival_id = partner_map.get(oid)
            if rival_id and rival_id != cid:
                # A (cid) is attracted to B (oid) who is with C (rival_id)
                severity = ENVY_GRIEVANCE_SEVERITY * envy_sens * attraction_score
                if severity > 1.5:
                    add_grievance(
                        c, rival_id,
                        "romantic_envy",
                        world,
                        severity=round(severity, 2),
                        details={
                            "attraction_target": oid,
                            "rival": rival_id,
                        }
                    )
                    # Also nudge rivalry in the relationship
                    rival_rel = c.get("relationships", {}).get(rival_id, {})
                    rival_rel["rivalry"] = min(100, rival_rel.get("rivalry", 0) + severity * 0.5)

    # 2. Partner jealousy — possessive/jealous traits watch their partner
    for cid, c in chars.items():
        profile = c.get("attraction_profile") or {}
        if profile.get("partner_monitoring", 0) < 0.2:
            continue  # not the jealous type
        partner_id = partner_map.get(cid)
        if not partner_id or partner_id not in chars:
            continue
        partner = chars[partner_id]

        # Check if partner shows attraction to a third party
        for oid, prel in partner.get("relationships", {}).items():
            if oid == cid or oid not in chars:
                continue
            partner_attraction = prel.get("attraction", 0) / 100.0
            if partner_attraction > 0.35:
                severity = 7.0 * profile["partner_monitoring"] * partner_attraction
                if severity > 1.0:
                    add_grievance(
                        c, oid,
                        "partner_jealousy",
                        world,
                        severity=round(severity, 2),
                        details={"partner": partner_id, "perceived_rival": oid}
                    )

    # 3. Status envy
    _check_status_envy(world, chars)


def _check_status_envy(world, chars):
    """Status/wealth envy between coworkers and neighbors."""
    # Group by household neighborhood + workplace
    envy_traits = {"jealous", "materialistic", "ambitious", "greedy"}

    for cid, c in chars.items():
        c_traits = set(c.get("traits", []) + c.get("personality_traits", []))
        if not (c_traits & envy_traits):
            continue  # only envious types feel status envy

        c_wealth = c.get("wealth", 1000.0) or 1.0
        c_rep    = c.get("reputation", {}).get("global", 0.5)

        # Check coworkers + housemates (use workplace and household_id)
        candidate_ids = set()
        hid = c.get("household_id")
        if hid:
            for oc in chars.values():
                if oc.get("household_id") == hid and oc["id"] != cid:
                    candidate_ids.add(oc["id"])
        wid = (c.get("job") or {}).get("company_id")
        if wid:
            for oc in chars.values():
                if (oc.get("job") or {}).get("company_id") == wid and oc["id"] != cid:
                    candidate_ids.add(oc["id"])

        for oid in candidate_ids:
            other = chars[oid]
            o_wealth = other.get("wealth", 1000.0) or 1.0
            o_rep    = other.get("reputation", {}).get("global", 0.5)
            wealth_gap = (o_wealth - c_wealth) / max(c_wealth, 1.0)
            rep_gap    = o_rep - c_rep

            if wealth_gap > STATUS_ENVY_THRESHOLD or rep_gap > 0.2:
                severity = STATUS_ENVY_BASE_SEVERITY * max(wealth_gap, rep_gap * 2.0)
                # Ambitious characters feel this more acutely
                if "ambitious" in c_traits:
                    severity *= 1.3
                if "greedy" in c_traits or "materialistic" in c_traits:
                    severity *= 1.2
                add_grievance(
                    c, oid,
                    "status_envy",
                    world,
                    severity=round(min(severity, 12.0), 2),
                    details={"wealth_gap": round(wealth_gap, 2), "rep_gap": round(rep_gap, 2)}
                )


# ── Conflict-of-interest detection ───────────────────────────────────────

def check_conflict_of_interest(world):
    """
    Daily pass: flag attraction situations that create professional or
    social conflicts.  Results stored as relationship flags, not grievances,
    since they aren't yet wrongs — just structural tensions.

    Cases:
      - Power dynamic: supervisor attracted to subordinate
      - Romantic rivalry: two people attracted to the same person
      - Loyalty conflict: attracted to a friend's partner
    """
    chars = {c["id"]: c for c in world.get("characters", {}).values() if not c.get("is_offscreen")}
    company_jobs = {}  # company_id → list of (char_id, job_prestige)
    for cid, c in chars.items():
        job = c.get("job") or {}
        comp_id = job.get("company_id")
        if comp_id:
            company_jobs.setdefault(comp_id, []).append(
                (cid, job.get("prestige_level", 1))
            )

    # 1. Power-dynamic attraction (supervisor → subordinate or vice versa)
    for comp_id, workers in company_jobs.items():
        for i, (aid, aprestige) in enumerate(workers):
            for bid, bprestige in workers[i+1:]:
                if abs(aprestige - bprestige) < 2:
                    continue  # similar level, no power dynamic
                sup_id, sub_id = (aid, bid) if aprestige > bprestige else (bid, aid)
                sup_c = chars.get(sup_id)
                sub_c = chars.get(sub_id)
                if not sup_c or not sub_c:
                    continue
                sup_attraction = sup_c.get("relationships", {}).get(sub_id, {}).get("attraction", 0)
                sub_attraction = sub_c.get("relationships", {}).get(sup_id, {}).get("attraction", 0)
                if max(sup_attraction, sub_attraction) > 40:
                    # Flag in relationship
                    sup_rel = sup_c.setdefault("relationships", {}).setdefault(sub_id, {})
                    sup_rel.setdefault("conflict_flags", [])
                    if "power_dynamic_attraction" not in sup_rel["conflict_flags"]:
                        sup_rel["conflict_flags"].append("power_dynamic_attraction")

    # 2. Romantic rivalry — two chars both attracted to same third party
    attraction_targets = {}  # target_id → list of attracted chars
    for cid, c in chars.items():
        for oid, rel in c.get("relationships", {}).items():
            if oid not in chars:
                continue
            if rel.get("attraction", 0) > 40:
                attraction_targets.setdefault(oid, []).append(cid)

    for target_id, admirers in attraction_targets.items():
        if len(admirers) < 2:
            continue
        for i, a1 in enumerate(admirers):
            for a2 in admirers[i+1:]:
                c1, c2 = chars.get(a1), chars.get(a2)
                if not c1 or not c2:
                    continue
                rel12 = c1.setdefault("relationships", {}).setdefault(a2, {})
                rel12.setdefault("conflict_flags", [])
                if "romantic_rivalry" not in rel12["conflict_flags"]:
                    rel12["conflict_flags"].append("romantic_rivalry")

    # 3. Loyalty conflict — attracted to a friend's partner
    # friend map
    friends = {}
    for cid, c in chars.items():
        for oid, rel in c.get("relationships", {}).items():
            if rel.get("state") in ("friend", "close_friend") and oid in chars:
                friends.setdefault(cid, set()).add(oid)

    partner_map = {}
    for cid, c in chars.items():
        for oid, rel in c.get("relationships", {}).items():
            if oid in chars and ("partner" in rel.get("labels", []) or
                                  rel.get("intimacy_stage", 0) >= 4):
                if cid not in partner_map:
                    partner_map[cid] = oid

    for cid, c in chars.items():
        for fid in friends.get(cid, set()):
            fp = partner_map.get(fid)
            if not fp or fp == cid:
                continue
            attraction_to_fp = c.get("relationships", {}).get(fp, {}).get("attraction", 0)
            if attraction_to_fp > 35:
                rel_to_fp = c.setdefault("relationships", {}).setdefault(fp, {})
                rel_to_fp.setdefault("conflict_flags", [])
                if "loyalty_conflict" not in rel_to_fp["conflict_flags"]:
                    rel_to_fp["conflict_flags"].append("loyalty_conflict")


# ── Context helper ────────────────────────────────────────────────────────

def get_attraction_context(c, world):
    """
    Return a dict summarising c's attraction state for LLM context.
    Does NOT include explicit act details — just drive, style, feelings.
    """
    profile = c.get("attraction_profile") or {}
    chars   = {x["id"]: x for x in world.get("characters", {}).values()}

    # Find who c is most attracted to
    top_attractions = []
    for oid, rel in c.get("relationships", {}).items():
        attr = rel.get("attraction", 0)
        if attr > 25 and oid in chars:
            top_attractions.append((oid, attr, rel.get("conflict_flags", [])))
    top_attractions.sort(key=lambda x: -x[1])

    lines = []
    if profile:
        lib  = profile.get("libido", 0.5)
        style = profile.get("initiation_style", "neutral")
        anxiety = profile.get("sexual_anxiety", 0.25)
        pd  = profile.get("party_disposition", 0.3)
        cr  = profile.get("casual_reluctance", 0.0)
        lines.append(f"libido={'high' if lib > 0.65 else 'low' if lib < 0.35 else 'moderate'}, "
                     f"initiation_style={style}, "
                     f"sexual_anxiety={'high' if anxiety > 0.55 else 'low' if anxiety < 0.20 else 'moderate'}")
        if pd >= 0.55:
            lines.append(
                f"party_disposition={pd:.2f}: enjoys going out, socialising, and is open to "
                f"casual encounters with new people (casual_reluctance={cr:.2f})."
            )
        elif pd <= 0.25:
            lines.append(
                f"party_disposition={pd:.2f}: prefers staying in; uncomfortable with or "
                f"uninterested in casual sexual encounters."
            )

    for oid, score, flags in top_attractions[:3]:
        name = chars[oid].get("name", oid)
        pct  = int(score)
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"attracted_to={name} ({pct}/100){flag_str}")

    return {"attraction": lines} if lines else {}
