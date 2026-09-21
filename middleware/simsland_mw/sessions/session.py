"""
Character session (spec sections 5.6 and 10).

A cognitive working set, not a chat log and never the source of truth --
Simsland owns all world state. In Phase 1 it only remembers which options
the character recently chose; Phase 2 fills recent_thoughts /
recent_conversations / recent_interpretations.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

MAX_RECENT = 5


@dataclass
class CharacterSession:
    character_id: str
    recent_choices: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_RECENT))
    recent_thoughts: Deque[str] = field(default_factory=lambda: deque(maxlen=MAX_RECENT))
    recent_conversations: Deque[Dict[str, str]] = field(default_factory=lambda: deque(maxlen=MAX_RECENT))
    recent_interpretations: Deque[str] = field(default_factory=lambda: deque(maxlen=MAX_RECENT))
    last_cognition_time: Optional[float] = None       # wall clock, time.time()
    pending_decision: Optional[Dict[str, Any]] = None
    pending_dialogue: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def record_choice(self, option_id: str, description: str, tick: Optional[int],
                      thought: Optional[str] = None) -> None:
        self.recent_choices.append({"option_id": option_id, "description": description, "tick": tick})
        if thought:
            self.recent_thoughts.append(thought)
        self.last_cognition_time = time.time()

    def digest(self) -> List[str]:
        """Lines for 'what I'm currently thinking about' -- a condensed digest,
        not a transcript."""
        lines: List[str] = list(self.recent_thoughts)
        lines += [f"{c['summary']}" if "summary" in c else "" for c in self.recent_conversations]
        lines += list(self.recent_interpretations)
        for c in list(self.recent_choices)[-3:]:
            lines.append(f"Earlier you decided to: {c['description'][:1].lower()}{c['description'][1:]}")
        return [l for l in lines if l]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "recent_choices": list(self.recent_choices),
            "recent_thoughts": list(self.recent_thoughts),
            "recent_conversations": list(self.recent_conversations),
            "recent_interpretations": list(self.recent_interpretations),
            "last_cognition_time": self.last_cognition_time,
            "pending_decision": self.pending_decision,
            "pending_dialogue": self.pending_dialogue,
            "metadata": self.metadata,
        }
