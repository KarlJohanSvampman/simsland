"""
systems/service_npc.py

Shared template-selection helper for lightweight, non-agentic
"is_service_worker" NPCs (mail-adjacent contractors, CPS workers, and
any future emergency-responder-style dispatch) -- previously every
spawn site hardcoded "template": "adult_base", a character_templates id
that doesn't exist (confirmed via direct read of definitions.json's
character_templates registry -- it silently fell back to the plain
fallback-primitive renderer for every single service worker, never a
real body). Reuses the SAME template-resolution machinery every other
character already goes through (frontend/src/templates.js::
resolveCharacter -> definitions.character_templates[c.template]) rather
than inventing a second lookup.

Real, distinct 3D assets for role-specific NPCs (police, fire, paramedic,
mail carrier) don't exist yet -- each ROLE_TEMPLATES entry is still a
real, independently-addressable character_templates id, already wired
end to end (including the existing per-template animation-override tool
in the Character Creator, keyed by this same template id), just pointing
at the generic adult body as a placeholder until a real .glb is dropped
in and that one template's "model" field is updated -- no code changes
needed anywhere else at that point.
"""

import random

# service_role/worker_trait -> a real, role-specific character_templates
# id, for the handful of roles where a visually distinct NPC is worth a
# dedicated template slot. Anything not listed here (the generic
# SERVICE_CATALOG trade roles -- contractor, repairman, gardener,
# caregiver, dealer, arms_dealer, escort) uses the plain sex-based
# fallback (service_worker_male / service_worker_female) instead.
ROLE_TEMPLATES = {
    "cps_worker":     "cps_worker",
    "police_officer": "police_officer",
    "firefighter":    "firefighter",
    "paramedic":       "paramedic",
    "mail_carrier":    "mail_carrier",
}


def pick_worker_template(role, sex=None):
    """Returns (template_id, sex). sex is rolled if not given, since
    every real character carries one and the generic fallback templates
    are sex-split; a role template (when one exists for this role) wins
    over the generic fallback regardless of sex."""
    sex = sex or random.choice(["male", "female"])
    template = ROLE_TEMPLATES.get(role) or f"service_worker_{sex}"
    return template, sex
