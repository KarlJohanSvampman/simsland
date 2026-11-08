"""
social/tick.py -- upkeep for social/ and the handlers that run on the main thread.

  process_social(world)   every few ticks (sim_loop's "conflicts" job): confrontations that were never said, or whose
                          conversation ended without being read; issues nobody has touched going quiet.
  "confront_requested"    a character's AI chose to confront someone (systems/action_router.py): the confrontation is
                          opened and they're woken to say it.
  "hostile_action_resolved"  a shove or a punch between people in a confrontation makes it physical.
  conversion of older saves (social/migrate.py), once.
"""

from core.event_bus import subscribe

import social.discourse   # noqa: F401 -- subscribes "social_line"
from social import confrontations as X, issues as I


def process_social(world):
    from social.migrate import migrate
    migrate(world)
    X.tick(world)
    if world.get("tick", 0) % 600 < 6:
        I.tick_dormancy(world)


def _on_confront(data, world):
    cs = world.get("characters") or {}
    c, target = cs.get(data.get("initiator_id")), cs.get(data.get("target_id"))
    if not c or not target:
        return
    conf = X.start(world, c["id"], target["id"], ctype=data.get("type"), problem=data.get("problem"),
                   desired=data.get("desired_outcome"))
    if conf:
        (c.get("wants_to_raise") or {}).pop(target["id"], None)
        from brain.cognition_scheduler import wake_character
        wake_character(c, world, "confronting", {"target_id": target["id"], "target_name": target.get("name"),
                                                 "problem": conf["problem_statement"]})


def _on_hostile(data, world):
    X.on_hostile_act(world, data.get("actor_id"), data.get("target_id"), data.get("action"))


subscribe("confront_requested", _on_confront)
subscribe("hostile_action_resolved", _on_hostile)
