"""
systems/item_stack.py

A character's "stack": an ordered pile of different item types held in one
hand without needing a container prop. Distinct from c["inventory"]'s flat
pocket list — an item leaves inventory while it's a member of the stack,
same as it already leaves inventory while placed on the ground.

Items declare stack_position: "stackable" | "not_stackable" | "top".
"top" means: whenever this item is added, it must be the topmost item in
the stack, even if more items are added after it. Distinct field/concept
from the pre-existing boolean `stackable` on items, which means something
unrelated (identical instances merging into a quantity counter).
"""

from systems.posture import _idle_key, _POSTURE_SETTLE_TICKS


def add_to_held_stack(c, item):
    """
    Insert `item` into c["held_stack"], respecting the "top" ordering rule.
    Caller must have already rejected stack_position == "not_stackable".

    held_stack is ordered bottom->top (index 0 = bottom, [-1] = topmost).
    A "top" item always appends past every existing element (including
    prior "top" items), so the most-recently-added "top" item is always
    the true topmost. A non-"top" item always inserts strictly before the
    first existing "top" item, so it can never end up above one.
    """
    stack = c.setdefault("held_stack", [])
    if item.get("stack_position") == "top":
        stack.append(item)
    else:
        first_top = next(
            (i for i, it in enumerate(stack) if it.get("stack_position") == "top"),
            None,
        )
        if first_top is None:
            stack.append(item)
        else:
            stack.insert(first_top, item)
    item["location"] = "stacked"


def remove_from_held_stack(c, item_id):
    """Pop and return the item dict with matching id, or None if absent."""
    stack = c.setdefault("held_stack", [])
    for i, item in enumerate(stack):
        if item.get("id") == item_id:
            return stack.pop(i)
    return None


def play_item_action_once(c, world, action_key, ticks=_POSTURE_SETTLE_TICKS):
    """
    One-shot animation that settles back to the character's CURRENT
    posture's idle. Reuses posture.py's _posture_settle mechanism —
    promote_pending_posture() is already polled every character every tick
    from agent_loop.py — instead of adding a second per-tick hook. Does not
    call set_posture() or touch c["posture"]: these are hand actions, not
    body-posture changes.
    """
    c["animation_state"] = action_key
    c["_posture_settle"] = {
        "expected_state": action_key,
        "target_idle":    _idle_key(world, c.get("posture", "standing")),
        "ready_at_tick":  world.get("tick", 0) + ticks,
    }
