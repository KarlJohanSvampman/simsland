"""
systems/persona.py

Cover personas -- a runtime flag for whether a character is "being
themselves" or playing an assumed identity, generated from tags and
STORED (c["active_persona"]) so a criminal caught at work gives a
consistent story if asked who they are. Plugs directly into
excuses.py's existing lie/consistency machinery (see its persona-aware
_get_true_detail() read) rather than being a parallel lie engine.
"""

import random
import uuid

_FIRST_NAMES = ["Alex", "Sam", "Jordan", "Casey", "Morgan", "Taylor", "Riley", "Jamie"]
_LAST_NAMES  = ["Reed", "Brooks", "Hale", "Stone", "Doyle", "Vance", "Cross", "Marsh"]

_OCCUPATION_LABELS = {
    "delivery_worker":     "package delivery",
    "police_officer":      "a police officer on patrol",
    "nurse":               "a home-visit nurse",
    "doctor":              "a doctor on a house call",
    "construction_worker": "a construction inspector",
    "janitor":             "building maintenance",
    "military_officer":    "a military liaison",
    "paramedic":           "a paramedic on a welfare check",
    "firefighter":         "a fire-safety inspector",
    "lab_worker":          "an environmental inspector",
    "utility_worker":      "a utility technician",
    "inspector":           "a building inspector",
    "surveyor":            "a property surveyor",
}
_DEFAULT_TAGS = ["utility_worker", "inspector", "delivery_worker"]


def generate_persona(c, world, tags=None):
    """Builds and adopts a new cover persona for c, biased toward any
    currently-worn disguise clothing's disguise_persona_tag (see
    definitions.json's disguise item_templates, systems/clothing.py's
    c["worn"] shape) when present, else the given tags, else a generic
    fallback pool."""
    disguise_tag = _worn_disguise_tag(c, world)
    pool = [disguise_tag] if disguise_tag else (tags or _DEFAULT_TAGS)
    chosen_tag = random.choice(pool)

    persona = {
        "id":               f"persona_{uuid.uuid4().hex[:8]}",
        "name":             f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}",
        "occupation_label": _OCCUPATION_LABELS.get(chosen_tag, "just passing through"),
        "cover_tags":       [chosen_tag],
        "adopted_tick":     world.get("tick", 0),
    }
    c["active_persona"] = persona
    return persona


def clear_persona(c):
    c["active_persona"] = None


def _worn_disguise_tag(c, world):
    worn = c.get("worn")
    if not isinstance(worn, dict):
        return None
    items = world.get("definitions", {}).get("item_templates", {})
    for item in worn.values():
        if not isinstance(item, dict):
            continue
        tmpl = items.get(item.get("template_id"), {})
        if tmpl.get("disguise"):
            return tmpl.get("disguise_persona_tag")
    return None
