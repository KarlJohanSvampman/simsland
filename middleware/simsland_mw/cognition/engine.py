"""
The GM loop for one character (spec sections 2, 11 and 13):

  DATA TYPES -> ASYNC RESOLVER -> SUBJECTIVE FILTER + SEMANTIC COMPILER ->
  OPTION GENERATOR -> LLM -> VALIDATE -> EXECUTE -> SESSION

Each stage is a separate, replaceable object; this class only sequences them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import Settings
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

MAX_ATTEMPTS = 2  # first try + one corrective retry


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
        options = compiled.options if compiled else self.generator.generate(res)
        return Prepared(char_id, wake_reason, profile, res, snapshot, options,
                        prompts.build_messages(snapshot, options,
                                               compiled.description if compiled else None),
                        tick=env.get("tick"), situation=compiled)

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
        rec.simsland_response = result.response or None

        tick = (result.response or {}).get("tick")
        if result.executed:
            self.sessions.get(char_id).record_choice(
                choice.option.id, choice.option.description, tick, choice.thought)
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
