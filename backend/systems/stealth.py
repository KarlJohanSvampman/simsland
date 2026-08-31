"""
systems/stealth.py

Shared sneak-entry framework for Burglar (systems/crime.py's shared
shift, extended to actually use this instead of an abstract roll) and
Private Investigator infiltration (systems/crime.py::
tick_pi_assignments). Forced entry needs a real lockpick or glass_cutter
in inventory. Sneaking itself carries a real noise/detection risk,
reusing reactions.py's existing involuntary-sound/alert-nearby
machinery (a new "sneak_noise" reaction type) rather than a parallel
detection system.
"""

import random

ENTRY_TOOL_TEMPLATES = ("lockpick", "glass_cutter")
BASE_ENTRY_SUCCESS = 0.75
NOISE_CHANCE = 0.25


def has_entry_tool(c):
    from systems.personal_items import get_item_by_template
    return any(get_item_by_template(c, t) for t in ENTRY_TOOL_TEMPLATES)


def attempt_sneak_entry(c, world):
    """Returns {"entered": bool, "detected": bool, "reason"?: str}. No
    real lockpick/glass_cutter in inventory -> no attempt at all."""
    if not has_entry_tool(c):
        return {"entered": False, "detected": False, "reason": "no_tool"}

    c["animation_state"] = "sneak"

    entered = random.random() < BASE_ENTRY_SUCCESS
    detected = random.random() < NOISE_CHANCE and _make_sneak_noise(c, world)

    return {"entered": entered, "detected": detected}


def _make_sneak_noise(c, world):
    """A real, audible noise -- see reactions.py's REACTION_SOUNDS/
    _alert_nearby (loudness>=2 can wake a same-building character in a
    different room). Returns True (a noise really was made) regardless
    of whether anyone happened to be close enough to hear it."""
    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(c, world, "sneak_noise")
    except Exception:
        pass
    return True
