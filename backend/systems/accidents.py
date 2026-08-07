"""
accidents.py -- non-violent, activity-grounded injury triggers.

Mirrors hostile_actions.py's shape but for accidents rather than attacks.
Fully data-driven (Round 3 of the damage-system rework): rolls the acting
interaction/stage_primitive's `possible_accidents` array (definitions.json,
{accident_template, probability}), then rolls the chosen accident_template's
own `possible_injuries` array, and hands off to health.py::apply_injury --
the same chain combat interactions use, just via an accident_template
middleman instead of going straight to an injury_template. Generalizes to
any future interaction with a possible_accidents array, not just cooking's
stage_primitives (currently the only content authored, see cooking_process.py's
active-stage block).
"""

from systems.health import apply_injury, weighted_pick


def maybe_trigger_cooking_accident(c, world, primitive_key):
    defs = world.get("definitions", {})
    tpl = defs.get("stage_primitives", {}).get(primitive_key)
    if not tpl:
        return
    possible_accidents = tpl.get("possible_accidents", [])
    if not possible_accidents:
        return

    accident_pick = weighted_pick(possible_accidents)
    if not accident_pick:
        return

    accident_key = accident_pick.get("accident_template")
    accident_tmpl = defs.get("accident_templates", {}).get(accident_key)
    if not accident_tmpl:
        return

    injury_pick = weighted_pick(accident_tmpl.get("possible_injuries", []))
    if not injury_pick:
        return

    tick = world.get("tick", 0)
    apply_injury(c, world, injury_pick.get("injury_template"), accident_key, tick=tick)
