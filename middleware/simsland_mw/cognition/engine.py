"""
The GM loop for one character (spec sections 2, 11 and 13):

  DATA TYPES -> ASYNC RESOLVER -> SUBJECTIVE FILTER + SEMANTIC COMPILER ->
  OPTION GENERATOR -> LLM -> VALIDATE -> EXECUTE -> SESSION

Each stage is a separate, replaceable object; this class only sequences them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..contracts.decisions import (
    ActionRequest, ActionResult, LLMDecision, ValidatedDecision,
)
from ..contracts.situation_instance import NarrativeContext, SituationPrompt
from ..data.registry import Registry, build_default_registry
from ..data.resolver import Resolution, Resolver
from ..decisions import executor
from ..decisions.options import DecisionContext, Option, OptionGenerator
from ..situations.library import default_registry
from ..situations.registry import CompiledSituation, SituationRegistry
from ..decisions.validator import Choice, ChoiceRejected, parse_choice
from ..llm.client import LLMClient
from ..narrative.compiler import ConsciousnessSnapshot, compile_snapshot
from ..sessions.manager import SessionManager
from ..simulation.client import SimulationClient
from . import decisions as prompts

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 2
REPEAT_COOLDOWN_TICKS = 3600  # first try + one corrective retry


@dataclass
class Prepared:
    char_id: str
    wake_reason: Optional[str]
    profile: str
    resolution: Resolution
    snapshot: ConsciousnessSnapshot
    options: List[Option]
    messages: List[Dict[str, str]]
    tick: Optional[int] = None
    situation: Optional[CompiledSituation] = None
    # Real Spec A objects (contracts/situation_instance.py) -- the exact
    # narrative/options the LLM is about to see, given the canonical shape,
    # not a second prompt-building pass. Only populated when a real
    # situation compiled (options-only, generic-menu decisions have no
    # SituationInstance to narrate).
    situation_prompt: Optional[SituationPrompt] = None


@dataclass
class DecisionRecord:
    char_id: str
    wake_reason: Optional[str]
    profile: str
    waves: List[List[str]]
    errors: Dict[str, str]
    options: List[Dict[str, str]]
    prompt: List[Dict[str, str]]
    situation_id: Optional[str] = None
    unresolved: List[Dict[str, str]] = field(default_factory=list)
    thought: Optional[str] = None
    speech: Optional[str] = None
    problems: List[str] = field(default_factory=list)
    replies: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    choice_id: Optional[str] = None
    via: Optional[str] = None            # id | index | only_option | fallback
    fallback: bool = False
    executed: bool = False
    action: Optional[Dict[str, Any]] = None
    simsland_response: Optional[Dict[str, Any]] = None
    elapsed_ms: int = 0
    finished_at: float = field(default_factory=time.time)
    # Real Spec A objects (contracts/decisions.py) for the same decision --
    # LLMDecision/ValidatedDecision wrap the already-validated Choice
    # (simsland_mw/decisions/validator.py already enforces every runtime
    # invariant the spec asks for; these are the canonical shape that
    # validated Choice is carried in, not a second validation pass).
    # ActionRequest/ActionResult wrap the same executor.execute() call this
    # record's own action/simsland_response fields already come from.
    llm_decision: Optional[LLMDecision] = None
    validated_decision: Optional[ValidatedDecision] = None
    action_request: Optional[ActionRequest] = None
    action_result: Optional[ActionResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class CognitionEngine:
    def __init__(self, sim: SimulationClient, llm: LLMClient, settings: Optional[Settings] = None,
                 registry: Optional[Registry] = None, generator: Optional[OptionGenerator] = None,
                 sessions: Optional[SessionManager] = None,
                 situations: Optional[SituationRegistry] = None):
        self.sim = sim
        self.llm = llm
        self.settings = settings or Settings()
        self.resolver = Resolver(registry or build_default_registry())
        self.generator = generator or OptionGenerator()
        self.sessions = sessions or SessionManager()
        self.situations = situations if situations is not None else default_registry()

    async def prepare(self, char_id: str, wake_reason: Optional[str] = None,
                      profile: Optional[str] = None, commit: bool = False) -> Prepared:
        """Everything up to (not including) the LLM call. `commit=False` (previews)
        leaves situation cooldowns untouched."""
        profile = profile or prompts.profile_for(wake_reason)
        types = sorted(set(prompts.PROFILES[profile]) | set(self.situations.required_data()))
        res = await self.resolver.resolve(types, self.sim, char_id)
        if "character.identity" in res.errors:
            raise RuntimeError(f"cannot decide for {char_id}: {res.errors['character.identity']}")
        session = self.sessions.get(char_id)
        snapshot = compile_snapshot(res, session.digest())
        env = res.get("environment.current") or {}
        compiled = self.situations.select(
            char_id, DecisionContext(res), wake_reason or env.get("wake_reason"),
            env.get("wake_payload"), env.get("tick"), commit=commit)
        options = compiled.options if compiled else self._without_recent_repeats(
            session, self.generator.generate(res), env.get("tick"))
        if not compiled and all(o.kind == "idle" for o in options):
            # Nothing to act on: offer real things to do rather than a bare "nothing".
            compiled = self.situations.select(
                char_id, DecisionContext(res), wake_reason or env.get("wake_reason"),
                env.get("wake_payload"), env.get("tick"), commit=False,
                force="cognition.quiet_moment") or compiled
            if compiled:
                options = compiled.options
        situation_prompt = None
        if compiled:
            from ..contracts.reactions import RenderedOption
            situation_prompt = SituationPrompt(
                situation_id=compiled.situation.id,
                character_id=char_id,
                narrative=compiled.description,
                options=tuple(RenderedOption(id=o.id, description=o.description, available=True)
                              for o in options),
            )
        return Prepared(char_id, wake_reason, profile, res, snapshot, options,
                        prompts.build_messages(snapshot, options,
                                               compiled.description if compiled else None),
                        tick=env.get("tick"), situation=compiled, situation_prompt=situation_prompt)

    @staticmethod
    def _without_recent_repeats(session, options: List[Option], tick: Optional[int]) -> List[Option]:
        """Don't re-offer a confrontation/ask the character already made within
        the last hour -- otherwise the same rule re-fires on every wake and
        someone tells the same person they're frustrated every few minutes."""
        if tick is None:
            return options
        recent = {c["option_id"] for c in session.recent_choices
                  if c.get("tick") is not None and tick - c["tick"] < REPEAT_COOLDOWN_TICKS}
        kept = [o for o in options if not (o.kind == "social" and o.speech and o.id in recent)]
        return kept or options

    async def decide(self, char_id: str, wake_reason: Optional[str] = None,
                     dry_run: Optional[bool] = None, profile: Optional[str] = None) -> DecisionRecord:
        started = time.monotonic()
        dry = self.settings.dry_run if dry_run is None else dry_run
        p = await self.prepare(char_id, wake_reason, profile, commit=not dry)
        rec = DecisionRecord(
            char_id=char_id, wake_reason=wake_reason, profile=p.profile, waves=p.resolution.waves,
            errors=p.resolution.errors, options=[o.public() for o in p.options], prompt=p.messages,
            situation_id=p.situation.situation.id if p.situation else None,
            unresolved=[{"option": o, "reason": r}
                        for o, r in (p.situation.unresolved if p.situation else [])])

        choice = await self._choose(p, rec)
        result = await executor.execute(self.sim, char_id, choice, wake_reason, dry_run=dry)
        rec.executed = result.executed
        rec.action = result.decision["action"]
        rec.thought, rec.speech = choice.thought, choice.speech
        rec.problems = result.problems
        if result.problems:
            log.warning("%s: refused to send %s (%s)", char_id, choice.option.id, "; ".join(result.problems))
        rec.simsland_response = result.response or None

        tick = (result.response or {}).get("tick")
        if result.executed:
            self.sessions.get(char_id).record_choice(
                choice.option.id, choice.option.description, tick, choice.thought)

        # Real Spec A objects for this same decision (contracts/decisions.py)
        # -- built from the already-validated Choice/ExecutionResult, not a
        # second decision or a second validation pass. situation_instance_id
        # falls back to the candidate id when there's no real situation
        # (the generic rule-based menu, spec's own "background candidates"
        # path) -- a full SituationInstance lifecycle (spec section 60,
        # CREATED->PRESENTED->...->COMPLETED) is a further layer on top of
        # this, deliberately not built this pass; see module docstring.
        situation_instance_id = (
            p.situation.candidate.candidate_id if p.situation and p.situation.candidate
            else f"{char_id}:{tick or p.tick or 0}:generic_menu"
        )
        decision_id = f"decision:{char_id}:{tick or p.tick or 0}:{choice.option.id}"
        rec.llm_decision = LLMDecision(choice=choice.option.id, thought=choice.thought, speech=choice.speech)
        rec.validated_decision = ValidatedDecision(
            decision_id=decision_id, character_id=char_id, situation_instance_id=situation_instance_id,
            option_id=choice.option.id, thought=choice.thought, speech=choice.speech, validated=True,
        )
        rec.action_request = ActionRequest(
            action_id=decision_id, character_id=char_id, situation_instance_id=situation_instance_id,
            option_id=choice.option.id, action_key=(result.decision.get("action") or {}).get("type", "none"),
            target_character_id=(result.decision.get("action") or {}).get("target"),
            parameters=dict(result.decision.get("action") or {}), requested_tick=p.tick or 0,
        )
        rec.action_result = ActionResult(
            action_id=decision_id, success=result.executed and not result.problems,
            tick_started=p.tick or 0, tick_completed=tick,
            observable_result=result.response or {},
            failure_code=("ACTION_REJECTED" if result.problems else None),
            failure_reason="; ".join(result.problems) if result.problems else None,
        )

        rec.elapsed_ms = int((time.monotonic() - started) * 1000)
        rec.finished_at = time.time()
        return rec

    async def _choose(self, p: Prepared, rec: DecisionRecord) -> Choice:
        if len(p.options) == 1:  # nothing to decide; skip the model call
            rec.choice_id, rec.via = p.options[0].id, "only_option"
            return Choice(option=p.options[0], via="only_option")

        ids = [o.id for o in p.options]
        messages = list(p.messages)
        for _ in range(MAX_ATTEMPTS):
            raw = await self.llm.choose(messages, ids)
            rec.replies.append(raw)
            try:
                choice = parse_choice(raw, p.options)
            except ChoiceRejected as e:
                rec.rejections.append(str(e))
                messages = messages + [{"role": "assistant", "content": raw},
                                       prompts.correction_message(str(e), p.options)]
                continue
            rec.choice_id, rec.via = choice.option.id, choice.via
            return choice

        # The model never produced a valid selection. Degrade to the rule-based
        # best option rather than letting the character stall or invent an action.
        best = p.options[0]  # OptionGenerator sorts by priority
        rec.choice_id, rec.via, rec.fallback = best.id, "fallback", True
        return Choice(option=best, via="fallback")
