"""
systems/workplace_npc.py

Real, lightweight, non-agentic NPCs for a character's professional life
-- recruiters, bosses, colleagues. Modeled directly on
systems/services.py::_spawn_worker()'s shape (a bare dict inserted
straight into world["characters"], flagged so it never runs full
per-tick cognition) rather than the full systems/character_gen.py
generator: these people are only ever off-grid/narrated (job interviews,
work-shift narration, phone calls), never physically rendered or
walked, so they don't need a body/needs simulation, x/y placement, or
an LLM-driven decision loop of their own.

c["workplace_contact_ids"] is a real, separately-capped (max 10) list
of who counts as a "known workplace contact" for a given character --
distinct from the much larger, unrelated c["relationships"] dict.
get_or_create_workplace_contact() is the single entry point every
consumer (hiring, hourly work-shift narration wanting to introduce
someone new) should call: it generates fresh NPCs until the cap is hit,
then always reuses an existing one, per the user's own "expand over
time until max 10, then reuse" framing.

Reputation/dependency (brain/relationships.py's new workplace_
reputation/workplace_dependency fields) are reciprocal but computed
lazily -- ensure_reciprocal_view() only ever creates the OTHER side's
opinion the first time something actually needs to read it, never as an
eager N-by-N generation pass.
"""

import random
import uuid

WORKPLACE_CONTACT_CAP = 10

_ROLE_TRAIT_FLAVOR_COUNT = (1, 2)


def _pick_flavor_traits(defs):
    pool = list((defs.get("trait_templates") or {}).keys())
    if not pool:
        return []
    n = random.randint(*_ROLE_TRAIT_FLAVOR_COUNT)
    return random.sample(pool, min(n, len(pool)))


def generate_workplace_npc(role, company_key, job_template, world):
    """role: "recruiter" | "boss" | "colleague". Returns the new
    character dict (already inserted into world["characters"])."""
    from systems.character_gen import _random_name, _random_sex

    defs = world.get("definitions", {})
    sex = _random_sex()
    first, last = _random_name(defs, sex)
    age = random.randint(24, 62)

    job_title = (job_template or {}).get("name", "employee")

    nid = f"npc_{role}_{uuid.uuid4().hex[:8]}"
    npc = {
        "id":               nid,
        "name":             f"{first} {last}",
        "first_name":       first,
        "family_name":      last,
        "sex":              sex,
        "age":              age,
        "traits":           _pick_flavor_traits(defs),
        "physical_traits":  [],
        "job_template_id":  (job_template or {}).get("id") or (job_template or {}).get("name"),
        "company_id":       company_key,
        "role":             role,
        "is_workplace_npc": True,
        "relationships":    {},
        "employed":         True,
    }
    world.setdefault("characters", {})[nid] = npc

    company = world.setdefault("companies", {}).setdefault(
        company_key, {"employee_ids": [], "boss_id": None}
    )
    if nid not in company["employee_ids"]:
        company["employee_ids"].append(nid)
    if role == "boss" and not company.get("boss_id"):
        company["boss_id"] = nid

    return npc


def _link_workplace_contact(c, other_id):
    ids = c.setdefault("workplace_contact_ids", [])
    if other_id not in ids:
        ids.append(other_id)
        ids[:] = ids[-WORKPLACE_CONTACT_CAP:]


def get_or_create_workplace_contact(c, world, role_hint, company_key=None, job_template=None):
    """The one entry point for "I need a real, named workplace contact
    right now" -- generates a fresh NPC while under the cap, otherwise
    always reuses a random existing one instead of growing further.
    Also links both sides so the relationship is discoverable from
    either character."""
    ids = c.get("workplace_contact_ids", [])

    if len(ids) < WORKPLACE_CONTACT_CAP:
        company_key = company_key or c.get("company_id")
        other = generate_workplace_npc(role_hint, company_key, job_template, world)
    else:
        other_id = random.choice(ids)
        other = world.get("characters", {}).get(other_id)
        if other is None:
            # Stale id (shouldn't normally happen) -- drop it and retry once.
            ids.remove(other_id)
            return get_or_create_workplace_contact(c, world, role_hint, company_key, job_template)

    _link_workplace_contact(c, other["id"])
    _link_workplace_contact(other, c["id"])

    from brain.relationships import ensure_relationship
    ensure_relationship(c, other["id"])
    ensure_relationship(other, c["id"])

    return other


def ensure_reciprocal_view(other_id, c, world):
    """Lazily reads-or-creates other_id's OWN relationship entry toward
    c (and seeds a small randomized starting workplace_reputation/
    workplace_dependency biased loosely by other's own traits) -- the
    reciprocal "what do THEY think of ME" side, computed on demand
    rather than eagerly for every pair up front."""
    other = world.get("characters", {}).get(other_id)
    if not other:
        return None

    from brain.relationships import ensure_relationship
    rel = ensure_relationship(other, c["id"])

    if rel.get("_reciprocal_seeded"):
        return rel

    base_rep = random.uniform(-15, 15)
    if "moody" in other.get("traits", []) or "cynical" in other.get("traits", []):
        base_rep -= 5
    rel["workplace_reputation"] = round(base_rep, 1)
    rel["workplace_dependency"] = round(random.uniform(5, 35), 1)
    rel["_reciprocal_seeded"] = True
    return rel
