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

from ..data.resolver import Resolution
from ..decisions.options import DecisionContext

Outcome = Dict[str, Any]


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

    MAX_OPTIONS = 6
