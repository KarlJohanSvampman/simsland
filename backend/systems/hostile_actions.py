"""
systems/hostile_actions.py

Resolves forced/hostile interaction_templates (punch, kick, shove,
catch_and_hold, hold_down, threaten, ...) in advance -- hit / evaded /
fumble -- reusing the same trait/dice-driven formula shape as
conflict_pipeline.py's escalation math, per this session's standing
design boundary: the act itself may resolve formulaically, but every
reaction to it (dodge/block/flee/intervene/call 911) stays a normal
per-tick LLM choice through the narrative/available-actions loop.

effectiveness_modifiers condition strings (definitions.json's
interaction_templates, e.g. "actor.trait == 'strong'",
"actor.height > target.height * 1.1",
"actor.held_item.category == 'melee_weapon_sharp'") are a small, fixed
grammar authored for a system that was never built -- not eval()-worthy.
_eval_condition() is a purpose-built parser, not a general expression
evaluator, and treats any missing/None field (most characters don't have
height/masked populated yet) as "condition not satisfied" rather than
raising.
"""

import random
import re
import uuid

from core.event_bus import emit
from systems.templates import get_interaction_template, resolve_item
from systems.posture import set_posture
from systems.body import drain_stamina

DEFENSE_STANCE_WINDOW_TICKS = 10
MAX_RECENT_HOSTILE_ACTS = 5

# Action ids the LLM chooses -> interaction_templates ids where they differ.
ACTION_TEMPLATE_MAP = {
    "grab_offensive": "catch_and_hold",
    "hold":           "hold_down",
}

# Baseline knockdown chance by template -- strikes can knock someone down,
# holds/threats don't.
_KNOCKDOWN_BASE = {
    "punch": 0.15, "kick": 0.20, "shove": 0.10,
    "catch_and_hold": 0.0, "hold_down": 0.0, "threaten": 0.0,
}

# Stamina cost (attacker) by template -- holds are more taxing to maintain
# than a single strike.
_STAMINA_COST = {
    "punch": 0.03, "kick": 0.04, "shove": 0.02,
    "catch_and_hold": 0.05, "hold_down": 0.06, "threaten": 0.0,
    "stab": 0.04, "knock": 0.05,
}

# Weapon category each weapon-gated template requires for its injury
# branch to actually fire -- an unarmed "stab"/"knock" is just a weak
# unarmed strike (effectiveness_modifiers already apply a heavy penalty
# for it), not a real wound.
_REQUIRED_WEAPON_CATEGORY = {
    "stab": "melee_weapon_sharp",
    "knock": "melee_weapon_blunt",
}


# ── Condition evaluator ─────────────────────────────────────────────────────

def _resolve_field(side, field, world):
    """Resolve a dotted field off a character dict for the condition DSL."""
    if field == "held_item":
        return next((i for i in side.get("inventory", []) if i.get("location") == "held"), None)
    if field == "held_item.category":
        held = next((i for i in side.get("inventory", []) if i.get("location") == "held"), None)
        if not held:
            return None
        # weapon_category, not category -- category is the item's
        # shelving/UI grouping (e.g. "kitchenware"); weapon_category is
        # the new, narrower combat tag added this round (see
        # simulations/default/definitions.json's item_templates: knife/
        # utility_knife -> melee_weapon_sharp, bat/pan/hammer ->
        # melee_weapon_blunt).
        return resolve_item(world, held).get("weapon_category")
    return side.get(field)


_CONDITION_RE = re.compile(r"^(actor|target)\.([\w.]+)\s*(==|>=|<=|>|<)\s*(.+)$")
_RHS_SIDE_RE  = re.compile(r"^(actor|target)\.([\w.]+)\s*\*\s*([\d.]+)$")


def _parse_literal(raw, actor, target, world):
    raw = raw.strip()
    m = _RHS_SIDE_RE.match(raw)
    if m:
        side = actor if m.group(1) == "actor" else target
        val = _resolve_field(side, m.group(2), world)
        if val is None or isinstance(val, (list, dict)):
            return None
        try:
            return float(val) * float(m.group(3))
        except (TypeError, ValueError):
            return None
    if raw in ("true", "false"):
        return raw == "true"
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    try:
        return float(raw)
    except ValueError:
        return None


def _eval_condition(condition, actor, target, world):
    """Evaluate one effectiveness_modifiers condition string. Never raises."""
    if not condition:
        return False
    m = _CONDITION_RE.match(condition.strip())
    if not m:
        return False
    side_name, field, op, rhs_raw = m.groups()
    side = actor if side_name == "actor" else target

    if field == "trait":
        rhs = _parse_literal(rhs_raw, actor, target, world)
        if op != "==" or not isinstance(rhs, str):
            return False
        return rhs in side.get("traits", [])

    # "actor.held_item == null" (the unarmed check threaten/stab/knock
    # all rely on) needs its own branch -- the generic "lhs is None ->
    # not satisfied" short-circuit below would otherwise make this
    # condition impossible to ever satisfy, since an unarmed character
    # is exactly the case where held_item resolves to None.
    if field == "held_item" and op == "==" and rhs_raw.strip().lower() in ("null", "none"):
        return _resolve_field(side, field, world) is None

    lhs = _resolve_field(side, field, world)
    if lhs is None or isinstance(lhs, (list, dict)):
        return False

    rhs = _parse_literal(rhs_raw, actor, target, world)
    if rhs is None:
        return False

    try:
        if op == "==":
            return lhs == rhs
        if op == ">":
            return float(lhs) > float(rhs)
        if op == "<":
            return float(lhs) < float(rhs)
        if op == ">=":
            return float(lhs) >= float(rhs)
        if op == "<=":
            return float(lhs) <= float(rhs)
    except (TypeError, ValueError):
        return False
    return False


def _effectiveness(tpl, actor, target, world):
    score = 1.0
    for mod in tpl.get("effectiveness_modifiers", []):
        if _eval_condition(mod.get("condition"), actor, target, world):
            score *= mod.get("multiplier", 1.0)
    return score


# ── Resolution formulas (same shape as conflict_pipeline.py's escalation
# math -- base + trait deltas + emotion + a small random term) ────────────

def _has(c, *traits):
    return any(t in c.get("traits", []) for t in traits)


def _evasion_chance(target, world):
    base = 0.25
    if _has(target, "agile", "athletic", "quick"):
        base += 0.20
    if _has(target, "clumsy", "heavy_build", "slow"):
        base -= 0.15
    emotion = target.get("emotion", "neutral")
    if emotion in ("alert", "focused"):
        base += 0.10
    elif emotion in ("distracted", "drunk", "exhausted"):
        base -= 0.15

    stance = target.get("defense_stance")
    if stance and world.get("tick", 0) - stance.get("tick", -9999) <= DEFENSE_STANCE_WINDOW_TICKS:
        base += 0.35 if stance.get("type") == "dodge" else 0.25

    return max(0.02, min(0.9, base + random.gauss(0, 0.05)))


def _fumble_chance(effectiveness):
    """Higher when the attacker's own roll was poor."""
    return max(0.03, min(0.35, 0.15 - effectiveness * 0.1))


# ── Animation write (same twin-write pattern as
# intimacy.py::_execute_touch, driven by the template's authored clips
# instead of a hardcoded dict) ──────────────────────────────────────────────

def _write_hostile_activity(char, tpl_side, action_id, partner_id, tick):
    clips = tpl_side.get("start") or []
    if not clips:
        return
    char["activity"] = {
        "type":               "hostile_interaction",
        "interaction":        action_id,
        "phase":              "using",
        "phase_started_tick": tick,
        "target_id":          partner_id,
        "state":              {},
    }
    char["animation_state"] = clips[0]


def _tag_hostile_act(actor, action_id, target_id, tick, outcome):
    acts = actor.setdefault("recent_hostile_acts", [])
    acts.append({"type": action_id, "target_id": target_id, "tick": tick, "outcome": outcome})
    del acts[:-MAX_RECENT_HOSTILE_ACTS]


def _apply_relationship_impact(actor, target, outcome):
    """Same shape as conflict_pipeline.py::_handle_physical's relationship
    deltas -- hostility up / trust down on both sides, fear up on the
    target specifically."""
    for c, other in ((actor, target), (target, actor)):
        rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
        rel["hostility"] = min(100, rel.get("hostility", 0) + 15)
        rel["trust"]     = max(-100, rel.get("trust", 0) - 20)
    victim_rel = target.setdefault("relationships", {}).setdefault(actor["id"], {})
    victim_rel["fear"] = min(100, victim_rel.get("fear", 0) + 15)


# ── Main entry point ────────────────────────────────────────────────────────

def resolve_hostile_action(actor, target, action_id, world):
    """
    Resolve a hostile action (punch/kick/shove/catch_and_hold/hold_down/
    threaten) from actor against target. Returns the outcome string
    ("hit", "evaded", "fumble") or None if the template couldn't be
    resolved.
    """
    template_id = ACTION_TEMPLATE_MAP.get(action_id, action_id)
    tpl = get_interaction_template(world, template_id)
    if not tpl:
        return None

    tick = world.get("tick", 0)
    effectiveness = _effectiveness(tpl, actor, target, world)
    evasion = _evasion_chance(target, world)

    roll = random.random()
    if roll < evasion:
        outcome = "evaded"
    elif random.random() < _fumble_chance(effectiveness):
        outcome = "fumble"
    else:
        outcome = "hit"

    # Consume a used defense stance regardless of outcome -- it was the
    # target's one shot at this exchange.
    stance = target.pop("defense_stance", None)
    stance_type = stance.get("type", "dodge") if stance else "dodge"

    # Attacker's own swing/grab animation plays no matter what happened.
    _write_hostile_activity(actor, tpl.get("animations", {}), action_id, target["id"], tick)
    drain_stamina(actor, _STAMINA_COST.get(template_id, 0.03))

    if outcome == "hit":
        _write_hostile_activity(target, tpl.get("target_animations", {}), action_id, actor["id"], tick)
        _apply_relationship_impact(actor, target, outcome)
        drain_stamina(target, 0.02)

        knockdown_chance = _KNOCKDOWN_BASE.get(template_id, 0.0) * effectiveness
        if knockdown_chance > 0 and random.random() < knockdown_chance:
            drain_stamina(target, 0.05)
            set_posture(target, world, "fallen_front")

        # Real injury for weapon-gated strikes -- health.py's
        # apply_blade_injury()/apply_blunt_trauma() were fully built
        # against definitions.json's physical_injury_schema but had zero
        # call sites before this round. Only fires when the actor is
        # actually holding the right weapon category -- an unarmed
        # "stab"/"knock" (already heavily penalized by
        # effectiveness_modifiers) is a weak strike, not a real wound.
        required_weapon = _REQUIRED_WEAPON_CATEGORY.get(template_id)
        if required_weapon and _resolve_field(actor, "held_item.category", world) == required_weapon:
            body_part = tpl.get("target_region", "torso")
            try:
                if template_id == "stab":
                    from systems.health import apply_blade_injury
                    apply_blade_injury(target, world, body_part,
                                        sharpness=0.7, size=0.5,
                                        irregular_shape=False, tick=tick)
                elif template_id == "knock":
                    from systems.health import apply_blunt_trauma
                    force_normalized = max(0.0, min(1.0, effectiveness / 3.0))
                    apply_blunt_trauma(target, world, body_part, force_normalized, tick)
            except Exception:
                pass

        # hold_down landing a hit used to be purely cosmetic (twin
        # animation write, then nothing persisted -- its authored
        # "applies_state": "pinned" field was read by zero code). Now it
        # starts a real, persistent restraint via the same engine
        # wrestle uses (systems/grapple.py), just mode="pin" -- a static
        # hold rather than a stamina-contest wrestle, with its own
        # held_down/holding_down postures and a lower base escape chance.
        if template_id == "hold_down" and not target.get("held_by") and not actor.get("holding"):
            try:
                from systems.grapple import start_grapple
                start_grapple(actor, target, world, mode="pin")
            except Exception:
                pass

        try:
            from systems.reactions import push_reaction
            push_reaction(target, "startled", tick, priority=2)
        except Exception:
            pass

        try:
            from systems.emergency import report_assault_incident
            report_assault_incident(world, actor, victim=target)
        except Exception:
            pass

    elif outcome == "evaded":
        try:
            from systems.reactions import push_reaction
            push_reaction(target, stance_type, tick)
        except Exception:
            pass

    elif outcome == "fumble":
        set_posture(actor, world, "fallen_front")
        try:
            from systems.reactions import push_reaction
            push_reaction(target, "dodge", tick)
        except Exception:
            pass
        try:
            from systems.emergency import report_assault_incident
            report_assault_incident(world, actor, victim=target)
        except Exception:
            pass

    _tag_hostile_act(actor, action_id, target["id"], tick, outcome)

    emit("hostile_action_resolved", {
        "actor_id": actor["id"], "target_id": target["id"],
        "action": action_id, "outcome": outcome,
    })

    return outcome
