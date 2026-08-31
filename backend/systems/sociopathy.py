"""
systems/sociopathy.py

Sociopathy behavioral modeling -- see mental_health_templates["sociopath"]
(definitions.json). Diagnosis auto-grants domestic_abuser, so the
already-complete abuse-tactics engine (domestic_control.py's negging/
shame-threat/isolation-pressure tick) just starts running for these
characters with no logic changes there. Pathological lying is wired
directly into excuses.py's generate_excuse(); this module owns the
genuinely new pieces: diagnosis, multiple concurrent personas
(persona_bank + per-relationship known_as), the honesty-exception
lookup, and drama-planting.
"""

import random
import uuid

SOCIOPATH_DIAGNOSIS_CHANCE = 0.02  # adults+ at generation -- real-world ASPD prevalence ~1-4%
PLANT_DRAMA_CHANCE = 0.02          # per real conversation exchange
PERSONA_INTRO_CHANCE = 0.15        # per new (low-familiarity) contact encountered
DISCOVERY_CHANCE = 0.01            # per pair of contacts who know the sociopath under different names, per daily tick


def maybe_diagnose_sociopath(c):
    """Called at generation for adults+ (see character_gen.py's post-
    build hook block). Auto-grants domestic_abuser (Confirmed Decision
    #12) so domestic_control.py's existing engine just starts running,
    no logic changes there."""
    if c.get("age_group") not in ("adult", "elderly"):
        return False
    if random.random() > SOCIOPATH_DIAGNOSIS_CHANCE:
        return False

    c.setdefault("mental_health", [])
    if "sociopath" not in c["mental_health"]:
        c["mental_health"].append("sociopath")
    traits = c.setdefault("traits", [])
    if "domestic_abuser" not in traits:
        traits.append("domestic_abuser")
    return True


def is_sociopath(c):
    return "sociopath" in c.get("mental_health", [])


def controlled_partner_id(c, world):
    """The one person a sociopath is genuinely honest with -- the
    partner they're running the abusive relationship with (Confirmed
    Decision #14a). Reuses domestic_control.py's own partner lookup so
    this stays in sync with whoever tick_domestic_control() actually
    applies tactics to."""
    if not is_sociopath(c):
        return None
    from systems.domestic_control import _find_intimate_partners
    partners = _find_intimate_partners(c, world.get("characters", {}))
    return partners[0] if partners else None


# =========================================================
# MULTIPLE CONCURRENT PERSONAS (Confirmed Decision #13)
# =========================================================

def maybe_introduce_false_identity(c, other, world):
    """A sociopath meeting a new (low-familiarity) contact may introduce
    themselves as one of their persona_bank identities (generating a new
    one if needed) instead of their real name -- persistent, not the
    single-activity systems/persona.py::active_persona. Stamps the
    OTHER character's own relationship record with what THEY believe the
    sociopath's identity is (known_as), which can genuinely differ
    contact-to-contact."""
    if not is_sociopath(c):
        return None
    if random.random() > PERSONA_INTRO_CHANCE:
        return None

    from brain.relationships import ensure_relationship
    rel_from_other = ensure_relationship(other, c["id"])
    if rel_from_other.get("known_as"):
        return None  # already introduced to this contact

    bank = c.setdefault("persona_bank", [])
    if bank and random.random() < 0.6:
        persona = random.choice(bank)
    else:
        from systems.persona import generate_persona
        persona = generate_persona(c, world)
        bank.append(persona)
        c["active_persona"] = None  # this is a persistent identity, not a temporary cover

    rel_from_other["known_as"] = persona["name"]
    return persona


def maybe_discover_persona_mismatch(c, world):
    """Daily-cadence roll: two of a sociopath's contacts who each have a
    known_as on file compare notes and realize they differ -- a real,
    generated discovery moment feeding stories.py."""
    if not is_sociopath(c) or not c.get("persona_bank"):
        return None

    characters = world.get("characters", {})
    known_by = []
    for other_id, other in characters.items():
        rel = other.get("relationships", {}).get(c["id"], {})
        if rel.get("known_as"):
            known_by.append((other_id, rel["known_as"]))

    distinct_names = {name for _, name in known_by}
    if len(distinct_names) < 2 or random.random() > DISCOVERY_CHANCE:
        return None

    a_id, a_name = random.choice(known_by)
    mismatches = [(oid, name) for oid, name in known_by if name != a_name]
    if not mismatches:
        return None
    b_id, b_name = random.choice(mismatches)

    from brain.memory import store_memory
    tick = world.get("tick", 0)
    text = (f"Realized {c.get('name', 'someone')} introduced themselves as "
            f"\"{a_name}\" to one person and \"{b_name}\" to another.")
    for discoverer_id in (a_id, b_id):
        discoverer = characters.get(discoverer_id)
        if discoverer:
            store_memory(discoverer, text, 0.85,
                         ["drama", "deception", "identity"], "sociopathy", tick,
                         people=[c["id"]])
    return {"a": a_id, "b": b_id}


# =========================================================
# PLANTING DRAMA (Confirmed Decision #14c)
# =========================================================

def maybe_plant_drama(c, world, listener=None):
    """A real, consequential fabrication about a real third party,
    delivered to a real listener -- can seed a genuinely unjustified
    grievance in the listener against the person lied about."""
    if not is_sociopath(c):
        return None
    if random.random() > PLANT_DRAMA_CHANCE:
        return None

    characters = world.get("characters", {})
    if listener is None:
        contacts = [characters[oid] for oid in c.get("relationships", {}) if oid in characters]
        if not contacts:
            return None
        listener = random.choice(contacts)

    victim_pool = [oc for oc in characters.values()
                   if oc["id"] not in (c["id"], listener["id"])]
    if not victim_pool:
        return None
    victim = random.choice(victim_pool)

    claims = [
        f"I heard {victim.get('name', 'they')} has been talking behind your back.",
        f"Between us -- {victim.get('name', 'they')} can't really be trusted.",
        f"I probably shouldn't say this, but {victim.get('name', 'they')} was saying awful things about you.",
    ]
    claim = random.choice(claims)

    try:
        from systems.incidental_speech import fire_incidental
        fire_incidental(c, "gossip", claim, world, target_id=listener["id"])
    except Exception:
        pass

    from systems.grievances import add_grievance
    add_grievance(listener, victim["id"], "witnessed_transgression", world,
                  severity=6.0, details={"context": "planted_drama", "source": c["id"]})

    return {"listener_id": listener["id"], "victim_id": victim["id"], "claim": claim}
