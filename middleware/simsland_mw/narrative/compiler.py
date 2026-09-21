"""
Semantic context compiler (spec sections 5.7 and 8).

Resolved data types in, a "character consciousness snapshot" out: the same
structure the spec sketches (who I am / what I know / what I remember / ...),
written in second person, with every number already translated to meaning.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..data.resolver import Resolution
from . import perception, semantic
from .templates import humanize, join_natural, sentence

MAX_RELATIONSHIP_LINES = 3

SECTION_TITLES = OrderedDict([
    ("who", "WHO I AM"),
    ("body", "HOW I FEEL"),
    ("situation", "WHAT I KNOW ABOUT RIGHT NOW"),
    ("remember", "WHAT I REMEMBER"),
    ("believe", "WHAT I BELIEVE"),
    ("worried", "WHAT I'M WORRIED ABOUT"),
    ("want", "WHAT I WANT"),
    ("expect", "WHAT I EXPECT"),
    ("thinking", "WHAT I'M CURRENTLY THINKING ABOUT"),
])

_WAKE_LINES = {
    "heard_speech": '{speaker_name} just said to you: "{utterance}"',
    "person_entered_view": "{subject_name} has just come into view.",
    "door_signal": "You hear someone at the door -- {visitor_name} is here.",
    "activity_aborted": "You couldn't get anywhere with what you were doing and gave up on it for now.",
    "activity_finished": "You've just finished what you were doing.",
    "waiting_timed_out": "You've been waiting a while and your patience is running out.",
    "wait_ready": "What you were waiting on is ready now.",
    "provoked": "{actor_name} just {verb_phrase} you.",
}
_NEED_WAKE = {
    "hunger": "Your hunger has become hard to ignore.",
    "fatigue": "You're suddenly very aware of how tired you are.",
    "bladder": "You urgently need the bathroom.",
    "hydration": "You realize how thirsty you are.",
}


@dataclass
class ConsciousnessSnapshot:
    name: str
    sections: "OrderedDict[str, List[str]]" = field(default_factory=OrderedDict)
    wake_line: Optional[str] = None

    def render(self) -> str:
        blocks: List[str] = []
        for key, title in SECTION_TITLES.items():
            lines = self.sections.get(key) or []
            if lines:
                blocks.append(title + "\n" + "\n".join(lines))
        return "\n\n".join(blocks)


def wake_sentence(reason: Optional[str], payload: Dict[str, Any]) -> Optional[str]:
    if not reason or reason == "idle":
        return None
    if reason == "urgent_need":
        return _NEED_WAKE.get((payload or {}).get("need"))
    template = _WAKE_LINES.get(reason)
    if not template:
        return None
    try:
        return sentence(template.format(**(payload or {})))
    except (KeyError, IndexError):
        return None


def _name_for(person_id: str, relationships: Dict[str, Dict[str, Any]],
              members: List[Dict[str, Any]]) -> str:
    if person_id in relationships:
        return relationships[person_id]["name"]
    for m in members:
        if m["id"] == person_id:
            return m["name"]
    return "someone"


def compile_snapshot(res: Resolution, digest: Optional[List[str]] = None) -> ConsciousnessSnapshot:
    ident = res.get("character.identity") or {}
    traits = (res.get("character.traits") or {}).get("traits", [])
    rels = res.get("character.relationships") or {}
    members = res.get("household.members") or []
    grievances = res.get("character.grievances") or {}
    env = res.get("environment.current") or {}
    snap = ConsciousnessSnapshot(name=ident.get("name") or "the character")
    s = snap.sections

    # WHO I AM
    person = {"female": "woman", "male": "man"}.get((ident.get("sex") or "").lower(), "person")
    who = [f"You are {snap.name}"
           + (f", a {ident['age']}-year-old {person}" if ident.get("age") else "") + "."]
    if traits:
        who.append(f"You tend to be {join_natural(traits)}.")
    if members and len(members) > 1:
        others = [m["name"] for m in members if not m["is_self"]]
        who.append(f"You share a household with {join_natural(others)}.")
    emotion = (res.get("character.mood") or {}).get("emotion")
    if emotion and emotion != "neutral":
        who.append(f"Right now you're feeling {emotion}.")
    s["who"] = who

    # HOW I FEEL
    needs = res.get("character.needs")
    if needs:
        feel = [semantic.describe_body(needs["body"])]
        if needs.get("frustrated_drives"):
            feel.append(f"You've been feeling a lack of {join_natural([humanize(d) for d in needs['frustrated_drives'][:3]])} lately.")
        s["body"] = feel

    # WHAT I KNOW
    situation = [l for l in [semantic.describe_time(env)] if l]
    situation += perception.describe_scene(
        env, res.get("environment.nearby_characters") or [], rels,
        res.get("environment.nearby_props") or [])
    act = res.get("character.activity") or {}
    if act.get("type"):
        situation.append(f"You are currently {humanize(act['type'])}.")
    s["situation"] = situation

    # WHAT I REMEMBER
    s["remember"] = [f"- {m['text']}" for m in res.get("character.recent_memories") or []]

    # WHAT I BELIEVE  (own beliefs + how she sees the people around her)
    beliefs = res.get("character.beliefs") or {}
    believe = [f"- {b}" for b in beliefs.get("held", [])]
    if beliefs.get("mentality"):
        believe.append(f"- {beliefs['mentality']}")
    relevant_ids = [p["id"] for p in res.get("environment.nearby_characters") or [] if p.get("id") in rels]
    relevant_ids += [m["id"] for m in members if not m["is_self"] and m["id"] in rels and m["id"] not in relevant_ids]
    for pid in relevant_ids[:MAX_RELATIONSHIP_LINES]:
        believe.append("- " + semantic.describe_relationship(
            rels[pid]["name"], rels[pid], (grievances.get(pid) or {}).get("total", 0.0)))
    s["believe"] = believe

    # WHAT I'M WORRIED ABOUT
    worried: List[str] = []
    money = semantic.describe_money(res.get("household.finances"), traits)
    if money:
        worried.append(f"- {money}")
    for e in res.get("character.expectations") or []:
        if e["status"] == "missed" and e["frustration"] >= 0.3:
            blame = [_name_for(b, rels, members) for b in e["blame"]]
            line = f"- \"{humanize(e['id'])}\" hasn't been taken care of"
            if blame:
                line += f", and you think that's on {join_natural(blame)}"
            worried.append(line + ".")
    s["worried"] = worried

    # WHAT I WANT / EXPECT
    s["want"] = [f"- {i['reason']}" for i in res.get("character.intentions") or [] if i.get("reason")][:4]
    s["expect"] = [f"- {humanize(e['id'])} ({e['cadence']})" for e in res.get("character.expectations") or []
                   if e["status"] in ("pending", "missed")][:4]

    # WHAT I'M CURRENTLY THINKING ABOUT (session working memory, never ground truth)
    s["thinking"] = [f"- {d}" for d in (digest or [])]

    snap.wake_line = wake_sentence(env.get("wake_reason"), env.get("wake_payload") or {})
    return snap
