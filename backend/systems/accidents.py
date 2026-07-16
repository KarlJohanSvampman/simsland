"""
accidents.py -- non-violent, activity-grounded injury triggers.

Mirrors hostile_actions.py's shape but for accidents rather than attacks:
reuses health.py's apply_blade_injury/apply_burn_injury as the mechanism,
tied to activities already happening in the sim (currently: cooking's
knife/heat stage_primitives -- see cooking_process.py's active-stage block).
"""

import random

from systems.health import apply_blade_injury, apply_burn_injury

# stage_primitives key -> (injury kind, per-tick chance while the stage is
# active, body part). Chances are per-tick, not per-session -- stages run
# several ticks (see stage_primitives' default_duration in definitions.json),
# so these stay rare flavor events rather than a routine occurrence.
COOKING_HAZARDS = {
    "chop":              ("blade", 0.003, "hand"),
    "fry":                ("burn", 0.002, "hand"),
    "put_on_stove":       ("burn", 0.004, "hand"),
    "take_off_stove":     ("burn", 0.004, "hand"),
    "put_in_oven":        ("burn", 0.004, "hand"),
    "take_out_of_oven":   ("burn", 0.004, "hand"),
}


def maybe_trigger_cooking_accident(c, world, primitive_key):
    hazard = COOKING_HAZARDS.get(primitive_key)
    if not hazard:
        return
    kind, chance, body_part = hazard
    if random.random() >= chance:
        return
    tick = world.get("tick", 0)
    if kind == "blade":
        # Household-knife scale -- well under stab/knock's weapon-grade
        # sharpness/size values.
        apply_blade_injury(c, world, body_part, sharpness=0.3, size=0.2,
                            irregular_shape=False, tick=tick)
    else:
        apply_burn_injury(c, world, body_part, severity=random.uniform(0.15, 0.4), tick=tick)
