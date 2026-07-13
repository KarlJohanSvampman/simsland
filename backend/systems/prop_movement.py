"""
systems/prop_movement.py

Movable props — a prop tagged with move_capacity (1 or 2) can be dragged
by a character (following behind them while they walk) and, if it needs
two people, pushed along by a second character attached from behind.

Two independent, combinable roles, tracked on the character
(c["dragged_prop_id"] / c["pushing_prop_id"]) and mirrored on the prop
instance (prop["being_dragged_by"] / prop["being_pushed_by"]):
  - Dragging alone is enough to move a move_capacity=1 prop.
  - A move_capacity=2 prop only actually moves once BOTH roles are
    filled — see movement.py's "crewed" check. Dragging one solo just
    marks it attached; the prop stays put until a pusher joins.

Separate from the pre-existing pushed_prop_id mechanic (baby carriage /
lawnmower, action_router.py's _route_put_baby_in_carriage) — that stays
its own single-character-only thing.
"""

from systems.templates import get_prop_template
from systems.posture import _idle_key, _POSTURE_SETTLE_TICKS


def get_move_capacity(prop):
    """Read move_capacity straight off the placed-prop instance —
    assembly.py copies it from the template at assembly time, same
    pattern as anchors. None/missing = not movable at all."""
    return prop.get("move_capacity")


def get_drag_animation(world, prop):
    tpl = get_prop_template(world, prop)
    return tpl.get("drag_animation") if tpl else None


def get_push_animation(world, prop):
    tpl = get_prop_template(world, prop)
    return tpl.get("push_animation") if tpl else None


def play_prop_action_once(c, world, action_key, target_idle=None, ticks=_POSTURE_SETTLE_TICKS):
    """
    One-shot animation that settles back to an idle state — same shape as
    item_stack.py's play_item_action_once, with one addition: an optional
    target_idle override. _idle_key() resolves by body posture (standing,
    sitting_seat, ...), which drag/push are orthogonal to — after
    "start_dragging" finishes, a character should settle to "drag_idle",
    not their ordinary posture idle, hence the override.
    """
    c["animation_state"] = action_key
    c["_posture_settle"] = {
        "expected_state": action_key,
        "target_idle":    target_idle or _idle_key(world, c.get("posture", "standing")),
        "ready_at_tick":  world.get("tick", 0) + ticks,
    }
