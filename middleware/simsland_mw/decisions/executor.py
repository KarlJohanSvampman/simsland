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
    problems: list = field(default_factory=list)   # decisions we refused to send as-is

    @property
    def invalid_action(self) -> Optional[Any]:
        return self.response.get("invalid_action")


def build_decision(choice: Choice) -> Dict[str, Any]:
    """The 'legacy decision' dict brain/agent_loop.py::process_decision consumes."""
    opt = choice.option
    action = dict(opt.outcome) if opt.outcome else None
    speech = dict(opt.speech) if opt.speech else None
    if action is not None:
        action.setdefault("reason", opt.description)
        if choice.speech and opt.speaks and action.get("type") == "speak":
            # The model's own words replace the templated line; the act itself
            # (who, to whom, what kind) is still the option's.
            action["utterance"] = choice.speech
            speech = {**(speech or {"speech_act": "say", "target": action.get("target")}),
                      "utterance": choice.speech}
    return {
        # Deliberately None: a thought would be stored as a memory by
        # process_decision. The middleware decides what persists (Phase 2).
        "thought": None,
        "action": action,
        "speech": speech,
        "intention": None,
        "reflection": None,
    }


def check_action(action: Optional[Dict[str, Any]]) -> list:
    """An action Simsland can't act on meaningfully. `interact` needs a target;
    `wait` means "waiting for something" and needs a condition. Anything that
    fails is reported (never silently sent) and the character carries on
    without an action so their wake still clears."""
    if not action:
        return []
    problems = []
    if action.get("type") == "interact" and not action.get("target"):
        problems.append("interact without a target")
    if action.get("type") == "wait" and not (action.get("waiting_for") or action.get("condition")):
        problems.append("wait without a condition")
    return problems


async def execute(sim: SimulationClient, char_id: str, choice: Choice,
                  wake_reason: Optional[str] = None, dry_run: bool = False) -> ExecutionResult:
    decision = build_decision(choice)
    problems = check_action(decision["action"])
    if problems:
        decision["dropped_action"], decision["action"] = decision["action"], None
    if dry_run:
        return ExecutionResult(executed=False, decision=decision, problems=problems)
    response = await sim.execute(char_id, decision, wake_reason)
    return ExecutionResult(executed=True, decision=decision, response=response, problems=problems)
