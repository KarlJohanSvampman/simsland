"""
Subjective filter (spec section 6).

World truth -> character knowledge -> belief -> perception -> narration.
The LLM only ever gets the last layers. In particular, another character's
memories, beliefs, intentions and private thoughts NEVER reach the prompt
unless Simsland explicitly marks them observable; the character sees her own
interpretation of that person (her relationship edge) and what a bystander
could observe (where they are, what they look like they're doing).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from ..data.providers.environment import PERCEIVABLE_PERSON_KEYS
from .templates import join_natural, sentence

# Keys that must never appear in anything describing *another* character.
FORBIDDEN_OTHER_KEYS = frozenset({
    "memories", "long_term_memory", "held_beliefs", "beliefs", "mentality",
    "intentions", "active_intentions", "intention_queue", "thought", "last_thought",
    "body", "grievances", "active_lies", "diary_entries", "expectations",
})


_VARIANT_SUFFIX = re.compile(r"_(?:modern_)?[a-z]$")


def prop_name(template: str) -> str:
    """'fridge_a' -> 'fridge'; 'chair_modern_a' -> 'chair'."""
    return _VARIANT_SUFFIX.sub("", template or "").replace("_", " ")


class LeakError(AssertionError):
    pass


def sanitize_person(person: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist what one character may perceive of another."""
    return {k: person[k] for k in PERCEIVABLE_PERSON_KEYS if k in person}


def assert_no_leak(person: Dict[str, Any]) -> None:
    leaked = FORBIDDEN_OTHER_KEYS & set(person)
    if leaked:
        raise LeakError(f"private fields would reach the prompt: {sorted(leaked)}")


def describe_person_nearby(person: Dict[str, Any], known: bool) -> str:
    person = sanitize_person(person)
    assert_no_leak(person)
    name = person.get("name") if known else None
    who = name or person.get("description") or "Someone"
    bits: List[str] = []
    if person.get("activity"):
        bits.append(f"is {person['activity']}")
    else:
        bits.append("is nearby")
    if person.get("appears"):
        bits.append(f"looking {person['appears']}")
    if person.get("speaking"):
        bits.append("and is speaking")
    d = person.get("distance")
    if isinstance(d, (int, float)):
        bits.append("right next to you" if d < 2 else "close by" if d < 5 else "across the room")
    return sentence(f"{who} " + ", ".join(bits))


def describe_scene(env: Dict[str, Any], people: Iterable[Dict[str, Any]],
                   relationships: Dict[str, Dict[str, Any]], props: Iterable[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    place = env.get("room_id")
    if env.get("indoors"):
        lines.append(f"You are indoors{', in the ' + str(place) if place else ''}.")
    else:
        lines.append("You are outdoors.")
    people = list(people)
    if not people:
        lines.append("No one else is around.")
    for p in people[:5]:
        lines.append(describe_person_nearby(p, known=p.get("id") in relationships))
    names = [prop_name(p["template"]) for p in list(props)[:5] if p.get("template")]
    if names:
        lines.append("Nearby: " + join_natural(names) + ".")
    return lines
