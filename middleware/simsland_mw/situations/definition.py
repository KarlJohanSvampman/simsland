"""
Situation seeds (Situation / Option Seed specification).

A SituationDefinition is a reusable *template*: when it applies, which semantic
data it needs, how it reads, and the finite choices it offers. It is not a
script -- `describe` and every option callable receive the whole
SituationContext, so the same template reads differently for a frugal
character with food in the fridge than for a hungry one who is late for work.

An OptionSeed is one choice. Exactly one of these holds:
  * `action` returns a concrete Simsland outcome (None if it is not possible
    *right now*, e.g. no fridge nearby -> the option is simply not offered);
  * `noop=True`: deliberately no Simsland action ("carry on"); the decision is
    still recorded in the character's session;
  * `gap` names a backend capability that does not exist yet. Such an option is
    never shown to the model; SituationRegistry.capability_report() lists it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple, Union

from ..contracts.reactions import (
    CompositionDefinition, CooldownDefinition, EligibilityDefinition,
    InterruptLevel, OptionDefinition, PerceptionRequirement, PersistenceMode,
    ReactionDefinition, TriggerDefinition, TriggerType,
)
from ..data.resolver import Resolution
from ..decisions.options import DecisionContext

Outcome = Dict[str, Any]

_TRIGGER_TYPE_VALUES = {t.value for t in TriggerType}


@dataclass
class SituationContext:
    """Everything a trigger, description or option seed may read."""
    dc: DecisionContext
    wake_reason: Optional[str]
    wake_payload: Dict[str, Any]
    tick: int
    state: Dict[str, Any]           # per-character situation state (cooldowns, armed thresholds)

    @property
    def res(self) -> Resolution:
        return self.dc.res

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted lookup: 'character.needs.body.hunger' -> res['character.needs']['body']['hunger']."""
        parts = path.split(".")
        for i in range(len(parts), 0, -1):
            key = ".".join(parts[:i])
            if key in self.res.values:
                cur: Any = self.res.values[key]
                for p in parts[i:]:
                    cur = cur.get(p) if isinstance(cur, dict) else None
                return default if cur is None else cur
        return default

    def person(self, pid: Optional[str]) -> Optional[Dict[str, Any]]:
        return next((p for p in self.dc.people if p["id"] == pid), None)

    def name(self, pid: Optional[str]) -> str:
        rel = self.dc.relationships.get(pid or "") or {}
        return rel.get("name") or (self.person(pid) or {}).get("name") or "someone"


@dataclass(frozen=True)
class Trigger:
    type: str                       # condition | threshold_crossed | event | idle | custom
    condition: Optional[str] = None            # "path op literal [&& ...]"
    field: Optional[str] = None                # threshold_crossed: dotted path
    threshold: Optional[float] = None
    event: Optional[str] = None                # event: the wake reason
    when: Optional[Callable[[SituationContext], bool]] = None   # extra guard / custom predicate
    key: Optional[Callable[[SituationContext], str]] = None     # cooldown scope ("this room", "this person")


@dataclass(frozen=True)
class OptionSeed:
    id: str
    description: Union[str, Callable[[SituationContext], str]]
    action: Optional[Callable[[SituationContext], Optional[Outcome]]] = None
    noop: bool = False
    gap: Optional[str] = None
    # A line the character says if the model supplies none (speech-type options only).
    default_line: Optional[Callable[[SituationContext], str]] = None
    speech_act: Optional[str] = None
    speaks: bool = False                       # LLM-authored `speech` is accepted for this option
    min_age: int = 0                           # never offered to anyone younger
    thought: bool = True                       # the reply's `thought` is kept in the session


@dataclass(frozen=True)
class SituationDefinition:
    """This IS the spec's ReactionDefinition (Spec A section 42) -- its
    concrete, working authoring form, not a class alongside it. interrupt_level/
    persistence/perception are the canonical fields it was genuinely missing;
    every one of them is Optional with a real, computed (not arbitrary)
    default via effective_interrupt_level()/effective_persistence() below, so
    none of the 30+ existing situations need to change to gain them. See
    as_reaction_definition() for the fully explicit canonical shape when
    something wants it (debugging, capability_report()-style audits)."""
    id: str
    category: str
    priority: int                              # provisional; tune in simulation testing
    triggers: Tuple[Trigger, ...]
    required_data: Tuple[str, ...]
    describe: Callable[[SituationContext], str]
    options: Tuple[OptionSeed, ...]
    cooldown_ticks: int = 1800                 # 1 tick = 1 sim second -> 30 sim minutes
    min_options: int = 2
    notes: str = ""
    # Options that depend on the character (one per pressing intention, ...).
    # They come first; `ordered` keeps them in the order given (priority) rather
    # than sampling when there are more than fit.
    dynamic_options: Optional[Callable[[SituationContext], Tuple[OptionSeed, ...]]] = None
    ordered: bool = False

    # ---- canonical fields added for Spec A (see simsland_mw/contracts/reactions.py) ----
    interrupt_level: Optional[InterruptLevel] = None    # None -> effective_interrupt_level() infers from priority
    persistence: Optional[PersistenceMode] = None        # None -> effective_persistence() infers from cooldown_ticks
    perception: Optional[PerceptionRequirement] = None    # only meaningful for an "event" trigger; None for condition/idle/etc.
    subcategory: str = ""
    composition: Optional[CompositionDefinition] = None

    MAX_OPTIONS = 6

    def effective_interrupt_level(self) -> InterruptLevel:
        """Spec section 49's own worked examples bucket by real-world
        urgency, which this codebase's priority scale (0-100, already
        tuned per-situation in simulation testing) already tracks closely
        enough to infer from directly rather than requiring a second,
        parallel number to be authored and kept in sync."""
        if self.interrupt_level is not None:
            return self.interrupt_level
        if self.priority >= 90:
            return InterruptLevel.CRITICAL
        if self.priority >= 70:
            return InterruptLevel.HIGH
        if self.priority >= 40:
            return InterruptLevel.NORMAL
        return InterruptLevel.BACKGROUND

    def effective_persistence(self) -> PersistenceMode:
        """A long cooldown already means "this kind of thing doesn't need
        re-litigating every few minutes" -- the same real signal spec
        section 87 uses to distinguish a crash/scream (transient) from a
        broken object/water leak (persistent)."""
        if self.persistence is not None:
            return self.persistence
        return PersistenceMode.PERSISTENT if self.cooldown_ticks >= 3600 else PersistenceMode.TRANSIENT

    def as_reaction_definition(self) -> ReactionDefinition:
        """The fully explicit canonical shape (spec section 42), built
        from this SituationDefinition's real fields -- for debugging/audit
        tooling, not a second thing anything in the live pipeline actually
        consumes instead of this class."""
        return ReactionDefinition(
            id=self.id,
            category=self.category,
            subcategory=self.subcategory,
            priority=self.priority,
            persistence=self.effective_persistence(),
            interrupt_level=self.effective_interrupt_level(),
            triggers=tuple(
                TriggerDefinition(
                    type=trig.type if isinstance(trig.type, TriggerType) else (
                        TriggerType(trig.type) if trig.type in _TRIGGER_TYPE_VALUES else TriggerType.CONDITION
                    ),
                    event_types=(trig.event,) if trig.event else (),
                    condition=trig.condition,
                    threshold_field=trig.field,
                    threshold_value=trig.threshold,
                    cooldown_ticks=self.cooldown_ticks,
                )
                for trig in self.triggers
            ),
            perception=self.perception,
            required_data=self.required_data,
            eligibility=EligibilityDefinition(),
            description_template=self.id,
            options=tuple(
                OptionDefinition(id=seed.id,
                                 description=seed.description if isinstance(seed.description, str) else seed.id,
                                 action=seed.gap, requires_target=False, ends_situation=True)
                for seed in self.options
            ),
            cooldown=CooldownDefinition(duration_ticks=self.cooldown_ticks),
            composition=self.composition,
        )
