"""
systems/standing.py

Who children look up to, and why.

Confidence isn't one number. Each character has a profile across ten
dimensions, DERIVED from data that already exists (traits, attractiveness,
household and parents' jobs, abilities, age) -- nothing here is stored:

    looks, intelligence, social ability, skills, family (name, wealth,
    occupations), intimidation, athletic ability, honor, experience, kindness

plus an eleventh that's computed from the others: companionship, the
confidence of the people you keep company with.

How impressive someone looks depends on who's looking. A small child is
swayed by looks, size and strength, family, and who nobody messes with; an
older child shifts toward social ability, brains and kindness; an adult
weighs honor, kindness and competence. So standing is always "subject, as
seen by observer".

A child's role model is the most impressive person they actually have contact
with who isn't younger than them (older kids count for extra -- they look up).
Role models amplify peer influence on traits and beliefs
(systems/peer_influence.py), and children who share a role model form a group
around them.

Only two things are stored, on c["child_cognition"]: role_model_id (+ what
they're admired for) and felt_bonus, how much confidence they've gained or lost
from wins, ridicule and being unchallenged.

Known data limits: weight, height and the `skills` list are unreliable for
children (the generator gives a 5-year-old adult work skills and an adult
weight), so athletic ability and skill lean on traits and abilities instead.
"""

DIMENSIONS = ("looks", "intelligence", "social", "skills", "family",
              "intimidation", "athletic", "honor", "experience", "kindness")

_BASE = {d: 0.5 for d in DIMENSIONS}
_BASE.update(intimidation=0.2, athletic=0.4)

# trait -> delta, per dimension. Only traits that exist in definitions.json's trait_templates.
_TRAIT_EFFECTS = {
    "intelligence": {"cognition_logical": .15, "wise": .20, "perceptive": .10, "curious": .05,
                     "innovative": .10, "rational": .10, "thoughtful": .05,
                     "gullible": -.10, "naive": -.10, "forgetful": -.05, "careless": -.05},
    "social":       {"charismatic": .25, "cheerful": .10, "polite": .05, "playful": .10, "confident": .10,
                     "tactful": .10, "diplomatic": .10, "cooperative": .05,
                     "rude": -.15, "obnoxious": -.20, "easily_embarrassed": -.15, "nervous": -.10,
                     "low_self_esteem": -.10, "inconsiderate": -.10},
    "intimidation": {"aggressive": .25, "hot_tempered": .15, "cruel": .20, "courageous": .10,
                     "ruthless": .15, "short_tempered": .10, "arrogant": .05, "reckless": .05,
                     "cowardly": -.10, "nervous": -.05},
    "athletic":     {"exercise_consistent": .25, "exercise_overdoer": .20, "exercise_social_only": .10,
                     "adventurous": .10, "courageous": .05, "resilient": .05,
                     "lazy": -.20},
    "honor":        {"honest": .20, "trustworthy": .20, "loyal": .15, "fair": .10, "respectful": .10,
                     "reliable": .10,
                     "deceitful": -.25, "deceptive": -.25, "dishonest": -.25, "manipulative": -.15,
                     "irresponsible": -.10},
    "kindness":     {"compassionate": .25, "empathetic": .25, "generous": .15, "selfless": .20,
                     "supportive": .10, "forgiving": .10,
                     "cruel": -.30, "selfish": -.15, "spiteful": -.15, "inconsiderate": -.10},
}

_ABILITY_LEVEL = {"novice": .20, "beginner": .35, "intermediate": .55, "advanced": .75, "expert": .95}
_INCOME = {"Low": .10, "Lower Middle": .30, "Middle": .50, "Upper Middle": .70, "Upper": .85,
           "High": .90, "Elite": 1.0}

# What each kind of observer is impressed by. Rows sum to 1.0 (companionship is mixed in separately).
_WEIGHTS = {
    "young_child": dict(looks=.15, intimidation=.18, athletic=.17, family=.12, social=.12, skills=.08,
                        intelligence=.05, honor=.03, experience=.05, kindness=.05),
    "older_child": dict(social=.20, looks=.15, athletic=.12, intelligence=.12, skills=.10, family=.10,
                        kindness=.10, honor=.08, intimidation=.08, experience=.05),
    "adult":       dict(honor=.15, kindness=.15, intelligence=.15, skills=.15, experience=.10, social=.10,
                        family=.10, looks=.05, athletic=.03, intimidation=.02),
}
_COMPANIONSHIP_WEIGHT = {"young_child": .04, "older_child": .10, "adult": .06}

# Phrase for what someone is admired for, completing "You look up to X -- ..."
ADMIRED_FOR = {
    "looks":        "they're so good-looking",
    "intelligence": "they're so smart",
    "social":       "everybody likes them",
    "skills":       "they're really good at things",
    "family":       "their family is a big deal",
    "intimidation": "nobody messes with them",
    "athletic":     "they're so fast and strong",
    "honor":        "they always keep their word",
    "experience":   "they've seen and done so much",
    "kindness":     "they're so kind",
}

AGE_GAP_STEP = 0.02      # per year older, when a child is the one looking
AGE_GAP_MIN, AGE_GAP_MAX = -0.10, 0.12

ROLE_MODEL_MIN_SCORE   = 0.50
ROLE_MODEL_SWITCH_EDGE = 0.05    # a challenger must beat the current role model by this much
ROLE_MODEL_INTERVAL    = 600
ROLE_MODEL_AMPLIFIER   = 2.0     # peer_influence source weight when the source IS the role model
FELT_CAP               = 0.4


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _trait_set(c):
    return set(c.get("traits", []) or []) | set(c.get("personality_traits", []) or []) | \
           set(c.get("physical_traits", []) or [])


def _household_adults(c, world):
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    chars = world.get("characters", {})
    return [chars[m] for m in hh.get("members", []) if m in chars
            and chars[m].get("age_group") in ("adult", "elderly")]


def _family_score(c, world):
    """Name and standing of the household: how well off, and what the grown-ups do."""
    if c.get("age_group") in ("adult", "elderly"):
        providers = [c]
    else:
        providers = _household_adults(c, world) or []
    incomes = [_INCOME.get((p.get("job") or {}).get("income_class"), .30) for p in providers] or [.30]
    income = max(incomes)

    authority = 0.0
    if providers:
        from systems.domestic_control import AUTHORITY_JOBS
        for p in providers:
            job = p.get("job") or {}
            if str(job.get("id") or "").lower() in AUTHORITY_JOBS or \
               str(job.get("title") or "").lower().replace(" ", "_") in AUTHORITY_JOBS:
                authority = 1.0
                break

    households = (world.get("households") or {}).values()
    richest = max([(h.get("wealth") or 0) for h in households] or [0])
    mine = ((world.get("households") or {}).get(c.get("household_id")) or {}).get("wealth") or c.get("wealth") or 0
    wealth_rank = (mine / richest) if richest > 0 else 0.5
    return _clamp(0.5 * income + 0.3 * _clamp(wealth_rank) + 0.2 * authority)


def confidence_profile(c, world):
    """{dimension: 0..1} -- what this character brings, before anyone's opinion of it."""
    traits = _trait_set(c)
    prof = dict(_BASE)
    for dim, effects in _TRAIT_EFFECTS.items():
        prof[dim] += sum(delta for trait, delta in effects.items() if trait in traits)

    attractiveness = c.get("attractiveness")
    prof["looks"] = 0.5 if attractiveness is None else attractiveness

    # Social ability also reflects how many people actually like them.
    friends = sum(1 for r in (c.get("relationships") or {}).values() if (r.get("trust") or 0) >= 30)
    prof["social"] += min(0.25, friends * 0.05)

    # Skill: best real ability level. The `skills` list is not used -- it's an adult-work
    # list the generator hands to children too.
    levels = [_ABILITY_LEVEL.get((a or {}).get("level"), .4) for a in (c.get("abilities") or {}).values()]
    prof["skills"] = max(levels) if levels else 0.3

    fat = (c.get("body_composition") or {}).get("body_fat_level")
    if fat is not None and fat < 0.20:
        prof["athletic"] += 0.10

    prof["family"] = _family_score(c, world)
    age = c.get("age")
    prof["experience"] = _clamp((age if age is not None else 25) / 40.0)

    return {d: _clamp(prof[d]) for d in DIMENSIONS}


def _observer_kind(observer):
    age = observer.get("age")
    group = observer.get("age_group")
    if group == "child":
        return "young_child" if (age is not None and age < 8) else "older_child"
    if group == "teen":
        return "older_child"
    return "adult"


def _weighted(profile, kind):
    w = _WEIGHTS[kind]
    return sum(w[d] * profile[d] for d in DIMENSIONS)


def companionship(subject, world, kind="older_child", exclude=()):
    """Confidence by association: the average standing of whoever they keep close company with."""
    chars = world.get("characters", {})
    rels = sorted(((r.get("hours_this_week") or 0.0) + (r.get("trust") or 0.0) / 10.0, oid)
                  for oid, r in (subject.get("relationships") or {}).items()
                  if (r.get("trust") or 0) >= 30 or (r.get("hours_this_week") or 0) >= 10)
    friends = [chars[oid] for _, oid in reversed(rels)
               if oid in chars and oid != subject.get("id") and oid not in exclude][:5]
    if not friends:
        return None
    return sum(_weighted(confidence_profile(f, world), kind) for f in friends) / len(friends)


def standing(subject, observer, world):
    """How impressive `subject` is to `observer`, 0..1."""
    kind = _observer_kind(observer)
    base = _weighted(confidence_profile(subject, world), kind)
    comp = companionship(subject, world, kind, exclude=(observer.get("id"),))
    wc = _COMPANIONSHIP_WEIGHT[kind]
    score = base if comp is None else (1 - wc) * base + wc * comp

    if observer.get("age_group") == "child" and observer.get("age") is not None and subject.get("age") is not None:
        score += max(AGE_GAP_MIN, min(AGE_GAP_MAX, (subject["age"] - observer["age"]) * AGE_GAP_STEP))
    return _clamp(score)


def admired_for(subject, observer, world):
    """Which dimension most explains the admiration: where subject beats observer by the most, weighted by what observer cares about."""
    kind = _observer_kind(observer)
    w = _WEIGHTS[kind]
    sp, op = confidence_profile(subject, world), confidence_profile(observer, world)
    return max(DIMENSIONS, key=lambda d: w[d] * (sp[d] - op[d]))


# ---------------------------------------------------------------------------
# Role models and groups
# ---------------------------------------------------------------------------

def _contact(rel):
    return min(1.0, (rel.get("hours_this_week") or 0.0) / 40.0 + (rel.get("familiarity") or 0.0) / 200.0)


def pick_role_model(child, world):
    """(id, score) of the most impressive person in the child's life who isn't younger than them, or None."""
    chars = world.get("characters", {})
    best = None
    for oid, rel in (child.get("relationships") or {}).items():
        other = chars.get(oid)
        if not other or other.get("alive") is False or oid == child.get("id"):
            continue
        if other.get("is_workplace_npc") or other.get("is_service_worker"):
            continue
        if (rel.get("familiarity") or 0) < 5 and (rel.get("hours_this_week") or 0) <= 0:
            continue
        if other.get("age") is not None and child.get("age") is not None and other["age"] < child["age"]:
            continue   # you don't look up to someone littler than you
        score = standing(other, child, world) * (0.5 + 0.5 * _contact(rel))
        if best is None or score > best[1]:
            best = (oid, score)
    return best if best and best[1] >= ROLE_MODEL_MIN_SCORE else None


def refresh_role_model(child, cog, world):
    """Re-evaluate on a slow cadence; a sitting role model is only displaced by a clearly better one."""
    tick = world.get("tick", 0)
    if tick - cog.get("_last_role_model_tick", -ROLE_MODEL_INTERVAL) < ROLE_MODEL_INTERVAL:
        return
    cog["_last_role_model_tick"] = tick
    chars = world.get("characters", {})
    pick = pick_role_model(child, world)
    current = cog.get("role_model_id")
    if current and current in chars and chars[current].get("alive") is not False:
        cur_rel = (child.get("relationships") or {}).get(current) or {}
        cur_score = standing(chars[current], child, world) * (0.5 + 0.5 * _contact(cur_rel))
        if not pick or pick[0] == current or pick[1] < cur_score + ROLE_MODEL_SWITCH_EDGE:
            pick = (current, cur_score) if cur_score >= ROLE_MODEL_MIN_SCORE else pick
    if pick:
        cog["role_model_id"] = pick[0]
        cog["admired_for"] = admired_for(chars[pick[0]], child, world)
    else:
        cog["role_model_id"] = None
        cog["admired_for"] = None


def role_model_amplifier(observer, source_id):
    """>1 when `source_id` is the observer's role model -- feeds peer_influence's source weight."""
    cog = observer.get("child_cognition") or {}
    return ROLE_MODEL_AMPLIFIER if cog.get("role_model_id") and cog["role_model_id"] == source_id else 1.0


def group_followers(leader_id, world):
    """Children whose role model is `leader_id`."""
    return [c for c in world.get("characters", {}).values()
            if c.get("age_group") == "child"
            and (c.get("child_cognition") or {}).get("role_model_id") == leader_id]


# ---------------------------------------------------------------------------
# Felt confidence
# ---------------------------------------------------------------------------

def felt_confidence(child, world):
    """0..1: how sure of themselves they feel right now. Starts from how they'd rate themselves, then moves with experience."""
    cog = child.get("child_cognition") or {}
    own = standing(child, child, world)
    return _clamp(0.5 + (own - 0.5) * 0.5 + (cog.get("felt_bonus") or 0.0))


def bump_felt(child, delta):
    cog = child.setdefault("child_cognition", {})
    cog["felt_bonus"] = max(-FELT_CAP, min(FELT_CAP, (cog.get("felt_bonus") or 0.0) + delta))


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def get_standing_context(c, world):
    """Sentences about who this child looks up to and how sure of themselves they feel (or [])."""
    chars = world.get("characters", {})
    cog = c.get("child_cognition") or {}
    parts = []

    rm = chars.get(cog.get("role_model_id")) if cog.get("role_model_id") else None
    if rm:
        why = ADMIRED_FOR.get(cog.get("admired_for"), "they seem so grown-up")
        parts.append(f"You look up to {rm.get('name', 'someone')} -- {why}. You want to be like them, "
                     f"and you copy how they act and what they say.")
        if rm.get("age_group") in ("child", "teen"):
            mates = [x.get("name") for x in group_followers(rm["id"], world) if x["id"] != c["id"]]
            parts.append(f"You're part of {rm.get('name')}'s group" + (f", with {', '.join(mates)}." if mates else "."))

    followers = [x.get("name") for x in group_followers(c["id"], world)]
    if followers:
        parts.append(f"{', '.join(followers)} look up to you and follow your lead.")

    felt = felt_confidence(c, world)
    if felt >= 0.70:
        parts.append("You feel confident and sure of yourself.")
    elif felt <= 0.30:
        parts.append("You feel small and unsure of yourself right now.")
    return parts
