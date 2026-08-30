"""
systems/family.py — family tree engine

A "family" is a group of characters linked by biological or legal kinship,
independent of who lives in the same household.

world["families"] = {
    "fam_abc": {
        "id":       "fam_abc",
        "surname":  "Kowalski",
        "members":  ["char_1", "char_2", ...],
        # directed edge: (from_id, to_id) -> relation label
        "relations": { "char_1:char_2": "parent", ... }
    }
}

Each character also gets:
    c["family_id"]   = "fam_abc" | None
    c["family_role"] = "head" | "spouse" | "child" | "parent" | ...

And on the per-contact relationship object:
    c["relationships"][other_id]["kinship"] = "parent" | "sibling" | None | ...
"""

import random
from systems.religious_repression import generate_family_values, init_repression_state
import uuid

# ---------------------------------------------------------------------------
# Relation vocabulary
# ---------------------------------------------------------------------------

INVERSE = {
    "parent":          "child",
    "child":           "parent",
    "sibling":         "sibling",
    "half_sibling":    "half_sibling",
    "spouse":          "spouse",
    "ex_spouse":       "ex_spouse",
    "grandparent":     "grandchild",
    "grandchild":      "grandparent",
    "aunt_uncle":      "niece_nephew",
    "niece_nephew":    "aunt_uncle",
    "cousin":          "cousin",
    "step_parent":     "step_child",
    "step_child":      "step_parent",
    "adoptive_parent": "adoptive_child",
    "adoptive_child":  "adoptive_parent",
    "guardian":        "ward",
    "ward":            "guardian",
}

CLOSE_KIN  = {"parent","child","sibling","spouse","grandparent","grandchild"}
LEGAL_KIN  = {"step_parent","step_child","adoptive_parent","adoptive_child","guardian","ward"}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rel_key(a, b):
    return f"{a}:{b}"

def _set_relation(family, a_id, b_id, a_to_b):
    """Set directed relation a→b and its inverse b→a."""
    family["relations"][_rel_key(a_id, b_id)] = a_to_b
    family["relations"][_rel_key(b_id, a_id)] = INVERSE.get(a_to_b, a_to_b)

def _add_member(family, char_id):
    if char_id not in family["members"]:
        family["members"].append(char_id)

def _new_family(surname):
    return {
        "id":        f"fam_{uuid.uuid4().hex[:8]}",
        "surname":   surname,
        "members":   [],
        "relations": {},
        "values":    generate_family_values(),
    }

def _random_char_for_role(world, defs, age_lo, age_hi, sex=None, exclude_ids=None):
    """
    Find an existing character that fits age/sex constraints and has no family yet,
    or return None (caller will create a stub NPC).
    """
    exclude_ids = set(exclude_ids or [])
    candidates = [
        c for c in world.get("characters", {}).values()
        if age_lo <= c.get("age", 0) <= age_hi
        and not c.get("family_id")
        and c["id"] not in exclude_ids
        and (sex is None or c.get("sex") == sex)
    ]
    return random.choice(candidates) if candidates else None

def _stub_npc(world, defs, age, sex, surname=None, seed_char=None, relation_type=None):
    """
    Generate a minimal off-screen NPC character (no position, not active).
    Used for relatives who aren't in the simulation proper.

    When seed_char/relation_type are both given, traits/hobbies/
    physical_traits are derived from seed_char via
    relative_gen.derive_relative() instead of being fully random, and a
    small templated bio is attached -- see relative_gen.py.
    """
    from systems.character_gen import generate_character
    overrides = {
        "age": age,
        "sex": sex,
        "x": -9999, "y": -9999,
        "is_offscreen": True,
    }
    if seed_char is not None and relation_type is not None:
        from systems.relative_gen import derive_relative, _fallback_bio
        derived = derive_relative(seed_char, relation_type, defs, sex=sex)
        overrides["traits"]          = derived["traits"]
        overrides["hobbies"]         = derived["hobbies"]
        overrides["physical_traits"] = derived["physical_traits"]
        overrides["bio"]             = _fallback_bio(seed_char, relation_type, derived["traits"])
        if relation_type == "child" and seed_char.get("values"):
            overrides["parent_values"] = [seed_char["values"]]
    if surname:
        c = generate_character(defs, overrides, world=world)
        c["family_name"] = surname
        c["name"] = f"{c['first_name']} {surname}"
    else:
        c = generate_character(defs, overrides, world=world)
    world["characters"][c["id"]] = c
    return c

# ---------------------------------------------------------------------------
# Kinship sync — keeps c["relationships"][other]["kinship"] in sync
# ---------------------------------------------------------------------------

def sync_kinship_to_relationships(family, world):
    """
    After building/modifying a family, stamp kinship labels onto every pair's
    relationship object so the LLM context always has it without a lookup.
    """
    chars = world.get("characters", {})
    for key, rel_label in family["relations"].items():
        a_id, b_id = key.split(":", 1)
        a = chars.get(a_id)
        if not a:
            continue
        a.setdefault("relationships", {})
        a["relationships"].setdefault(b_id, {})
        a["relationships"][b_id]["kinship"] = rel_label
        # Ensure family_id is stamped
        if a.get("family_id") is None:
            a["family_id"] = family["id"]

# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------

def generate_family_for_character(char, world, defs, depth=1):
    """
    Build a plausible family tree centred on `char` and insert it into
    world["families"].  Returns the family dict.

    depth=1 → immediate family (parents, siblings, spouse, children)
    depth=2 → also grandparents, aunts/uncles, cousins  (expensive)

    Characters that don't exist in the simulation are created as off-screen
    NPC stubs so every family member has a real character id.
    """
    age      = char.get("age", 30)
    sex      = char.get("sex", "male")
    surname  = char.get("family_name", "Unknown")
    char_id  = char["id"]

    # If already in a family, just return it
    if char.get("family_id"):
        return world.get("families", {}).get(char["family_id"])

    world.setdefault("families", {})

    family = _new_family(surname)
    fam_id = family["id"]

    _add_member(family, char_id)
    char["family_id"]   = fam_id
    char["family_role"] = "head"

    # ── Parents ─────────────────────────────────────────────────────────────
    if age >= 5:
        parent_age_lo = max(18, age + 18)
        parent_age_hi = age + 55

        # Father
        father = _random_char_for_role(world, defs, parent_age_lo, parent_age_hi, sex="male", exclude_ids=[char_id])
        if father is None:
            father = _stub_npc(world, defs, random.randint(parent_age_lo, min(parent_age_hi, 90)), "male", surname,
                                seed_char=char, relation_type="parent")
        father["family_id"]   = fam_id
        father["family_role"] = "parent"
        _add_member(family, father["id"])
        _set_relation(family, father["id"], char_id, "parent")

        # Mother (different surname typically, but same family unit)
        mother_surname = surname if random.random() < 0.5 else f"{surname}-{'Smith'}"
        mother = _random_char_for_role(world, defs, parent_age_lo, parent_age_hi, sex="female", exclude_ids=[char_id, father["id"]])
        if mother is None:
            mother = _stub_npc(world, defs, random.randint(parent_age_lo, min(parent_age_hi, 90)), "female",
                                seed_char=char, relation_type="parent")
        mother["family_id"]   = fam_id
        mother["family_role"] = "parent"
        _add_member(family, mother["id"])
        _set_relation(family, mother["id"], char_id, "parent")
        _set_relation(family, father["id"], mother["id"], "spouse")

        # ── Grandparents (depth=2) ───────────────────────────────────────────
        if depth >= 2:
            for parent_c, label_from_char in [(father, "grandparent"), (mother, "grandparent")]:
                p_age = parent_c.get("age", 50)
                for gp_sex in ("male", "female"):
                    gp_age_hi = min(p_age + 40, 100)
                    gp_age_lo = min(max(40, p_age + 18), gp_age_hi)
                    gp = _stub_npc(world, defs, random.randint(gp_age_lo, gp_age_hi), gp_sex,
                                    seed_char=char, relation_type="grandparent")
                    gp["family_id"]   = fam_id
                    gp["family_role"] = "grandparent"
                    _add_member(family, gp["id"])
                    _set_relation(family, gp["id"], parent_c["id"], "parent")
                    _set_relation(family, gp["id"], char_id, "grandparent")

    # ── Siblings ────────────────────────────────────────────────────────────
    if age >= 5:
        num_siblings = random.choices([0, 1, 2, 3, 4], weights=[25, 30, 25, 15, 5])[0]
        for _ in range(num_siblings):
            sib_age_lo = max(5, age - 15)
            sib_age_hi = age + 15
            sib_sex = random.choice(["male", "female"])
            sib = _random_char_for_role(world, defs, sib_age_lo, sib_age_hi, sex=sib_sex,
                                        exclude_ids=list(family["members"]))
            if sib is None:
                sib = _stub_npc(world, defs, random.randint(sib_age_lo, sib_age_hi), sib_sex, surname,
                                 seed_char=char, relation_type="sibling")
            sib["family_id"]   = fam_id
            sib["family_role"] = "sibling"
            _add_member(family, sib["id"])
            _set_relation(family, char_id, sib["id"], "sibling")
            # Siblings share parents
            for mid in list(family["members"]):
                c = world["characters"].get(mid)
                if c and c.get("family_role") == "parent":
                    _set_relation(family, mid, sib["id"], "parent")

            # Sibling's spouse (depth≥1, sibling is adult)
            if depth >= 1 and sib.get("age", 0) >= 22 and random.random() < 0.55:
                sp_sex = "female" if sib_sex == "male" else "male"
                sp = _stub_npc(world, defs, random.randint(max(22, sib.get("age",25)-8), sib.get("age",30)+5), sp_sex)
                sp["family_id"]   = fam_id
                sp["family_role"] = "in_law"
                _add_member(family, sp["id"])
                _set_relation(family, sib["id"], sp["id"], "spouse")

    # ── Spouse ──────────────────────────────────────────────────────────────
    if age >= 18:
        married_chance = 0.0
        if 22 <= age < 35:  married_chance = 0.45
        elif 35 <= age < 55: married_chance = 0.65
        elif age >= 55:      married_chance = 0.60

        if random.random() < married_chance:
            sp_sex = "female" if sex == "male" else "male"
            sp = _random_char_for_role(world, defs,
                                       max(18, age - 12), age + 12,
                                       sex=sp_sex, exclude_ids=list(family["members"]))
            if sp is None:
                sp = _stub_npc(world, defs, random.randint(max(18, age - 12), age + 12), sp_sex,
                                seed_char=char, relation_type="spouse")
            sp["family_id"]   = fam_id
            sp["family_role"] = "spouse"
            _add_member(family, sp["id"])
            _set_relation(family, char_id, sp["id"], "spouse")

            # ── Children ────────────────────────────────────────────────────
            if age >= 22:
                max_kids  = max(0, (age - 20) // 3)
                num_kids  = random.choices(range(min(5, max_kids) + 1),
                                           weights=[20, 30, 25, 15, 7, 3][:min(5, max_kids) + 1])[0]
                for _ in range(num_kids):
                    kid_age = random.randint(1, max(1, age - 20))
                    kid_sex = random.choice(["male", "female"])
                    kid = _random_char_for_role(world, defs, max(1, kid_age - 2), kid_age + 2,
                                                sex=kid_sex, exclude_ids=list(family["members"]))
                    if kid is None:
                        kid = _stub_npc(world, defs, kid_age, kid_sex, surname,
                                         seed_char=char, relation_type="child")
                    kid["family_id"]   = fam_id
                    kid["family_role"] = "child"
                    _add_member(family, kid["id"])
                    _set_relation(family, char_id, kid["id"], "parent")
                    _set_relation(family, sp["id"], kid["id"], "parent")

                    # Siblings between children
                    for mid in list(family["members"]):
                        existing = world["characters"].get(mid)
                        if existing and existing.get("family_role") == "child" and mid != kid["id"]:
                            _set_relation(family, kid["id"], mid, "sibling")

        elif age >= 30 and random.random() < 0.20:
            # Divorced
            sp_sex = "female" if sex == "male" else "male"
            ex = _stub_npc(world, defs, random.randint(max(18, age - 10), age + 10), sp_sex,
                            seed_char=char, relation_type="ex_spouse")
            ex["family_id"]   = fam_id
            ex["family_role"] = "ex_spouse"
            _add_member(family, ex["id"])
            _set_relation(family, char_id, ex["id"], "ex_spouse")

    # ── Aunts/uncles and cousins (depth=2) ──────────────────────────────────
    if depth >= 2:
        for mid in list(family["members"]):
            pc = world["characters"].get(mid)
            if not pc or pc.get("family_role") != "parent":
                continue
            p_age = pc.get("age", 50)
            num_au = random.randint(0, 2)
            for _ in range(num_au):
                au_sex = random.choice(["male", "female"])
                au_age = random.randint(max(20, p_age - 12), p_age + 12)
                au = _stub_npc(world, defs, au_age, au_sex, seed_char=char, relation_type="aunt_uncle")
                au["family_id"]   = fam_id
                au["family_role"] = "aunt_uncle"
                _add_member(family, au["id"])
                _set_relation(family, au["id"], mid, "sibling")
                _set_relation(family, au["id"], char_id, "aunt_uncle")

                # Cousins
                num_cousins = random.randint(0, 3)
                for _ in range(num_cousins):
                    c_age = random.randint(max(1, age - 15), age + 15)
                    c_sex = random.choice(["male", "female"])
                    cous  = _stub_npc(world, defs, c_age, c_sex, seed_char=char, relation_type="cousin")
                    cous["family_id"]   = fam_id
                    cous["family_role"] = "cousin"
                    _add_member(family, cous["id"])
                    _set_relation(family, au["id"], cous["id"], "parent")
                    _set_relation(family, char_id, cous["id"], "cousin")

    # ── Finalise ────────────────────────────────────────────────────────────
    world["families"][fam_id] = family
    sync_kinship_to_relationships(family, world)
    return family


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_kinship(family, a_id, b_id):
    """Return the relation label from a's perspective to b, or None."""
    return family.get("relations", {}).get(_rel_key(a_id, b_id))


def get_family_summary(family, world):
    """
    Return a human-readable dict describing the family tree —
    useful for LLM context and the debug UI.
    """
    chars  = world.get("characters", {})
    result = {
        "family_id": family["id"],
        "surname":   family["surname"],
        "size":      len(family["members"]),
        "members":   []
    }
    for mid in family["members"]:
        c = chars.get(mid, {})
        entry = {
            "id":   mid,
            "name": c.get("name", mid),
            "age":  c.get("age"),
            "sex":  c.get("sex"),
            "role": c.get("family_role"),
            "offscreen": c.get("is_offscreen", False),
            "relations_to_others": {}
        }
        for key, label in family["relations"].items():
            from_id, to_id = key.split(":", 1)
            if from_id == mid:
                target = chars.get(to_id, {})
                entry["relations_to_others"][target.get("name", to_id)] = label
        result["members"].append(entry)
    return result
