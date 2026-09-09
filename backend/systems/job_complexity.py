"""
systems/job_complexity.py

The real, populated 577-entry job_templates registry has `degree_required`
data that's effectively random with respect to the actual job -- e.g.
`surgeon.degree_required == "high_school"`, `cashier.degree_required ==
"bachelor"`, `teacher.degree_required == "none"` (confirmed via a full
scan). `income_class`/`average_salary`/`hourly_wage` are equally
unreliable as complexity signals for the same reason (`cashier.
average_salary == 133000`, `surgeon.average_salary == 32000`) -- they
can't be used to DERIVE a corrected degree_required, they're just as
wrong. So this classifies off the one thing that's actually meaningful
and consistent across all 577 entries: the job's own name/title, which
follows a systematic "Senior X" / "Lead X" / "Lead Senior X" naming
pattern over a few hundred distinct base occupations.

classify_job() is deterministic (no LLM, no randomness) and run ONCE as
a content-migration pass over definitions.json (see
scripts/fix_job_qualifications.py) -- not recomputed at hiring time.
Returns (complexity_tier, degree_required):

  tier 1 -- no real prerequisite (cashier, laborer, dishwasher, ...)
  tier 2 -- trade/certificate/associate-level training (electrician,
            registered nurse, police officer, ...)
  tier 3 -- bachelor's/master's professional work (engineer, teacher,
            accountant, architect, ...)
  tier 4 -- doctorate/professional-license work (surgeon, physician,
            lawyer, judge, ...) -- the tier that gets the full
            interview-plus-references pipeline (see jobs.py).

Tier also drives DEGREE_RANK's ordering directly -- higher tier implies
at least that tier's typical degree_required floor, so a corrected
degree_required and a corrected tier can never disagree with each
other.
"""

# Single source of truth for education-rank ordering -- character_gen.py
# and jobs.py both used to keep their own hand-duplicated copy of this
# exact table ("kept in sync only by a comment"); both now import
# DEGREE_RANK from here instead. Same tie structure as those original
# tables (certificate/trade_school tie, professional/doctorate tie) --
# real-world these are comparable qualification tiers, and preserving
# the tie avoids a behavior change for the existing degree_required
# comparisons that already relied on it.
DEGREE_RANK = {
    "none": 0, "none_completed": 0, "preschool": 0, "primary": 0,
    "middle_school": 0, "high_school": 1, "trade_school": 2, "certificate": 2,
    "associate": 3, "bachelor": 4, "master": 5, "doctorate": 6, "professional": 6,
}

_MIN_TIER_DEGREE_FLOOR = {
    1: "none",
    2: "certificate",
    3: "bachelor",
    4: "professional",
}

# Checked in order, first substring match (against the lowercased,
# Senior-/Lead-stripped title) wins -- ordered most-specific first so
# e.g. "nurse practitioner" matches before the generic "nurse" fallback
# further down. (degree_required, tier).
_KEYWORD_RULES = [
    # -- Tier 4: doctorate / licensed-professional work --
    ("nurse practitioner", "master", 3),
    ("physician assistant", "master", 3),
    ("family physician", "doctorate", 4),
    ("physician", "doctorate", 4),
    ("surgeon", "doctorate", 4),
    ("anesthesiologist", "doctorate", 4),
    ("cardiologist", "doctorate", 4),
    ("neurologist", "doctorate", 4),
    ("psychiatrist", "doctorate", 4),
    ("radiologist", "doctorate", 4),
    ("orthodontist", "doctorate", 4),
    ("dentist", "doctorate", 4),
    ("veterinarian", "doctorate", 4),
    ("judge", "professional", 4),
    ("prosecutor", "professional", 4),
    ("public defender", "professional", 4),
    ("attorney", "professional", 4),
    ("lawyer", "professional", 4),
    ("pharmacist", "doctorate", 3),
    ("school psychologist", "doctorate", 3),
    ("psychologist", "doctorate", 3),
    ("professor", "doctorate", 3),
    ("dean", "doctorate", 3),

    # -- Tier 3: bachelor's/master's professional --
    ("data scientist", "master", 3),
    ("engineering manager", "master", 3),
    ("software architect", "master", 3),
    ("hospital administrator", "bachelor", 3),
    ("diplomat", "master", 3),
    ("cfo", "master", 3),
    ("controller", "master", 3),
    ("portfolio manager", "bachelor", 3),
    ("actuary", "bachelor", 3),
    ("architect", "bachelor", 3),
    ("engineer", "bachelor", 3),  # AI/Cloud/Civil/Industrial/Process/Rail Engineer, ...
    ("scientist", "bachelor", 3),
    ("developer", "bachelor", 3),
    ("scrum master", "bachelor", 3),
    ("product manager", "bachelor", 3),
    ("city planner", "master", 3),
    ("construction manager", "bachelor", 3),
    ("factory manager", "bachelor", 3),
    ("plant manager", "bachelor", 3),
    ("resort manager", "bachelor", 3),
    ("hotel manager", "bachelor", 3),
    ("regional manager", "bachelor", 3),
    ("operations manager", "bachelor", 3),
    ("fleet manager", "bachelor", 3),
    ("mayor", "bachelor", 3),
    ("legislator", "bachelor", 3),
    ("teacher", "bachelor", 3),
    ("lecturer", "master", 3),
    ("principal", "master", 3),
    ("librarian", "master", 3),
    ("curriculum developer", "master", 3),
    ("education administrator", "master", 3),
    ("vocational instructor", "trade_school", 2),
    ("substitute teacher", "bachelor", 2),
    ("teaching assistant", "high_school", 1),
    ("preschool teacher", "associate", 2),
    ("daycare worker", "certificate", 1),
    ("tutor", "bachelor", 2),
    ("accountant", "bachelor", 3),
    ("auditor", "bachelor", 3),
    ("financial analyst", "bachelor", 3),
    ("financial planner", "bachelor", 3),
    ("investment analyst", "bachelor", 3),
    ("credit analyst", "bachelor", 2),
    ("risk analyst", "bachelor", 3),
    ("treasury analyst", "bachelor", 2),
    ("procurement analyst", "bachelor", 2),
    ("supply chain analyst", "bachelor", 2),
    ("policy analyst", "bachelor", 3),
    ("tax specialist", "bachelor", 2),
    ("tax inspector", "bachelor", 2),
    ("branch manager", "bachelor", 2),
    ("compliance officer", "bachelor", 2),
    ("trader", "bachelor", 3),
    ("detective", "bachelor", 2),
    ("social worker", "bachelor", 2),
    ("public health inspector", "bachelor", 2),
    ("emergency manager", "bachelor", 2),
    ("technical writer", "bachelor", 2),
    ("database administrator", "bachelor", 2),
    ("network engineer", "bachelor", 2),
    ("cybersecurity analyst", "bachelor", 2),
    ("private investigator", "certificate", 2),

    # -- Tier 2: trade / certificate / associate-level training --
    ("registered nurse", "associate", 2),
    ("licensed practical nurse", "certificate", 2),
    ("nursing assistant", "certificate", 1),
    ("nurse", "associate", 2),  # ER/ICU/Pediatric Nurse fallback
    ("emt", "certificate", 2),
    ("paramedic", "certificate", 2),
    ("lab technician", "associate", 2),
    ("medical assistant", "certificate", 1),
    ("medical receptionist", "high_school", 1),
    ("police officer", "certificate", 2),
    ("corrections officer", "certificate", 1),
    ("firefighter", "certificate", 2),
    ("border patrol", "certificate", 2),
    ("customs officer", "certificate", 2),
    ("park ranger", "associate", 1),
    ("building inspector", "certificate", 2),
    ("election official", "high_school", 1),
    ("water treatment operator", "certificate", 1),
    ("administrative clerk", "high_school", 1),
    ("electrician", "trade_school", 2),
    ("plumber", "trade_school", 2),
    ("hvac technician", "trade_school", 2),
    ("crane operator", "certificate", 1),
    ("heavy equipment operator", "certificate", 1),
    ("glazier", "trade_school", 1),
    ("tile setter", "trade_school", 1),
    ("steel worker", "trade_school", 1),
    ("tool and die maker", "trade_school", 2),
    ("machinist", "trade_school", 2),
    ("industrial electrician", "trade_school", 2),
    ("maintenance technician", "trade_school", 1),
    ("aircraft mechanic", "trade_school", 2),
    ("rail engineer", "trade_school", 2),
    ("harbor pilot", "certificate", 3),
    ("ship captain", "certificate", 3),
    ("airline captain", "bachelor", 3),
    ("airline pilot", "bachelor", 3),
    ("train conductor", "certificate", 1),
    ("truck driver", "certificate", 1),
    ("taxi driver", "certificate", 1),
    ("bus driver", "certificate", 1),
    ("dispatcher", "high_school", 1),
    ("freight broker", "certificate", 1),
    ("logistics coordinator", "associate", 1),
    ("flight attendant", "certificate", 1),
    ("site supervisor", "associate", 2),
    ("surveyor", "bachelor", 2),
    ("estimator", "bachelor", 2),
    ("inspector", "certificate", 1),
    ("cnc operator", "certificate", 1),
    ("chemical operator", "certificate", 1),
    ("safety coordinator", "associate", 2),
    ("production supervisor", "associate", 2),
    ("shift supervisor", "high_school", 1),
    ("lean specialist", "bachelor", 2),
    ("quality inspector", "certificate", 1),
    ("it support", "certificate", 1),
    ("qa tester", "certificate", 1),
    ("systems administrator", "associate", 2),
    ("bookkeeper", "certificate", 1),
    ("payroll specialist", "certificate", 1),
    ("mortgage broker", "certificate", 2),
    ("loan officer", "certificate", 2),
    ("insurance agent", "certificate", 1),
    ("claims adjuster", "certificate", 1),
    ("bank teller", "high_school", 1),
    ("assistant store manager", "high_school", 1),
    ("store manager", "associate", 2),
    ("floor manager", "high_school", 1),
    ("department supervisor", "high_school", 1),
    ("loss prevention officer", "certificate", 1),
    ("retail trainer", "high_school", 1),
    ("chef", "trade_school", 2),
    ("sous chef", "trade_school", 2),
    ("pastry chef", "trade_school", 2),
    ("sommelier", "certificate", 1),
    ("kitchen manager", "trade_school", 1),
    ("restaurant manager", "associate", 1),
    ("banquet manager", "associate", 1),
    ("catering manager", "associate", 1),
    ("event coordinator", "bachelor", 1),
    ("travel agent", "certificate", 1),
    ("tour guide", "high_school", 1),
    ("cruise director", "bachelor", 1),
    ("concierge", "high_school", 1),

    # -- Tier 1: no real prerequisite --
    ("cashier", "none", 1),
    ("laborer", "none", 1),
    ("janitor", "none", 1),
    ("sanitation worker", "none", 1),
    ("dishwasher", "none", 1),
    ("waiter", "none", 1),
    ("host", "none", 1),
    ("food runner", "none", 1),
    ("line cook", "none", 1),
    ("barista", "none", 1),
    ("bartender", "certificate", 1),
    ("housekeeper", "none", 1),
    ("hotel receptionist", "high_school", 1),
    ("room service attendant", "none", 1),
    ("carpenter", "trade_school", 1),
    ("mason", "trade_school", 1),
    ("bricklayer", "trade_school", 1),
    ("drywall installer", "none", 1),
    ("concrete finisher", "none", 1),
    ("demolition worker", "none", 1),
    ("roofer", "none", 1),
    ("painter", "none", 1),
    ("welder", "trade_school", 1),
    ("assembler", "none", 1),
    ("fabricator", "none", 1),
    ("machine operator", "certificate", 1),
    ("packaging operator", "none", 1),
    ("materials planner", "associate", 1),
    ("production planner", "bachelor", 2),
    ("process engineer", "bachelor", 3),
    ("industrial engineer", "bachelor", 3),
    ("shipping clerk", "none", 1),
    ("warehouse picker", "none", 1),
    ("warehouse associate", "none", 1),
    ("warehouse manager", "associate", 2),
    ("baggage handler", "none", 1),
    ("courier", "none", 1),
    ("delivery driver", "certificate", 1),
    ("ride share driver", "certificate", 1),
    ("tow truck operator", "certificate", 1),
    ("traffic controller", "certificate", 1),
    ("postal carrier", "high_school", 1),
    ("forklift operator", "certificate", 1),
    ("customer service representative", "high_school", 1),
    ("e-commerce associate", "high_school", 1),
    ("electronics specialist", "high_school", 1),
    ("furniture salesperson", "high_school", 1),
    ("garden associate", "none", 1),
    ("jewelry salesperson", "high_school", 1),
    ("pricing coordinator", "associate", 1),
    ("receiving clerk", "none", 1),
    ("returns specialist", "none", 1),
    ("sales associate", "none", 1),
    ("shift lead", "high_school", 1),
    ("stock clerk", "none", 1),
    ("visual merchandiser", "high_school", 1),
    ("inventory specialist", "high_school", 1),
    ("buyer", "bachelor", 2),
    ("pharmacy cashier", "high_school", 1),

    # -- Illegal/fringe -- no real prerequisite; kept sane for data
    # hygiene even though these are hired through crime.py, not
    # apply_for_job (which structurally excludes illegal jobs already).
    ("bouncer", "none", 1),
    ("bodyguard", "certificate", 1),
    ("security guard", "certificate", 1),
]

# Compiled once, longest-substring-first within any tie so a more
# specific phrase (already ordered above) isn't shadowed by a shorter
# one that happens to appear earlier by accident.
_KEYWORD_RULES.sort(key=lambda r: -len(r[0]))

_STRIP_PREFIXES = ("lead senior ", "senior lead ", "lead ", "senior ")


def _normalize_title(name):
    n = (name or "").lower().strip()
    changed = True
    while changed:
        changed = False
        for p in _STRIP_PREFIXES:
            if n.startswith(p):
                n = n[len(p):]
                changed = True
    return n


def classify_job(job_template):
    """Returns (complexity_tier: int 1-4, degree_required: str). Illegal/
    criminal_tier jobs still get a real classification (data hygiene) even
    though nothing in the qualification-gated apply_for_job() path ever
    reads it for them."""
    name = _normalize_title(job_template.get("name", ""))

    for keyword, degree, tier in _KEYWORD_RULES:
        if keyword in name:
            return tier, degree

    # Fallback for anything not covered by name -- lean on physical/
    # social demand as a rough real-world proxy (high physical + low
    # social skews toward manual/trade work; low physical + high social
    # skews toward office/professional work) rather than income_class/
    # salary, which are exactly as unreliable as the degree_required data
    # this function exists to correct.
    physical = job_template.get("physical_demand", 50)
    social = job_template.get("social_demand", 50)
    if physical >= 65 and social < 50:
        return 1, "none"
    if physical >= 45:
        return 2, "certificate"
    if social >= 65:
        return 3, "bachelor"
    return 2, "high_school"


def apply_classification(job_template):
    """Mutates job_template in place with a corrected complexity_tier and
    degree_required, keeping them mutually consistent (degree never
    falls below its tier's floor -- see _MIN_TIER_DEGREE_FLOOR)."""
    tier, degree = classify_job(job_template)
    floor = _MIN_TIER_DEGREE_FLOOR[tier]
    if DEGREE_RANK.get(degree, 0) < DEGREE_RANK[floor]:
        degree = floor
    job_template["complexity_tier"] = tier
    job_template["degree_required"] = degree
    return tier, degree
