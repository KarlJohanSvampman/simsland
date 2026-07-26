"""
api/social_sandbox.py

Stateful debug tool: stage real character_templates into a synthetic
in-memory world for testing multi-character social dynamics (real LLM
conversations, off-grid narration) without touching the live simulation.

Unlike api/debug.py (deliberately stateless -- every route rebuilds a
throwaway world per request), this module keeps a sandbox's synthetic
world alive across many requests, keyed by a sandbox_id.

GET/POST endpoints are added incrementally across rounds.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.editor import load_definitions
from systems.character_gen import generate_character
from systems.schema_defaults import ensure_world_defaults, ensure_character_defaults
from brain.perception import perceived_emotion, perceived_activity
from systems.perception.descriptions import build_visible_person_description
from brain.relationships import ensure_relationship


router = APIRouter(prefix="/debug/sandbox", tags=["social_sandbox"])

# ─── State ──────────────────────────────────────────────────────────────────
# In-memory only, no locking/TTL -- single-admin dev tool, same risk profile
# already accepted by llm/llm_client.py's _PROMPT_LOG ring buffer.
_SANDBOXES: Dict[str, dict] = {}
_SANDBOX_MAX = 20

# Same 11-field override allowlist api/editor.py::_spawn_character_locked
# uses (editor.py:136-147) -- deliberately not the dead "instance" merge
# (character_creator.js never writes that key).
_TEMPLATE_OVERRIDE_FIELDS = [
    "model", "traits", "physical_traits", "hobbies", "worn",
    "starting_inventory", "job", "education", "current_school",
    "work_history", "legal", "household_id",
]


# ─── Request models ─────────────────────────────────────────────────────────

class StagedCharSpec(BaseModel):
    template_id: str
    x: float = 0.0
    y: float = 0.0


class AbsentRelSpec(BaseModel):
    name: str
    # Index into StageRequest.characters, not a character id -- ids are
    # generated inside stage_sandbox() and can't be known by the caller
    # when building a single combined request.
    relationship_to_index: int
    relation_label: str = ""
    relationship_overrides: Dict[str, Any] = {}


class StageRequest(BaseModel):
    sim_id: str = "default"
    characters: List[StagedCharSpec]
    absent: List[AbsentRelSpec] = []


# ─── World skeleton ─────────────────────────────────────────────────────────

def _new_sandbox_world(defs: dict) -> dict:
    """Mirrors api/debug.py's _WORLD_SKELETON shape, plus definitions
    stashed directly on the world (several context-builder/perception-
    description helpers read world.get("definitions", {}), not a bare
    local variable)."""
    return {
        "tick": 100,
        "calendar": {"weekday": "monday", "hour": 9, "minute": 0, "timestamp": time.time()},
        "characters": {},
        "households": {},
        "homes": {},
        "vacant_homes": [],
        "events": [],
        "props": {},
        "buildings": {},
        "rooms": {},
        "conversations": {},
        "conflicts": {},
        "social_contracts": {},
        "news_feed": [],
        "environment": {"cost_of_living_index": 1.0, "tax_rate": 0.2},
        "market": {},
        "mail": {},
        "mailboxes": {},
        "services": {},
        "businesses": {},
        "definitions": defs,
        "offmap": [],
    }


def _trimmed_view(c: dict) -> dict:
    """Curated subset for staging/turn responses -- the full ~80-key dict
    is available on demand via GET /characters/{id} (added next round)."""
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "age": c.get("age"),
        "sex": c.get("sex"),
        "traits": c.get("traits", []),
        "hobbies": c.get("hobbies", []),
        "job": c.get("job"),
        "health": c.get("health"),
        "emotion": c.get("emotion"),
        "mood": c.get("mood"),
        "x": c.get("x"),
        "y": c.get("y"),
        "template": c.get("template"),
    }


def _build_visible_people(world: dict, defs: dict, present_ids: List[str]) -> None:
    """Mutual-visibility pass: for every ordered pair of present (non-
    absent) staged characters, stamp a real visible_people entry by
    reusing the same helpers perceive() itself uses -- distance/visibility
    are fixed "close/clear" constants since the point of staging is that
    everyone is in the same room, not a real LOS/range simulation."""
    chars = world["characters"]
    for observer_id in present_ids:
        observer = chars[observer_id]
        visible_people = []
        for target_id in present_ids:
            if target_id == observer_id:
                continue
            target = chars[target_id]
            visible_people.append({
                "id": target_id,
                "name": target.get("name"),
                "distance": 1,
                "visibility": 1.0,
                "appears": perceived_emotion(observer, target),
                "activity": perceived_activity(target),
                "speaking": bool(target.get("current_speech")),
                "description": build_visible_person_description(observer, target, defs),
                "body": {
                    "odor": target.get("body", {}).get("odor", 0),
                    "mouth_hygiene": target.get("body", {}).get("mouth_hygiene", 100),
                },
            })
        observer["perception"] = {
            "visible_people": visible_people,
            "visible_props": [],
            "social_scenes": [],
            "audible_events": [],
            "environment": {},
            "news": [],
            "events": [],
            "focus": None,
        }


# ─── Staging ─────────────────────────────────────────────────────────────────

@router.post("/stage")
def stage_sandbox(req: StageRequest):
    defs = load_definitions(req.sim_id)
    world = _new_sandbox_world(defs)
    ensure_world_defaults(world, defs)

    present_ids: List[str] = []
    for spec in req.characters:
        tmpl = defs.get("character_templates", {}).get(spec.template_id)
        if not tmpl:
            raise HTTPException(status_code=404,
                                 detail=f"Character template '{spec.template_id}' not found")

        cid = f"sbx_{uuid.uuid4().hex[:8]}"
        name = tmpl.get("name") or spec.template_id.replace("_", " ").title()
        overrides = {"id": cid, "x": spec.x, "y": spec.y, "template": spec.template_id, "name": name}
        for field in _TEMPLATE_OVERRIDE_FIELDS:
            if tmpl.get(field):
                overrides[field] = tmpl[field]

        character = generate_character(defs, overrides)
        ensure_character_defaults(character)

        # generate_character()'s output has a full "job" dict but no
        # top-level "employment" key, which build_visible_person_description
        # reads ({job, company} ids) -- stamp a derived one so descriptions
        # of this character include the employment clause.
        if character.get("job"):
            character["employment"] = {
                "job": character["job"].get("id") or character["job"].get("title"),
                "company": character.get("company_id"),
            }

        world["characters"][cid] = character
        present_ids.append(cid)

    _build_visible_people(world, defs, present_ids)

    absent_summaries = []
    for spec in req.absent:
        if not (0 <= spec.relationship_to_index < len(present_ids)):
            raise HTTPException(
                status_code=404,
                detail=f"absent.relationship_to_index {spec.relationship_to_index} is out of range "
                       f"for {len(present_ids)} staged characters",
            )
        present = world["characters"][present_ids[spec.relationship_to_index]]
        stub_id = f"stub_{uuid.uuid4().hex[:8]}"
        world["characters"][stub_id] = {"id": stub_id, "name": spec.name, "alive": True}

        rel = ensure_relationship(present, stub_id)
        rel.update(spec.relationship_overrides)
        if "familiarity" not in spec.relationship_overrides:
            rel["familiarity"] = rel.get("familiarity") or 1
        if spec.relation_label:
            rel.setdefault("labels", [])
            if spec.relation_label not in rel["labels"]:
                rel["labels"].append(spec.relation_label)

        absent_summaries.append({"id": stub_id, "name": spec.name})

    sandbox_id = f"sbx_{uuid.uuid4().hex[:10]}"
    _SANDBOXES[sandbox_id] = world
    if len(_SANDBOXES) > _SANDBOX_MAX:
        oldest = next(iter(_SANDBOXES))
        del _SANDBOXES[oldest]

    return {
        "sandbox_id": sandbox_id,
        "characters": [_trimmed_view(world["characters"][cid]) for cid in present_ids],
        "absent": absent_summaries,
    }


# ─── Character fetch ────────────────────────────────────────────────────────

@router.get("/{sandbox_id}/characters/{char_id}")
def get_sandbox_character(sandbox_id: str, char_id: str):
    world = _SANDBOXES.get(sandbox_id)
    if world is None:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    character = world["characters"].get(char_id)
    if character is None:
        raise HTTPException(status_code=404, detail=f"Character '{char_id}' not in sandbox")
    return character


# ─── Turn ────────────────────────────────────────────────────────────────────
# Same fallback sections as api/debug.py::_partial_context (debug.py:192-217)
# -- duplicated rather than imported since debug.py is deliberately kept
# free of any dependency on this (stateful) module.

def _partial_context(c, world, out, errors):
    from brain.context_builder import (
        build_relationship_context, build_grievance_context,
        build_conflict_context, build_social_context,
        build_available_actions, build_intentions,
        build_memory_context, build_body_context,
    )
    sections = [
        ("identity",          lambda: {"name": c.get("name"), "traits": c.get("traits")}),
        ("internal_state",    lambda: {"emotion": c.get("emotion"), "energy": c.get("energy")}),
        ("relationships",     lambda: build_relationship_context(c, world)),
        ("grievances",        lambda: build_grievance_context(c, world)),
        ("active_conflict",   lambda: build_conflict_context(c, world)),
        ("social",            lambda: build_social_context(c, world)),
        ("available_actions", lambda: build_available_actions(c, world)),
        ("active_intentions", lambda: build_intentions(c)),
        ("memories",          lambda: build_memory_context(c)),
        ("body_state",        lambda: build_body_context(c)),
    ]
    for name, fn in sections:
        if name not in out:
            try:
                out[name] = fn()
            except Exception as e:
                errors[name] = f"{type(e).__name__}: {e}"


def _turn_view(c: dict) -> dict:
    view = _trimmed_view(c)
    view["current_speech"] = c.get("current_speech")
    view["last_thought"] = c.get("last_thought")
    return view


class TurnRequest(BaseModel):
    char_id: str


@router.post("/{sandbox_id}/turn")
async def sandbox_turn(sandbox_id: str, req: TurnRequest):
    from brain.context_builder import build_context
    from brain.llm_brain import think
    from brain.agent_loop import process_decision

    world = _SANDBOXES.get(sandbox_id)
    if world is None:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    c = world["characters"].get(req.char_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Character '{req.char_id}' not in sandbox")

    # Advance the sandbox's own clock so SPEECH_BUBBLE_TICKS expiry and
    # add_message()'s tick-stamped history behave sensibly across a
    # multi-turn conversation.
    world["tick"] = world.get("tick", 0) + 1

    context_errors: Dict[str, str] = {}
    context: Dict[str, Any] = {}
    try:
        context = build_context(c, world)
    except Exception as e:
        context_errors["build_context"] = f"{type(e).__name__}: {e}"
        _partial_context(c, world, context, context_errors)

    session = c.setdefault("_llm_session", {"history": []})
    loop = asyncio.get_event_loop()
    decision = await loop.run_in_executor(None, think, context, c["id"], session)

    action_error = None
    try:
        process_decision(c, world, decision)
    except Exception as e:
        action_error = f"{type(e).__name__}: {e}"

    conversation = None
    for conv in world.get("conversations", {}).values():
        history = conv.get("history") or []
        if (req.char_id in conv.get("participants", [])
                and history and history[-1].get("tick") == world["tick"]):
            conversation = conv
            break

    return {
        "decision": decision,
        "action_error": action_error,
        "character": _turn_view(c),
        "conversation": conversation,
        "context_errors": context_errors,
    }


# ─── Off-grid dispatcher ────────────────────────────────────────────────────

class OffgridRequest(BaseModel):
    char_id: str
    category: str  # shopping|leisure|gym|cafe|job_search|work|doctor|hospital|jail|"event:<id>"
    duration: int = 20


@router.post("/{sandbox_id}/offgrid")
def sandbox_offgrid(sandbox_id: str, req: OffgridRequest):
    from systems.offgrid import send_offgrid, process_return

    world = _SANDBOXES.get(sandbox_id)
    if world is None:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    c = world["characters"].get(req.char_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Character '{req.char_id}' not in sandbox")

    ok = send_offgrid(c, world, req.category, req.duration)
    if not ok:
        return {"ok": False, "reason": "already_off_grid_or_jailed"}

    # Fast-forward the sandbox clock to the return tick -- process_return()
    # is itself a no-op until world["tick"] reaches c["return_tick"].
    world["tick"] = c["return_tick"]
    process_return(c, world)

    story_arc = c.get("off_grid_story_arc") or []
    narration = story_arc[-1]["summary"] if story_arc else "(no story generated)"

    return {
        "ok": True,
        "narration": narration,
        "character": _turn_view(c),
    }


# ─── Character patch ────────────────────────────────────────────────────────
# Shallow + one-level-nested merge, same style as api/debug.py::_build_char
# (debug.py:108-115) -- but merged in place into the stored character dict
# rather than building a fresh one, since this is what makes State-tab edits
# persist against the real sandbox world instead of a disconnected copy.

def _apply_patch(c: dict, patch: dict) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k] = {**c[k], **v}
        else:
            c[k] = v


@router.patch("/{sandbox_id}/characters/{char_id}")
def patch_sandbox_character(sandbox_id: str, char_id: str, patch: Dict[str, Any]):
    world = _SANDBOXES.get(sandbox_id)
    if world is None:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    c = world["characters"].get(char_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Character '{char_id}' not in sandbox")
    _apply_patch(c, patch)
    return c


# ─── Family tree ────────────────────────────────────────────────────────────
# Mirrors api/editor.py::_generate_family_locked (editor.py:207-251) minus
# the lock/save_world/already-existed persistence dance -- a sandbox family
# tree doesn't need to survive beyond the session, and the real route's
# load_world(sim_id) is the persisted live world anyway, wholly disjoint
# from _SANDBOXES, so it 404s for every sandbox character today.

@router.post("/{sandbox_id}/characters/{char_id}/generate_family")
def sandbox_generate_family(sandbox_id: str, char_id: str, depth: int = 1):
    from systems.family import generate_family_for_character, get_family_summary

    world = _SANDBOXES.get(sandbox_id)
    if world is None:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    char = world["characters"].get(char_id)
    if char is None:
        raise HTTPException(status_code=404, detail=f"Character '{char_id}' not in sandbox")

    defs = world.get("definitions", {})

    if char.get("family_id"):
        fam = world.get("families", {}).get(char["family_id"])
        if fam:
            return {"ok": True, "already_existed": True, "family": get_family_summary(fam, world)}

    family = generate_family_for_character(char, world, defs, depth=depth)
    return {"ok": True, "already_existed": False, "family": get_family_summary(family, world)}
