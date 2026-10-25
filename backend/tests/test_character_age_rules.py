"""
Age-appropriate generation (systems/age_rules.py via systems/character_gen.py): no jobs under 18, the right school and grade,
and hobbies, problems, body quirks and fetishes that fit the age.

Run inside the backend container:   python tests/test_character_age_rules.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from db import load_definitions
from systems import age_rules as ar
from systems.character_gen import generate_character

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


defs = load_definitions("default")
schools = defs["school_templates"]
hobbies = defs["hobby_templates"]

# ---- the rules themselves -----------------------------------------------------------------------------------------------------
check("age 5 is kindergarten at a preschool", ar.school_placement(5) == ("preschool", 0))
check("age 4 is preschool with no grade", ar.school_placement(4) == ("preschool", None))
check("under 3 there is no school", ar.school_placement(2) == (None, None))
check("age 6 is 1st grade, primary", ar.school_placement(6) == ("primary", 1))
check("age 10 is 5th grade, still primary", ar.school_placement(10) == ("primary", 5))
check("age 11 is 6th grade, middle school", ar.school_placement(11) == ("middle_school", 6))
check("age 13 is 8th grade, middle school", ar.school_placement(13) == ("middle_school", 8))
check("age 14 is 9th grade, high school", ar.school_placement(14) == ("high_school", 9))
check("age 17 is 12th grade", ar.school_placement(17) == ("high_school", 12))
check("an adult is not a school child", ar.school_placement(18) == (None, None))
check("what has been completed so far", [ar.attained_education(a) for a in (4, 6, 10, 11, 13, 14, 17)] ==
      ["none", "preschool", "preschool", "primary", "primary", "middle_school", "middle_school"])
check("grade labels", [ar.grade_label(g) for g in (0, 1, 2, 3, 4, 11, 12)] ==
      ["kindergarten", "1st grade", "2nd grade", "3rd grade", "4th grade", "11th grade", "12th grade"])
check("the specialist school is never a random choice", all("oakdale_special_ed" not in ar.pick_school_ids(schools, a) for a in range(3, 18)))
check("every school-age year has at least one general school", all(ar.pick_school_ids(schools, a) for a in range(3, 18)))
check("gambling is for adults", all(ar.hobby_min_age(h) == 18 for h in ("poker", "slot_machines", "lottery", "bingo", "sports_betting")))
check("hunting and shooting are 16+", ar.hobby_min_age("hunting") == 16 and ar.hobby_min_age("shooting_sports") == 16)
check("every hobby in the definitions has a rule (nothing falls to the default)", all(h in ar.HOBBY_MIN_AGE for h in hobbies if not h.startswith("_")),
      str([h for h in hobbies if not h.startswith("_") and h not in ar.HOBBY_MIN_AGE]))
check("an unknown hobby is not for little children", not ar.hobby_ok("some_new_thing", 8) and ar.hobby_ok("some_new_thing", 30))
check("a definitions entry's own min_age wins", ar.hobby_ok("poker", 12, {"min_age": 10}))

# ---- generated people -----------------------------------------------------------------------------------------------------------
random.seed(11)
bad = {"job": [], "school": [], "hobby": [], "problem": [], "quirk": [], "fetish": [], "edu": [], "searching": [], "grade": []}
count = 0
for age in range(3, 91):
    for _ in range(12):
        c = generate_character(defs, {"age": age})
        count += 1
        if age < 18:
            if c.get("job") or c.get("employed") or c.get("occupation") != "none":
                bad["job"].append((age, c.get("job")))
            if c.get("job_searching"):
                bad["searching"].append(age)
            if c.get("fetishes"):
                bad["fetish"].append((age, c["fetishes"]))
            if [p for p in c.get("problems", []) if p not in ar.KID_PROBLEMS]:
                bad["problem"].append((age, c["problems"]))
            if [a for a in c.get("abnormal_traits", []) if a in ar.ADULT_ONLY_ABNORMAL]:
                bad["quirk"].append((age, c["abnormal_traits"]))
            level, grade = ar.school_placement(age)
            sid = c.get("current_school")
            if age >= 3 and (not sid or schools[sid]["education_level"] != level or "special_ed" in sid
                             or not (schools[sid]["age_range"][0] <= age <= schools[sid]["age_range"][1])):
                bad["school"].append((age, sid))
            if c.get("school_grade") != grade:
                bad["grade"].append((age, c.get("school_grade"), grade))
            if c.get("education") != ar.attained_education(age):
                bad["edu"].append((age, c.get("education")))
        for h in c.get("hobbies", []):
            if not ar.hobby_ok(h, age, hobbies.get(h)):
                bad["hobby"].append((age, h))
        if c.get("hobbies") == [] and age >= 4:       # a three-year-old has no hobbies yet
            bad["hobby"].append((age, "none at all"))
print(f"   generated {count} characters, ages 3-90")
check("nobody under 18 has a job, is employed, or is looking for one", not bad["job"] and not bad["searching"], str(bad["job"][:3] + bad["searching"][:3]))
check("every school-age child is at a general school of the right level and age", not bad["school"], str(bad["school"][:5]))
check("and in the right grade", not bad["grade"], str(bad["grade"][:5]))
check("their education is what they have completed so far", not bad["edu"], str(bad["edu"][:5]))
check("every hobby fits its owner's age, and everyone from four up has one", not bad["hobby"], str(bad["hobby"][:8]))
check("children have only mild problems", not bad["problem"], str(bad["problem"][:5]))
check("children have no adult body quirks and no fetishes", not bad["quirk"] and not bad["fetish"], str(bad["quirk"][:3] + bad["fetish"][:3]))

adults = [generate_character(defs, {"age": a}) for a in range(25, 60) for _ in range(4)]
check("adults still get jobs", sum(1 for c in adults if c.get("job") and c["job"].get("id")) > 100)
check("adults can still have gambling hobbies, adult problems and fetishes", any(ar.HOBBY_MIN_AGE.get(h) == 18 for c in adults for h in c["hobbies"])
      and any(p not in ar.KID_PROBLEMS for c in adults for p in c["problems"]) and any(c.get("fetishes") for c in adults))

# ---- overrides ---------------------------------------------------------------------------------------------------------------------
c = generate_character(defs, {"age": 15, "job": {"id": "x", "title": "Stock Clerk"}, "hobbies": ["slot_machines", "painting"]})
check("a job in a template does not give a 15-year-old a job", not c["job"] and c["occupation"] == "none")
check("a hobby in a template that the age does not allow is dropped, the rest kept", c["hobbies"] == ["painting"], str(c["hobbies"]))
c = generate_character(defs, {"age": 15, "hobbies": ["slot_machines"]})
check("and if nothing is left, an appropriate one is picked", c["hobbies"] and all(ar.hobby_ok(h, 15, hobbies.get(h)) for h in c["hobbies"]), str(c["hobbies"]))
c = generate_character(defs, {"age": 30, "hobbies": ["poker", "hunting"]})
check("adults keep what they chose", c["hobbies"] == ["poker", "hunting"])

# ---- the prompt ----------------------------------------------------------------------------------------------------------------------------
from brain.context_builder import _sec_identity
kid = generate_character(defs, {"age": 9})
def prompt(c):
    out = _sec_identity(c, {"definitions": defs})
    return " ".join(out) if isinstance(out, list) else str(out)


text = prompt(kid)
check("the prompt tells a child their grade and school", "4th grade" in text and schools[kid["current_school"]]["name"] in text, text[:200])
tot = generate_character(defs, {"age": 4})
text = prompt(tot)
check("and a preschooler just where they go", "You go to" in text and "grade" not in text, text[:200])
grown = generate_character(defs, {"age": 40})
check("an adult's prompt has no school line", "grade at" not in prompt(grown))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
