"""
SituationRegistry + SituationCompiler.

  wake / state  ->  TriggerEvaluator  ->  highest-priority situation that fires
                ->  compile: describe() + resolve each OptionSeed into a real
                    `Option` (or drop it: no action possible / capability gap)

If nothing fires, or too few options resolve, `select` returns None and the
engine falls back to the generic rule-based menu -- a character is never left
without a decision.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..decisions.options import DecisionContext, Option
from .definition import OptionSeed, SituationContext, SituationDefinition, Trigger
from .triggers import TriggerEvaluator


@dataclass
class CompiledSituation:
    situation: SituationDefinition
    trigger: Trigger
    ctx: SituationContext
    description: str
    options: List[Option]
    unresolved: List[Tuple[str, str]] = field(default_factory=list)   # (option id, why)

    def summary(self) -> Dict[str, Any]:
        return {"id": self.situation.id, "category": self.situation.category,
                "trigger": self.trigger.type, "options": [o.id for o in self.options],
                "unresolved": [{"option": o, "reason": r} for o, r in self.unresolved]}


class SituationRegistry:
    def __init__(self, situations: Iterable[SituationDefinition] = ()):
        self._sits: Dict[str, SituationDefinition] = {}
        self.evaluator = TriggerEvaluator()
        self._state: Dict[str, Dict[str, Any]] = {}
        for s in situations:
            self.register(s)

    def register(self, sit: SituationDefinition) -> SituationDefinition:
        if sit.id in self._sits:
            raise ValueError(f"duplicate situation id {sit.id}")
        self._sits[sit.id] = sit
        return sit

    def all(self) -> List[SituationDefinition]:
        return list(self._sits.values())

    def get(self, sid: str) -> SituationDefinition:
        return self._sits[sid]

    def required_data(self) -> List[str]:
        return sorted({d for s in self._sits.values() for d in s.required_data})

    def state_for(self, char_id: str) -> Dict[str, Any]:
        return self._state.setdefault(char_id, {})

    # ---- selection -------------------------------------------------------
    def select(self, char_id: str, dc: DecisionContext, wake_reason: Optional[str],
               wake_payload: Optional[Dict[str, Any]], tick: Optional[int],
               commit: bool = True, force: Optional[str] = None) -> Optional[CompiledSituation]:
        """`force` compiles one named situation regardless of its triggers -- the
        engine uses it so a character with nothing else to do still gets real
        things to do instead of an empty menu."""
        ctx = SituationContext(dc=dc, wake_reason=wake_reason, wake_payload=wake_payload or {},
                               tick=tick or 0, state=self.state_for(char_id))
        if force:
            sit = self._sits.get(force)
            if sit is None:
                return None
            trig = sit.triggers[0]
            compiled = self.compile(sit, trig, ctx)
            return compiled if len(compiled.options) >= sit.min_options else None
        eligible: List[Tuple[SituationDefinition, Trigger]] = []
        for sit in self._sits.values():
            missing = [d for d in sit.required_data if d not in dc.res.values]
            if missing:
                continue
            try:
                trig = self.evaluator.match(sit, ctx)
            except Exception:                      # a broken seed must not stall a character
                continue
            if trig:
                eligible.append((sit, trig))
        eligible.sort(key=lambda st: -st[0].priority)
        for sit, trig in eligible:
            compiled = self.compile(sit, trig, ctx)
            if len(compiled.options) >= sit.min_options:
                if commit:
                    self.evaluator.commit(sit, trig, ctx)
                return compiled
        return None

    # ---- compilation -----------------------------------------------------
    def compile(self, sit: SituationDefinition, trig: Trigger, ctx: SituationContext) -> CompiledSituation:
        options: List[Option] = []
        unresolved: List[Tuple[str, str]] = []
        seen_outcomes = set()
        for i, seed in enumerate(sit.options):
            if seed.gap:
                unresolved.append((seed.id, f"missing backend capability: {seed.gap}"))
                continue
            outcome: Optional[Dict[str, Any]] = None
            if not seed.noop:
                try:
                    outcome = seed.action(ctx) if seed.action else None
                except Exception as e:
                    unresolved.append((seed.id, f"resolver error: {type(e).__name__}"))
                    continue
                if outcome is None:
                    unresolved.append((seed.id, "not possible right now"))
                    continue
                sig = json.dumps(outcome, sort_keys=True, default=str)
                if sig in seen_outcomes:            # two seeds that resolve to the same act
                    continue
                seen_outcomes.add(sig)
            if outcome and self._restarts_current(ctx, outcome):
                unresolved.append((seed.id, "already doing this"))
                continue
            desc = seed.description(ctx) if callable(seed.description) else seed.description
            speech = None
            if seed.speaks and outcome and outcome.get("type") in ("speak", "socialize"):
                line = seed.default_line(ctx) if seed.default_line else None
                if line:
                    outcome = {**outcome, "utterance": line}
                    speech = {"utterance": line, "speech_act": seed.speech_act or "say",
                              "target": outcome.get("target")}
            options.append(Option(seed.id, desc, outcome, speech=speech,
                                  priority=sit.priority - i, kind="situation",
                                  speaks=seed.speaks, situation=sit.id))
        options = self._trim(options, random.Random(f"{ctx.tick}:{sit.id}"))
        return CompiledSituation(sit, trig, ctx, sit.describe(ctx), options, unresolved)

    PROP_ACTIONS = ("interact", "sleep", "sit_down", "eat", "lie_down")

    @classmethod
    def _restarts_current(cls, ctx: SituationContext, outcome: Dict[str, Any]) -> bool:
        """Choosing it would restart the very activity the character is in the
        middle of (re-picking "use the toilet" while on it resets its progress)."""
        act = ctx.dc.activity
        return bool(act.get("type") and outcome.get("type") in cls.PROP_ACTIONS
                    and outcome.get("target") and act.get("target_id") == outcome["target"])

    @staticmethod
    def _trim(options: List[Option], rng: random.Random) -> List[Option]:
        """At most MAX_OPTIONS. Deliberate no-ops always survive; the rest are
        sampled, so a situation with many possible things to do doesn't offer the
        same first few forever."""
        cap = SituationDefinition.MAX_OPTIONS
        if len(options) <= cap:
            return options
        keep = [o for o in options if o.outcome is None]
        rest = [o for o in options if o.outcome is not None]
        picked = set(id(o) for o in rng.sample(rest, max(0, cap - len(keep))))
        return [o for o in options if o.outcome is None or id(o) in picked]

    # ---- reporting -------------------------------------------------------
    def capability_report(self) -> List[Dict[str, Any]]:
        """Every option, in every situation, that names a backend feature that
        does not exist yet -- the to-do list for the Simsland side."""
        out: Dict[str, Dict[str, Any]] = {}
        for sit in self._sits.values():
            for seed in sit.options:
                if seed.gap:
                    e = out.setdefault(seed.gap, {"capability": seed.gap, "needed_by": []})
                    e["needed_by"].append(f"{sit.id}/{seed.id}")
        return sorted(out.values(), key=lambda e: e["capability"])
