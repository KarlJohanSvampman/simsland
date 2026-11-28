"""
What a child calls their parents (systems/family_address.py; live 2026-11-28: Christopher and Alexander called their
mother "Rebecca" and their father "Anthony").

A. parents(): from either side's kinship label, or the spouse of a parent at home; not a grandparent at home with no
   label; not for adults.
B. The prompt: "you call her Mom, never Rebecca"; a step-parent is left to them.
C. fix_vocative: "Rebecca, ..." / "Hey Rebecca, ..." / "..., Anthony?" said to that parent -> Mom / Dad; her name in the
   middle of a line, a line to someone else, an adult speaker: unchanged.

Run inside the backend container:   python tests/test_family_address.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from systems import family_address as F

mom = {"id": "r", "name": "Rebecca Martinez", "sex": "female", "age_group": "adult", "household_id": "h"}
dad = {"id": "a", "name": "Anthony Martinez", "sex": "male", "age_group": "adult", "household_id": "h",
       "relationships": {"r": {"kinship": "spouse"}}}
grandpa = {"id": "g", "name": "Daniel Martinez", "sex": "male", "age_group": "elderly", "household_id": "h",
           "relationships": {"r": {"kinship": "parent"}}}
kid = {"id": "c", "name": "Christopher Martinez", "sex": "male", "age_group": "teen", "household_id": "h",
       "relationships": {"a": {"kinship": "child"}, "r": {}, "x": {"kinship": "sibling"}}}
sib = {"id": "x", "name": "Alexander Martinez", "sex": "male", "age_group": "child", "household_id": "h"}
neighbour = {"id": "n", "name": "Pamela Shaw", "sex": "female", "age_group": "adult", "household_id": "h2"}
kid["relationships"]["n"] = {}
world = {"characters": {c["id"]: c for c in (mom, dad, kid, sib, neighbour, grandpa)}}

# A
ps = {oid: term for oid, term, _ in F.parents(kid, world)}
check("A: dad by kinship, mom as his wife at home (no label); not grandpa", ps == {"a": "Dad", "r": "Mom"}, ps)
pam = {"id": "p", "name": "Pamela Martinez", "sex": "female", "age_group": "teen", "household_id": "h", "relationships": {}}
mom["relationships"] = {"p": {"kinship": "parent"}}
world["characters"]["p"] = pam
check("A: the parent's own label counts too", [o for o, _, _ in F.parents(pam, world)] == ["r"], F.parents(pam, world))
check("A: an adult has no parents here", F.parents(mom, world) == [])

# B
text = " ".join(F.prompt_lines(kid, world))
check("B: you call her Mom, never Rebecca", "call her Mom, never Rebecca" in text, text)
check("B: you call him Dad, never Anthony", "call him Dad, never Anthony" in text, text)
check("B: talk like their kid", "kid" in text)
kid["relationships"]["a"]["kinship"] = "step_child"
check("B: a step-parent is left to them", "stepdad" in " ".join(F.prompt_lines(kid, world)))
check("B: ...and isn't renamed", F.fix_vocative(world, kid, "a", "Anthony, can I go out?") == "Anthony, can I go out?")
kid["relationships"]["a"]["kinship"] = "child"

# C
cases = [("r", "Rebecca, can I go to Jake's after school?", "Mom, can I go to Jake's after school?"),
         ("r", "Hey Rebecca, what's for dinner?", "Hey Mom, what's for dinner?"),
         ("r", "Hi, Rebecca! I finished my homework.", "Hi, Mom! I finished my homework."),
         ("a", "Can we play catch later, Anthony?", "Can we play catch later, Dad?"),
         ("a", "I told Rebecca I'd be back by six.", "I told Rebecca I'd be back by six."),
         ("r", "Did Anthony say we could go?", "Did Anthony say we could go?"),
         ("n", "Pamela, have you seen my ball?", "Pamela, have you seen my ball?")]
for tid, said, want in cases:
    got = F.fix_vocative(world, kid, tid, said)
    check(f"C: {said!r} -> {want!r}", got == want, got)
check("C: an adult's line is left alone", F.fix_vocative(world, dad, "r", "Rebecca, dinner's ready.") == "Rebecca, dinner's ready.")

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
