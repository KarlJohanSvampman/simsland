"""
Offline stand-in for Simsland, so the whole pipeline can be exercised (tests,
`python -m simsland_mw.cli --mock`) without Docker or Ollama.

`dinner_world()` mirrors the shapes served by backend/api/middleware_bridge.py
for the spec's running example: Kimberly is hungry, Dennis was asked to buy
groceries and didn't, money is tight.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Optional


def dinner_world() -> Dict[str, Any]:
    kim = {
        "id": "kim", "name": "Kimberly", "age": 34, "sex": "female",
        "household_id": "hh1", "building_id": "home1", "room_id": "kitchen",
        "posture": "standing",
        "traits": ["frugal", "sensitive"],
        "body": {"hunger": 78, "fatigue": 43, "hydration": 51, "bladder": 20,
                 "hygiene": 70, "sickness": 0},
        "relationships": {
            "den": {"trust": 42, "friendship": 71, "familiarity": 90, "respect": 55,
                    "labels": ["spouse"]},
        },
        "grievances": [
            {"id": "g1", "caused_by": "den", "event_type": "chore_missed",
             "severity": 6.0, "weight": 6.0, "tick": 100, "details": {}},
        ],
        "expectations": {
            "make_dinner": {"template_id": "make_dinner", "cadence": "daily",
                            "status": "pending", "frustration": 0.2, "missed_count": 0,
                            "streak": 3, "last_missed_blame": []},
            "buy_groceries": {"template_id": "buy_groceries", "cadence": "weekly",
                              "status": "missed", "frustration": 0.6, "missed_count": 2,
                              "streak": 0, "last_missed_blame": ["den"]},
        },
        "active_intentions": [
            {"type": "eat_food", "priority": 72, "reason": "You're hungry.", "source": "lt_need",
             "target_id": None},
            {"type": "expectation:make_dinner", "priority": 60,
             "reason": "Dinner is normally made around now.", "source": "expectation",
             "target_id": None},
        ],
        "memories": [
            {"id": "m1", "text": "I asked Dennis to buy groceries this morning.", "tick": 900,
             "importance": 0.7, "tags": ["request"], "kind": "shared_event", "people": ["den"]},
            {"id": "m2", "text": "Dennis said he would take care of it.", "tick": 905,
             "importance": 0.6, "tags": [], "kind": "shared_event", "people": ["den"]},
            {"id": "m3", "text": "Seriously? Again?", "tick": 990,
             "importance": 0.3, "tags": ["thought"], "kind": "thought", "people": []},
        ],
        "held_beliefs": [{"text": "Dennis doesn't take household responsibilities seriously."}],
        "long_term_memory": [],
        "dependents": [],
        "cognition": {"wake_reason": "urgent_need", "next_think_tick": 0},
    }
    den = {"id": "den", "name": "Dennis", "age": 36, "sex": "male", "household_id": "hh1"}
    fridge = {"id": "prop_fridge", "template": "fridge_a", "distance": 2,
              "tags": [], "interactions": ["open_fridge"]}
    sofa = {"id": "prop_sofa", "template": "sofa_a", "distance": 4,
            "tags": ["seatable", "sleepable"], "interactions": ["sit_chair"]}
    return {
        "tick": 1000,
        "meta": {"tick": 1000,
                 "calendar": {"hour": 18, "minute": 40, "weekday": "Tuesday"},
                 "cognition": {"wake_reason": "urgent_need", "wake_payload": {"need": "hunger"},
                               "next_think_tick": 0}},
        "character": kim,
        "environment": {
            "building_id": "home1", "room_id": "kitchen",
            "visible_people": [{"id": "den", "name": "Dennis", "distance": 3,
                                "description": "a man in a rumpled shirt", "activity": "watching TV",
                                "appears": "relaxed"}],
            "visible_props": [fridge, sofa],
        },
        "people": {"kim": {"id": "kim", "name": "Kimberly", "age": 34, "sex": "female"},
                   "den": {"id": "den", "name": den["name"], "age": 36, "sex": "male"}},
        "household": {"id": "hh1", "name": "The Holmes household", "members": ["kim", "den"],
                      "wealth": 240, "loans": {}, "bills_due": [{"name": "electricity", "amount": 90}],
                      "weekly_expenses": 410},
        "household_market": None,
        "available_actions": {
            "action_types": ["move", "speak", "interact", "wait", "eat", "sleep", "socialize",
                             "sit_down", "lie_down", "describe", "recall", "phone_call",
                             "computer_order_item"],
            "interactable_props": [fridge, sofa],
            "nearby_characters": [{"id": "den", "name": "Dennis", "distance": 3}],
            "known_contacts": [], "known_businesses": [], "open_proposals": [],
        },
    }


class MockSimClient:
    """Serves a fixed world; records what `execute` receives."""

    def __init__(self, world: Optional[Dict[str, Any]] = None):
        self.world = world or dinner_world()
        self.executed: List[Dict[str, Any]] = []
        self.snapshot_calls: List[List[str]] = []
        self.external: Dict[str, bool] = {}
        self.invalid_action: Any = None  # set to simulate Simsland rejecting an action

    async def snapshot(self, char_id: str, sections: Iterable[str]) -> Dict[str, Any]:
        sections = set(sections)
        self.snapshot_calls.append(sorted(sections))
        w = self.world
        out: Dict[str, Any] = {"tick": w["tick"]}
        for s in ("meta", "character", "environment", "household", "household_market",
                  "available_actions", "people"):
            key = {"actions": "available_actions"}.get(s, s)
            if s in sections or (s == "household_market" and "household" in sections) or \
               (s == "available_actions" and "actions" in sections) or \
               (s == "people" and sections & {"environment", "household", "character"}):
                out[key] = copy.deepcopy(w.get(key))
        return out

    async def due(self) -> Dict[str, Any]:
        return {"tick": self.world["tick"], "due": [
            {"id": cid, "wake_reason": "idle", "wake_payload": {}}
            for cid, on in self.external.items() if on]}

    async def list_characters(self) -> Dict[str, Any]:
        c = self.world["character"]
        return {"tick": self.world["tick"], "characters": [
            {"id": c["id"], "name": c["name"], "household_id": c.get("household_id"),
             "external_brain": self.external.get(c["id"], False), "due": True}]}

    async def execute(self, char_id: str, decision: Dict[str, Any],
                      wake_reason: Optional[str] = None, thought: Optional[str] = None) -> Dict[str, Any]:
        self.executed.append({"char_id": char_id, "decision": decision, "wake_reason": wake_reason,
                              "thought": thought})
        return {"ok": True, "tick": self.world["tick"],
                "activity_type": (decision.get("action") or {}).get("type"),
                "invalid_action": self.invalid_action}

    async def set_external_brain(self, char_id: str, enabled: bool) -> Dict[str, Any]:
        self.external[char_id] = enabled
        return {"id": char_id, "external_brain": enabled}

    async def aclose(self) -> None:
        return None
