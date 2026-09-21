"""
Outcome execution. Maps a validated Choice back to the private Simsland
action and applies it through the bridge's /execute route (which runs the
normal validate_action -> route_action path inside Simsland).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..simulation.client import SimulationClient
from .validator import Choice


@dataclass
class ExecutionResult:
    executed: bool
    decision: Dict[str, Any]
    response: Dict[str, Any] = field(default_factory=dict)

    @property
    def invalid_action(self) -> Optional[Any]:
        return self.response.get("invalid_action")


def build_decision(choice: Choice) -> Dict[str, Any]:
    """The 'legacy decision' dict brain/agent_loop.py::process_decision consumes."""
    action = dict(choice.option.outcome)
    action.setdefault("reason", choice.option.description)
    return {
        # Deliberately None: a thought would be stored as a memory by
        # process_decision. The middleware decides what persists (Phase 2).
        "thought": None,
        "action": action,
        "speech": dict(choice.option.speech) if choice.option.speech else None,
        "intention": None,
        "reflection": None,
    }


async def execute(sim: SimulationClient, char_id: str, choice: Choice,
                  wake_reason: Optional[str] = None, dry_run: bool = False) -> ExecutionResult:
    decision = build_decision(choice)
    if dry_run:
        return ExecutionResult(executed=False, decision=decision)
    response = await sim.execute(char_id, decision, wake_reason)
    return ExecutionResult(executed=True, decision=decision, response=response)
