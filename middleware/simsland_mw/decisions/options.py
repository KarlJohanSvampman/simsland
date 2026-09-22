"""
Rule-based option generation (spec sections 4 and 4.1, migration Phase 1).

Simsland decides what is *possible*; this module turns that into the finite
menu the LLM picks from. Every option carries:

  * `description` -- the only thing the LLM ever sees, and
  * `outcome`      -- a private, concrete Simsland action (same shape
                      brain/agent_loop.py::process_decision consumes).

Rules are plain functions registered on an OptionGenerator, so adding "order
delivery" or a new social move is one function, not a prompt edit. Nothing
here calls a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ..data.resolver import Resolution
from ..narrative import semantic
from ..narrative.templates import humanize

# What each kind of prop is recognised by. Substring match on Simsland's
# interaction names, exact match on tags. Extend as templates are added.
AFFORDANCES: Dict[str, Dict[str, Sequence[str]]] = {
    "food": {"interactions": ("fridge", "pantry", "prepare_food", "cook"), "tags": ("food", "fridge")},
    "cook": {"interactions": ("cook", "prepare_food"), "tags": ()},
    "coffee": {"interactions": ("coffee",), "tags": ("coffee",)},
    "computer": {"interactions": ("computer_use",), "tags": ()},
    "toilet": {"interactions": ("toilet",), "tags": ("toilet",)},
    "water": {"interactions": ("drink", "sink", "get_water"), "tags": ("water",)},
    "sleep": {"interactions": (), "tags": ("sleepable",)},
    "seat": {"interactions": (), "tags": ("seatable",)},
    "tv": {"interactions": (), "tags": ("entertainment", "tv")},
}

SIT_REST_AT = 35  # fatigue at which "sit down and rest" is a reasonable thing to consider
MAX_CHAT_OPTIONS = 2
CHILD_AGE = 13  # matches Simsland's own age_group boundary (child < 13)


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")


@dataclass(frozen=True)
class Option:
    id: str
    description: str
    outcome: Optional[Dict[str, Any]]       # private: what Simsland is asked to do (None = carry on, no action)
    speech: Optional[Dict[str, Any]] = None  # private: templated line for speak-type options
    priority: int = 50                       # deterministic fallback + display order (never shown)
    kind: str = "generic"
    speaks: bool = False                     # a model-authored `speech` line is accepted for this option
    situation: Optional[str] = None          # id of the situation that offered it (None = legacy rules)

    def public(self) -> Dict[str, str]:
        return {"id": self.id, "description": self.description}


@dataclass
class DecisionContext:
    res: Resolution

    @property
    def body(self) -> Dict[str, Any]:
        return (self.res.get("character.needs") or {}).get("body") or {}

    @property
    def action_types(self) -> set:
        return set((self.res.get("environment.available_interactions") or {}).get("action_types") or [])

    def allowed(self, action_type: str) -> bool:
        return action_type in self.action_types

    @property
    def props(self) -> List[Dict[str, Any]]:
        return self.res.get("environment.nearby_props") or []

    @property
    def people(self) -> List[Dict[str, Any]]:
        return self.res.get("environment.nearby_characters") or []

    @property
    def relationships(self) -> Dict[str, Dict[str, Any]]:
        return self.res.get("character.relationships") or {}

    def find_prop(self, kind: str) -> Optional[Dict[str, Any]]:
        spec = AFFORDANCES[kind]
        for p in self.props:  # already sorted nearest-first
            if any(t in p["tags"] for t in spec["tags"]):
                return p
            if any(sub in i for i in p["interactions"] for sub in spec["interactions"]):
                return p
        return None

    def interaction_for(self, prop: Dict[str, Any], kind: str) -> Optional[str]:
        for i in prop["interactions"]:
            if any(sub in i for sub in AFFORDANCES[kind]["interactions"]):
                return i
        return None

    @property
    def activity(self) -> Dict[str, Any]:
        return self.res.get("character.activity") or {}

    def is_dependent(self, pid: str) -> bool:
        """A child -- in this character's care, or simply young (a neighbour's
        6-year-old) -- is never the target of a confrontation or a "did you do
        your chores" ask."""
        rel = self.relationships.get(pid) or {}
        age = rel.get("age")
        return bool(rel.get("authority_over")) or (age is not None and age < CHILD_AGE)

    def handle(self, pid: str) -> str:
        """Short, readable option-id fragment for a person (their first name)
        instead of a raw Simsland id; falls back to the id tail on a name clash."""
        name = (self.relationships.get(pid) or {}).get("name") or pid
        first = _slug(name.split()[0]) or "someone"
        clash = sum(1 for r in self.relationships.values()
                    if _slug((r.get("name") or "").split()[0] if r.get("name") else "") == first)
        return first if clash <= 1 else f"{first}_{pid[-4:]}"

    def has_intention(self, prefix: str) -> bool:
        return any((i.get("type") or "").startswith(prefix)
                   for i in self.res.get("character.intentions") or [])


Rule = Callable[[DecisionContext], List[Option]]


# ---- rules -----------------------------------------------------------------

def rule_eat(dc: DecisionContext) -> List[Option]:
    hunger = dc.body.get("hunger") or 0
    if hunger < semantic.HUNGRY_AT and not dc.has_intention("eat"):
        return []
    prop = dc.find_prop("food")
    if not prop or not dc.allowed("interact"):
        return []
    interaction = dc.interaction_for(prop, "food")
    outcome: Dict[str, Any] = {"type": "interact", "target": prop["id"]}
    if interaction:
        outcome["interaction"] = interaction
    return [Option("eat_at_home", "Look through the refrigerator and find something to eat.",
                   outcome, priority=55 + int(hunger // 2), kind="need")]


def rule_bathroom(dc: DecisionContext) -> List[Option]:
    if (dc.body.get("bladder") or 0) < semantic.BLADDER_AT or not dc.allowed("interact"):
        return []
    prop = dc.find_prop("toilet")
    if not prop:
        return []
    outcome: Dict[str, Any] = {"type": "interact", "target": prop["id"]}
    interaction = dc.interaction_for(prop, "toilet")
    if interaction:
        outcome["interaction"] = interaction
    return [Option("use_bathroom", "Go to the bathroom.", outcome,
                   priority=60 + int((dc.body.get("bladder") or 0) // 2), kind="need")]


def rule_drink(dc: DecisionContext) -> List[Option]:
    hydration = dc.body.get("hydration")
    if hydration is None or hydration > semantic.THIRSTY_AT or not dc.allowed("interact"):
        return []
    prop = dc.find_prop("water")
    if not prop:
        return []
    outcome: Dict[str, Any] = {"type": "interact", "target": prop["id"]}
    interaction = dc.interaction_for(prop, "water")
    if interaction:
        outcome["interaction"] = interaction
    return [Option("get_water", "Get something to drink.", outcome,
                   priority=50 + int((100 - hydration) // 3), kind="need")]


def rule_rest(dc: DecisionContext) -> List[Option]:
    fatigue = dc.body.get("fatigue") or 0
    out: List[Option] = []
    if fatigue >= semantic.TIRED_AT and dc.allowed("sleep"):
        bed = dc.find_prop("sleep")
        if bed:
            out.append(Option("go_to_sleep", "Lie down and go to sleep.",
                              {"type": "sleep", "target": bed["id"]},
                              priority=50 + int(fatigue // 2), kind="need"))
    if fatigue >= SIT_REST_AT and dc.allowed("sit_down"):
        seat = dc.find_prop("seat")
        if seat:
            out.append(Option("sit_and_rest", "Put things off for a bit and sit down to rest.",
                              {"type": "sit_down", "target": seat["id"]},
                              priority=30 + int(fatigue // 4), kind="need"))
    return out


def _expectation_label(e_id: str) -> str:
    return humanize(e_id)


def rule_raise_issue(dc: DecisionContext) -> List[Option]:
    """Raise an unmet expectation, or frustration, with someone present who is
    to blame for it. Utterances are templated in Phase 1 (the LLM only picks);
    Phase 2's `speech` field lets the character say it in her own words."""
    if not dc.allowed("speak"):
        return []
    here = {p["id"]: p for p in dc.people}
    out: List[Option] = []
    used = set()
    for e in dc.res.get("character.expectations") or []:
        if e["status"] != "missed" or e["frustration"] < 0.3:
            continue
        for pid in e["blame"]:
            if pid in here and pid not in used and pid in dc.relationships and not dc.is_dependent(pid):
                used.add(pid)
                name = dc.relationships[pid]["name"]
                label = _expectation_label(e["id"])
                line = f"{name}, did you {label}?"
                out.append(Option(
                    f"ask_{dc.handle(pid)}_about_{e['id']}", f"Ask {name} about it: did they {label}?",
                    {"type": "speak", "target": pid, "utterance": line},
                    speech={"utterance": line, "speech_act": "ask", "topic": label, "target": pid},
                    priority=45 + int(e["frustration"] * 20), kind="social"))
    grievances = dc.res.get("character.grievances") or {}
    for pid, g in grievances.items():
        if g["total"] >= 4 and pid in here and pid in dc.relationships and not dc.is_dependent(pid):
            name = dc.relationships[pid]["name"]
            line = f"{name}, I'm really frustrated about how things have been around here."
            out.append(Option(
                f"tell_{dc.handle(pid)}_frustrated", f"Tell {name} you're frustrated.",
                {"type": "speak", "target": pid, "utterance": line},
                speech={"utterance": line, "speech_act": "declare", "topic": "frustration", "target": pid},
                priority=40, kind="social"))
    return out


def rule_socialize(dc: DecisionContext) -> List[Option]:
    if not dc.allowed("socialize"):
        return []
    out: List[Option] = []
    for p in dc.people:
        rel = dc.relationships.get(p["id"])
        if rel and (rel.get("friendship") or 0) >= 40:
            out.append(Option(f"chat_{dc.handle(p['id'])}", f"Spend some time chatting with {rel['name']}.",
                              {"type": "socialize", "target": p["id"]}, priority=25, kind="social"))
        if len(out) >= MAX_CHAT_OPTIONS:
            break
    return out


def rule_wait(dc: DecisionContext) -> List[Option]:
    """Carrying on with nothing in particular. Deliberately NOT Simsland's
    `wait` action: that one means "waiting for <person/business/delivery>" and
    must carry a condition, and a bare idle has none. This sends no action."""
    return [Option("do_nothing_for_now", "Do nothing in particular for now and see what happens.",
                   None, priority=1, kind="idle")]


DEFAULT_RULES: List[Rule] = [rule_eat, rule_bathroom, rule_drink, rule_rest,
                             rule_raise_issue, rule_socialize, rule_wait]


def _already_doing(dc: DecisionContext, opt: Option) -> bool:
    """True when the character is already engaged in exactly this. Without it a
    character woken by an unrelated event (someone walked in, a noise) re-picks
    "get a drink" while already at the sink, and restarts it every wake."""
    act = dc.activity
    if not act.get("type") or opt.kind == "idle":
        return False
    outcome = opt.outcome or {}
    target = outcome.get("target")
    if target:
        return act.get("target_id") == target
    # Confirmed live bug: a targetless activity (jog, sit_ups, practice_juggling,
    # ...) never matched here, so a character already mid-sit-ups kept getting
    # "sit_and_rest"/etc. re-offered, and picking it again re-scaffolded a BRAND
    # NEW activity from tick 0 -- it could never actually finish, just kept
    # restarting. Same activity type, no target on either side -> already doing it.
    return act.get("type") == outcome.get("type") and not act.get("target_id")


class OptionGenerator:
    def __init__(self, rules: Optional[Iterable[Rule]] = None):
        self.rules: List[Rule] = list(rules) if rules is not None else list(DEFAULT_RULES)

    def generate(self, res: Resolution) -> List[Option]:
        dc = DecisionContext(res)
        seen: set = set()
        options: List[Option] = []
        for rule in self.rules:
            for opt in rule(dc):
                if opt.id not in seen:
                    seen.add(opt.id)
                    options.append(opt)
        options = [o for o in options if not _already_doing(dc, o)]
        options.sort(key=lambda o: -o.priority)  # stable: rule order breaks ties
        return options
