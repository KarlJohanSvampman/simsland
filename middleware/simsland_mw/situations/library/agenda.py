"""
cognition.idle_agenda -- what to do with an idle moment.

When a character wakes with nothing acute going on, they are offered what is
actually on their mind: their pending intentions and expectations, most
pressing first, each mapped to a real Simsland action. The model chooses among
them with the character's traits and mood in view; it never invents an option.

Every mapping is either a real action, a deliberate no-op, or a named gap in
`INTENTION_GAPS` (reported by /situations/capabilities). Nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, interact, prop_action, socialize_with, speak_to

Resolver = Callable[[SituationContext, Dict[str, Any]], Optional[Dict[str, Any]]]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _target(ctx: SituationContext, i: Dict[str, Any]) -> Optional[str]:
    tid = i.get("target_id")
    return tid if tid and ctx.person(tid) else None


def _any_person(ctx: SituationContext, i: Dict[str, Any]) -> Optional[str]:
    tid = _target(ctx, i)
    if tid:
        return tid
    for p in ctx.dc.people:
        if p["id"] in ctx.dc.relationships and not ctx.dc.is_dependent(p["id"]):
            return p["id"]
    return None


def _with_interaction(token: str) -> Resolver:
    def resolve(ctx: SituationContext, i: Dict[str, Any]):
        if not ctx.dc.allowed("interact"):
            return None
        for p in ctx.dc.props:
            for name in p.get("interactions", []):
                if token in name:
                    return {"type": "interact", "target": p["id"], "interaction": name}
        return None
    return resolve


def _speak(default: str) -> Tuple[Resolver, Callable[[SituationContext, Dict[str, Any]], str]]:
    return (lambda c, i: speak_to(c, _any_person(c, i)),
            lambda c, i: default.format(name=c.name(_any_person(c, i))))


@dataclass(frozen=True)
class Mapping:
    phrase: str
    resolve: Optional[Resolver] = None
    noop: bool = False
    min_age: int = 0
    line: Optional[Callable[[SituationContext, Dict[str, Any]], str]] = None
    gap: Optional[str] = None


def _phone(ctx: SituationContext, i: Dict[str, Any]):
    tid = i.get("target_id")
    return act(ctx, "phone_call", target=tid) if tid else None


_apologize = _speak("{name}, I'm sorry about how things have been.")
_compliment = _speak("You look nice today, {name}.")

# intention / expectation type -> what doing something about it looks like.
MAPPINGS: Dict[str, Mapping] = {
    "eat_food": Mapping("Get something to eat.", lambda c, i: interact(c, "food")),
    "drink": Mapping("Get something to drink.", lambda c, i: interact(c, "water")),
    "use_toilet": Mapping("Use the bathroom.", lambda c, i: interact(c, "toilet")),
    "brush_teeth": Mapping("Brush your teeth.", _with_interaction("brush_teeth")),
    "wash_hands": Mapping("Wash your hands.", _with_interaction("wash_hands")),
    "sleep": Mapping("Go to bed.", lambda c, i: prop_action(c, "sleep", "sleep")),
    "exercise": Mapping("Get some exercise.", lambda c, i: act(c, "sit_ups") or act(c, "jog")),
    "creative_outlet": Mapping("Do something creative.", lambda c, i: act(c, "make_drawing")),
    "learn_something": Mapping("Look something up and learn something.", _with_interaction("computer_use")),
    "socialize": Mapping("Spend some time with them.", lambda c, i: socialize_with(c, _any_person(c, i))),
    "seek_romance": Mapping("Spend some time with someone you're drawn to.", lambda c, i: socialize_with(c, _target(c, i)),
                            min_age=16),
    "apologize": Mapping("Apologise.", _apologize[0], line=_apologize[1]),
    "compliment_looks": Mapping("Pay them a compliment.", _compliment[0], line=_compliment[1]),
    "contact_person": Mapping("Get in touch with them.", lambda c, i: _phone(c, i)),
    # expectations
    "expectation:go_to_work": Mapping("Head off to work.", lambda c, i: act(c, "work"), min_age=16),
    "expectation:make_dinner": Mapping("Cook dinner.", lambda c, i: interact(c, "cook"), min_age=14),
    "expectation:spend_time_alone": Mapping("Spend some time on your own.", noop=True),
    "expectation:relax_with_someone": Mapping("Unwind with someone.", lambda c, i: socialize_with(c, _any_person(c, i))),
    "expectation:keep_room_clean": Mapping("Tidy up your room.", lambda c, i: act(c, "clean_floors")),
    "expectation:clean_kitchen": Mapping("Clean the kitchen.", lambda c, i: act(c, "clean_floors"), min_age=10),
}

# Intention types with no Simsland action behind them yet.
INTENTION_GAPS = {
    "outdoor_time": "outdoor_activity",
    "pursue_purpose": "purpose_activity",
    "spiritual_practice": "spiritual_activity",
    "seek_intimacy": "intimacy_options",
    "gossip": "gossip_action",
    "suggest_hygiene": "suggest_hygiene_action",
    "expectation:get_kids_to_school": "school_run",
    "expectation:family_dinner_together": "family_meal_gathering",
    "expectation:file_taxes": "file_taxes_action",
    "expectation:acquire_driver_license": "driver_license_process",
}


def _agenda(ctx: SituationContext) -> List[Dict[str, Any]]:
    items = [i for i in ctx.get("character.intentions", []) or [] if i.get("type")]
    return sorted(items, key=lambda i: -(i.get("priority") or 0))


def _seeds(ctx: SituationContext) -> Tuple[O, ...]:
    seeds: List[O] = []
    seen = set()
    for i in _agenda(ctx):
        t = i["type"]
        if t in seen:
            continue
        seen.add(t)
        m = MAPPINGS.get(t)
        oid = "agenda_" + _slug(t)
        if m is None:
            seeds.append(O(oid, t.replace("_", " "), gap=INTENTION_GAPS.get(t, f"intention_action:{t}")))
            continue
        line = m.line
        seeds.append(O(
            oid, m.phrase,
            action=(lambda c, i=i, m=m: m.resolve(c, i)) if m.resolve else None,
            noop=m.noop, min_age=m.min_age,
            speaks=bool(line), speech_act="say" if line else None,
            default_line=(lambda c, i=i, line=line: line(c, i)) if line else None,
        ))
    return tuple(seeds)


def _describe(ctx: SituationContext) -> str:
    lines = ["Nothing pressing is happening. Here is what's on your mind, most pressing first:"]
    for i in _agenda(ctx)[:6]:
        if i.get("reason"):
            lines.append(f"- {i['reason']}")
    return "\n".join(lines)


IDLE_AGENDA = S(
    id="cognition.idle_agenda", category="cognition", priority=20, cooldown_ticks=0,
    triggers=(T("event", event="idle"),),
    required_data=("character.intentions", "character.identity", "character.mood",
                   "environment.available_interactions", "environment.nearby_props",
                   "environment.nearby_characters", "character.relationships"),
    describe=_describe,
    options=(
        O("just_relax_for_a_while", "Just relax for a while.", noop=True),
    ),
    dynamic_options=_seeds,
    ordered=True,
    min_options=2,
    notes="One option per pending intention/expectation, ordered by priority; unmapped types are "
          "reported as gaps (INTENTION_GAPS).",
)
