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
        self._extra_gaps: List[Tuple[str, str, str]] = []      # (situation, what, capability)
        for s in situations:
            self.register(s)

    def register(self, sit: SituationDefinition) -> SituationDefinition:
        if sit.id in self._sits:
            raise ValueError(f"duplicate situation id {sit.id}")
        self._sits[sit.id] = sit
        return sit

    def register_gaps(self, situation_id: str, gaps: Dict[str, str]) -> None:
        """Gaps of dynamic options (one per intention type), which can't be found by
        reading the static seed list."""
        self._extra_gaps += [(situation_id, what, cap) for what, cap in gaps.items()]

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
        seeds = tuple(sit.dynamic_options(ctx)) if sit.dynamic_options else ()
        age = ctx.get("character.identity.age")
        for i, seed in enumerate(seeds + sit.options):
            if seed.min_age and age is not None and age < seed.min_age:
                unresolved.append((seed.id, f"not for someone aged {age}"))
                continue
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
                if seed.speaks:
                    # Confirmed live bug: speak_to()/socialize_with() only ever
                    # return {"type": ..., "target": pid} -- speech_act (what
                    # actually makes "challenge them" a different act from
                    # "insult them back" or "ask why") lives on the SEED, not
                    # the outcome dict, so two seeds.speaks options aimed at the
                    # same person were byte-identical to this dedup check and
                    # silently collapsed to whichever came first. Already
                    # affected social.character_approaches's greet_them/
                    # ask_how_they_are before this -- neither test nor anything
                    # else had ever caught it, since nothing asserted both
                    # speech options actually coexisted. Folding speech_act into
                    # the signature only for speaks=True seeds -- the LLM is
                    # meant to supply genuinely different words for a genuinely
                    # different social intent here, so two such seeds are never
                    # really "the same act" the way two equivalent non-speech
                    # resolutions (e.g. two seeds that both land on the same
                    # interact(fridge)) legitimately are.
                    sig = f"{sig}:{seed.speech_act}"
                elif "target" not in outcome:
                    # Same underlying reasoning as the speaks=True case just
                    # above, for a different shape: a target-less outcome
                    # (e.g. post_social_media -- {"type": "post_social_media"},
                    # nothing else) is IDENTICAL no matter which of a
                    # situation's own options resolves to it, because the real
                    # differentiation (a denial vs. an explanation, sharing
                    # vs. defending someone, ...) lives entirely in what the
                    # LLM goes on to write, same as speech_act differentiates
                    # two speaks=True seeds. Confirmed live: social_media.
                    # rumor_about_self's deny_it_publicly/explain_what_happened
                    # (and rumor_seen's share_it/defend_them) both silently
                    # collapsed to one option before this -- deliberately
                    # authored as distinct choices in the same situation, not
                    # an accidental duplicate the dedup is meant to catch.
                    sig = f"{sig}:{seed.id}"
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
                                  priority=sit.priority - len(options), kind="situation",
                                  speaks=seed.speaks, situation=sit.id))
        options = self._trim(options, random.Random(f"{ctx.tick}:{sit.id}"), sit.ordered)
        return CompiledSituation(sit, trig, ctx, sit.describe(ctx), options, unresolved)

    PROP_ACTIONS = ("interact", "sleep", "sit_down", "eat", "lie_down")

    @classmethod
    def _restarts_current(cls, ctx: SituationContext, outcome: Dict[str, Any]) -> bool:
        """Choosing it would restart the very activity the character is in the
        middle of (re-picking "use the toilet" while on it resets its progress).
        Confirmed live bug: a targetless activity (jog, sit_ups, practice_juggling,
        ...) was never caught here -- re-picking it while already mid-session
        re-scaffolds a brand new one from tick 0 every time, so it could never
        actually finish and just kept visibly restarting."""
        act = ctx.dc.activity
        if not act.get("type"):
            return False
        target = outcome.get("target")
        if target:
            return outcome.get("type") in cls.PROP_ACTIONS and act.get("target_id") == target
        return act.get("type") == outcome.get("type") and not act.get("target_id")

    @staticmethod
    def _trim(options: List[Option], rng: random.Random, ordered: bool = False) -> List[Option]:
        """At most MAX_OPTIONS. Deliberate no-ops always survive; the rest are
        sampled, so a situation with many possible things to do doesn't offer the
        same first few forever."""
        cap = SituationDefinition.MAX_OPTIONS
        if len(options) <= cap:
            return options
        keep = [o for o in options if o.outcome is None]
        rest = [o for o in options if o.outcome is not None]
        room = max(0, cap - len(keep))
        picked = set(id(o) for o in (rest[:room] if ordered else rng.sample(rest, room)))
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
        for sid, what, cap in self._extra_gaps:
            out.setdefault(cap, {"capability": cap, "needed_by": []})["needed_by"].append(f"{sid}/{what}")
        return sorted(out.values(), key=lambda e: e["capability"])
