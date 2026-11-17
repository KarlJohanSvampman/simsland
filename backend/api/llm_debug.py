"""
/admin/llm -- for VR "LLM log" and "Choices & tags" (frontend/src/vrLLM.js):

    GET /admin/llm/{id}/log            every prompt sent for this character and the reply (llm/llm_client.py's
                                       per-character log, newest first): which prompt (purpose), when, how long,
                                       cached / failed; ?full=1 for the messages themselves, else sizes only
    GET /admin/llm/{id}/log/{n}        one entry in full (n = 0 is the newest)
    GET /admin/llm/{id}/choices        each decision: what was chosen from what, the tags on the character, and the
                                       ones the model said mattered (systems/choice_tags.py), newest first
"""

import time

from fastapi import APIRouter, HTTPException

from db import load_world
from core.commands import core_only

router = APIRouter(prefix="/admin/llm", tags=["llm-debug"])


def _short_purpose(p):
    p = str(p or "?")
    for pre in ("brain.", "llm.", "systems."):
        if p.startswith(pre):
            p = p[len(pre):]
    return p


def _summary(i, e):
    msgs = e.get("messages") or []
    return {"n": i, "ts": e.get("ts"), "ago_s": round(time.time() - (e.get("ts") or time.time())), "purpose": _short_purpose(e.get("purpose")),
            "elapsed_s": e.get("elapsed_s"), "cached": bool(e.get("cached")), "error": e.get("error"),
            "prompt_chars": sum(len(str(m.get("content") or "")) for m in msgs), "messages": len(msgs),
            "response_chars": len(str(e.get("response") or "")),
            "response_start": str(e.get("response") or "")[:120]}


@router.get("/{char_id}/log")
@core_only                       # the prompt log lives in the core process (llm/llm_client.py)
def llm_log(char_id: str, limit: int = 50, full: int = 0):
    from llm.llm_client import get_prompt_log
    entries = get_prompt_log(char_id)[:max(1, min(100, limit))]
    out = []
    for i, e in enumerate(entries):
        row = _summary(i, e)
        if full:
            row["messages"] = e.get("messages") or []
            row["response"] = e.get("response")
        out.append(row)
    return {"char_id": char_id, "entries": out}


@router.get("/{char_id}/log/{n}")
@core_only
def llm_log_entry(char_id: str, n: int):
    from llm.llm_client import get_prompt_log
    entries = get_prompt_log(char_id)
    if not 0 <= n < len(entries):
        raise HTTPException(404, "no such entry")
    e = entries[n]
    return dict(_summary(n, e), messages=e.get("messages") or [], response=e.get("response"))


@router.get("/{char_id}/choices")
def llm_choices(char_id: str, sim_id: str = "default", limit: int = 30):
    world = load_world(sim_id)
    c = (world.get("characters") or {}).get(char_id)
    if not c:
        raise HTTPException(404, f"no character '{char_id}'")
    tick = world.get("tick", 0)
    rows = [dict(e, ago_s=tick - e.get("tick", tick)) for e in reversed((c.get("choice_log") or [])[-max(1, min(60, limit)):])]
    from systems.personality_profile import effective_traits
    return {"char_id": char_id, "name": c.get("name"), "tags_now": effective_traits(c), "choices": rows}
