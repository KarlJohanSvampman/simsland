"""
LLMDecision and the decision/action pipeline contracts (spec sections 65-70).

simsland_mw/decisions/validator.py::Choice already enforces every LLM
runtime invariant the spec asks for (cannot invent an option, cannot call
Simsland, cannot mutate world state directly -- parse_choice() only ever
returns one of the options it was actually shown). LLMDecision/
ValidatedDecision below are the canonical shapes that Choice is adapted
into at the boundary (simsland_mw/situations/candidates.py has the small
adapter functions), not a second, independently-enforced validation path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .events import WorldLocation


@dataclass(frozen=True)
class LLMDecision:
    choice: str
    thought: Optional[str] = None
    speech: Optional[str] = None


@dataclass
class DecisionRecord:
    decision_id: str
    character_id: str
    situation_instance_id: str
    tick: int
    requested_choice: str
    thought: Optional[str] = None
    speech: Optional[str] = None
    valid: bool = True
    validation_error: Optional[str] = None
    selected_option_id: Optional[str] = None


@dataclass(frozen=True)
class ValidatedDecision:
    decision_id: str
    character_id: str
    situation_instance_id: str
    option_id: str
    thought: Optional[str] = None
    speech: Optional[str] = None
    validated: bool = True


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    character_id: str
    situation_instance_id: str
    option_id: str
    action_key: str
    target_character_id: Optional[str] = None
    target_object_id: Optional[str] = None
    target_location: Optional[WorldLocation] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    requested_tick: int = 0


# Failure codes (spec section 70)
ACTION_FAILURE_CODES = (
    "INVALID_TARGET", "CAPABILITY_UNAVAILABLE", "CHARACTER_UNAVAILABLE",
    "TARGET_UNAVAILABLE", "ACTION_REJECTED", "SIMULATION_ERROR",
    "TIMEOUT", "UNKNOWN",
)


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    success: bool
    tick_started: int
    tick_completed: Optional[int] = None
    resulting_event_ids: Tuple[str, ...] = ()
    observable_result: Dict[str, Any] = field(default_factory=dict)
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None
