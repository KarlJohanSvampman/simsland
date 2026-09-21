"""Decision profiles (demand-driven data, spec 7.3) and prompt assembly."""

from __future__ import annotations

from typing import Dict, List, Optional

from ..decisions.options import Option
from ..narrative.compiler import ConsciousnessSnapshot

_BASE = [
    "character.identity", "character.traits", "character.needs", "character.activity",
    "character.intentions", "environment.current", "environment.nearby_characters",
    "environment.nearby_props", "environment.available_interactions", "household.members",
]
_DEEP = [
    "character.expectations", "character.recent_memories", "character.beliefs",
    "character.relationships", "character.grievances", "household.finances",
]

# A body emergency doesn't need the whole social backstory, so its prompt stays small.
PROFILES: Dict[str, List[str]] = {
    "needs": _BASE + ["character.relationships"],
    "general": _BASE + _DEEP,
    "social": _BASE + _DEEP + ["events.recent"],
}

_WAKE_TO_PROFILE = {"urgent_need": "needs", "person_entered_view": "social", "door_signal": "social"}


def profile_for(wake_reason: Optional[str]) -> str:
    return _WAKE_TO_PROFILE.get(wake_reason or "", "general")


SYSTEM_TEMPLATE = (
    "You are playing {name}, a person living in a simulated neighbourhood. "
    "Decide what {name} does next, the way {name} would -- their needs, history, feelings and "
    "relationships all matter. You can only pick from the listed choices; nothing else is possible right now.\n"
    "Reply with ONLY a JSON object of the form {{\"choice\": \"<id>\"}}, where <id> is exactly one of the "
    "ids in the list. No explanation."
)


def render_options(options: List[Option]) -> str:
    return "\n".join(f"{i}. {o.description}  [id: {o.id}]" for i, o in enumerate(options, 1))


def build_messages(snapshot: ConsciousnessSnapshot, options: List[Option]) -> List[Dict[str, str]]:
    user = snapshot.render()
    if snapshot.wake_line:
        user += "\n\nJUST NOW\n" + snapshot.wake_line
    user += "\n\nWHAT I CAN DO RIGHT NOW\n" + render_options(options)
    user += "\n\nWhat do you do?"
    return [
        {"role": "system", "content": SYSTEM_TEMPLATE.format(name=snapshot.name)},
        {"role": "user", "content": user},
    ]


def correction_message(reason: str, options: List[Option]) -> Dict[str, str]:
    ids = ", ".join(o.id for o in options)
    return {"role": "user", "content": (
        f"That reply was rejected: {reason}. Reply with ONLY a JSON object like "
        f"{{\"choice\": \"<id>\"}} using exactly one of these ids: {ids}.")}
