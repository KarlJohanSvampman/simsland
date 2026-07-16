"""
systems/grapple.py

wrestle/overtake: a repeatable hold. Modeled directly on
conflict_pipeline.py's proven shape (dict-keyed-by-id in
world["grapples"], an "outcome" sentinel, a cadence-driven
process_grapples(world) advancing one round every GRAPPLE_ROUND_TICKS,
mirroring _process_fight's "ticks_in_phase % FIGHT_EXCHANGE_TICKS"
idiom) -- the "repeated resolution every few ticks until an outcome"
pattern already proven in this codebase. task_process.py was checked
and rejected as a template: it's household/list-oriented with no
twin-character sync or per-round contest roll.

Per the standing design boundary: only each round's own stamina-check
result resolves formulaically. Whether to wrestle at all, whether to
release, whether to struggle -- those stay real per-tick LLM choices.
The struggle option reuses the exact "dodge" defense_stance flag
hostile_actions.py already built (a character who chose dodge recently
also reads as "actively fighting to break free" here) -- no new action
needed for that half.
"""

import uuid
import random

from core.event_bus import emit
from systems.body import drain_stamina

GRAPPLE_ROUND_TICKS = 8
MAX_GRAPPLE_ROUNDS = 12
STRUGGLE_WINDOW_TICKS = 10


def _has(c, *traits):
    return any(t in c.get("traits", []) for t in traits)


# Both "wrestle" (standing contest, see hostile_actions.py's
# catch_and_hold) and "pin" (static hold, see hostile_actions.py's
# hold_down "hit" outcome) share the one held_down/holding_down posture
# pair -- a standing-vs-ground distinction turned out not to earn its
# keep, see the stance-simplification round. Each stance's idle_key *is*
# the struggle animation -- no separate cosmetic layer needed.
_HELD_POSTURE   = "held_down"
_HOLDING_POSTURE = "holding_down"

# The bookkeeping *flag* names stay mode-distinct -- they still drive
# different escape-chance formulas (see _escape_chance below) even
# though the visual posture no longer differs.
_MODE_FIELDS = {
    "wrestle": {"held": "grappled_by", "holder": "grappling"},
    "pin":     {"held": "held_by",     "holder": "holding"},
}


def start_grapple(holder, held, world, mode="wrestle"):
    """Create the persistent grapple entry once the initial grab (see
    action_router.py::_route_wrestle for mode="wrestle", or
    hostile_actions.py::resolve_hostile_action's hold_down hit branch for
    mode="pin") lands."""
    grapple = {
        "id":              f"grapple_{uuid.uuid4().hex[:8]}",
        "holder_id":       holder["id"],
        "held_id":         held["id"],
        "mode":            mode,
        "round":           1,
        "tick_started":    world.get("tick", 0),
        "tick_last_round": world.get("tick", 0),
        "outcome":         None,
    }
    world.setdefault("grapples", {})[grapple["id"]] = grapple

    fields = _MODE_FIELDS[mode]
    held[fields["held"]] = holder["id"]
    holder[fields["holder"]] = held["id"]

    from systems.posture import set_posture
    set_posture(held, world, _HELD_POSTURE)
    set_posture(holder, world, _HOLDING_POSTURE)

    emit("grapple_started", {
        "grapple_id": grapple["id"], "mode": mode,
        "holder_id":  holder["id"],  "held_id": held["id"],
    })
    return grapple


def _escape_chance(held, holder, world, mode="wrestle"):
    """Same trait/emotion/dice shape as conflict_pipeline.py's
    _escalation_chance/_de_escalation_chance -- base + trait deltas +
    a stamina term + a small random term. A static pin (mode="pin") is
    harder to break than shrugging off a wrestling hold."""
    base = 0.25 if mode == "wrestle" else 0.15
    if _has(held, "agile", "athletic", "strong"):
        base += 0.15
    if _has(held, "clumsy", "heavy_build", "weak"):
        base -= 0.10
    if _has(holder, "strong", "heavy_build"):
        base -= 0.15
    if _has(holder, "clumsy", "weak"):
        base += 0.10

    held_stamina = held.get("stamina", 1.0)
    if held_stamina < 0.2:
        base -= 0.20
    elif held_stamina > 0.7:
        base += 0.05

    stance = held.get("defense_stance")
    if stance and stance.get("type") == "dodge" and \
            world.get("tick", 0) - stance.get("tick", -9999) <= STRUGGLE_WINDOW_TICKS:
        base += 0.25

    return max(0.03, min(0.85, base + random.gauss(0, 0.05)))


def _clear_grapple_flags(grapple, world):
    chars = world.get("characters", {})
    held = chars.get(grapple["held_id"])
    holder = chars.get(grapple["holder_id"])
    fields = _MODE_FIELDS[grapple.get("mode", "wrestle")]
    if held:
        held.pop(fields["held"], None)
    if holder:
        holder.pop(fields["holder"], None)

    from systems.posture import set_posture
    if held and held.get("posture") == _HELD_POSTURE:
        set_posture(held, world, "standing")
    if holder and holder.get("posture") == _HOLDING_POSTURE:
        set_posture(holder, world, "standing")


def _resolve(grapple, outcome, world):
    grapple["outcome"] = outcome
    grapple["tick_ended"] = world.get("tick", 0)
    _clear_grapple_flags(grapple, world)
    emit("grapple_resolved", {
        "grapple_id": grapple["id"], "outcome": outcome,
        "holder_id":  grapple["holder_id"], "held_id": grapple["held_id"],
    })


def release_hold(holder, world):
    """The holder's own free choice to stop -- see
    action_router.py::_route_release_hold. Resolves immediately
    regardless of round/stamina state, same "genuine free exit" shape as
    respond_touch/give_excuse elsewhere in this codebase."""
    for grapple in world.get("grapples", {}).values():
        if grapple["outcome"] is not None:
            continue
        if grapple["holder_id"] == holder["id"]:
            _resolve(grapple, "released", world)
            return grapple
    return None


def active_grapple_for(character_id, world):
    """The one active grapple this character (holder or held) is
    currently part of, or None."""
    for grapple in world.get("grapples", {}).values():
        if grapple["outcome"] is not None:
            continue
        if character_id in (grapple["holder_id"], grapple["held_id"]):
            return grapple
    return None


def process_grapples(world):
    """Advance every active grapple. Called from sim_loop on the same
    cadence tier as conflicts (see core/tick_schedule.py's
    CADENCE["grapples"])."""
    chars = world.get("characters", {})
    tick = world.get("tick", 0)

    for grapple in list(world.get("grapples", {}).values()):
        if grapple["outcome"] is not None:
            continue

        holder = chars.get(grapple["holder_id"])
        held = chars.get(grapple["held_id"])
        if not holder or not held:
            _resolve(grapple, "broken_off", world)
            continue

        if tick - grapple["tick_last_round"] < GRAPPLE_ROUND_TICKS:
            continue
        grapple["tick_last_round"] = tick

        # Sustained exertion -- the held character pays more than the
        # holder, but holding on is tiring too.
        drain_stamina(held, 0.08)
        drain_stamina(holder, 0.03)

        if holder.get("stamina", 1.0) <= 0.0:
            _resolve(grapple, "escaped", world)
            try:
                from systems.reactions import push_reaction
                push_reaction(held, "dodge", tick)
            except Exception:
                pass
            held.pop("defense_stance", None)
            continue

        escaped = random.random() < _escape_chance(held, holder, world, grapple.get("mode", "wrestle"))
        # Struggling on purpose is a one-round-at-a-time choice -- consume
        # the stance so the bonus doesn't silently persist across rounds
        # without the LLM choosing to keep fighting.
        held.pop("defense_stance", None)

        if escaped:
            _resolve(grapple, "escaped", world)
            rel = holder.setdefault("relationships", {}).setdefault(held["id"], {})
            rel["hostility"] = min(100, rel.get("hostility", 0) + 10)
            try:
                from systems.reactions import push_reaction
                push_reaction(held, "dodge", tick)
            except Exception:
                pass
            continue

        grapple["round"] += 1
        if grapple["round"] >= MAX_GRAPPLE_ROUNDS or held.get("stamina", 1.0) <= 0.0:
            _resolve(grapple, "pinned", world)
            rel = held.setdefault("relationships", {}).setdefault(holder["id"], {})
            rel["fear"] = min(100, rel.get("fear", 0) + 20)
