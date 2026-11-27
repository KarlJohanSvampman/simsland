"""
/admin/llm -- for VR "LLM log" and "Choices & tags" (frontend/src/vrLLM.js):

    GET /admin/llm/{id}/log            every prompt sent for this character and the reply (llm/llm_client.py's
                                       per-character log, newest first): which prompt (purpose), when, how long,
                                       cached / failed; ?full=1 for the messages themselves, else sizes only
    GET /admin/llm/{id}/log/{n}        one entry in full (n = 0 is the newest)
    GET /admin/llm/{id}/choices        each decision: what was chosen from what, the tags on the character, and the
                                       ones the model said mattered (systems/choice_tags.py), newest first

For the LLM debug page (frontend/llm_debug.html):

    GET /admin/llm/all                 every logged call, all characters and the background ones, newest first: who,
                                       which prompt, what woke them, sizes (characters, tokens), time, model, errors;
                                       ?char= ?purpose= (substring) ?errors=1 ?limit= ; plus totals by prompt and by person
    GET /admin/llm/entry/{entry_id}    one call in full: every message sent and the reply, with the service's numbers
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


def _names():
    try:
        world = load_world("default")
        return {cid: c.get("name") for cid, c in (world.get("characters") or {}).items()}
    except Exception:                                   # noqa: BLE001
        return {}


def _row(e, names):
    m = e.get("meta") or {}
    msgs = e.get("messages") or []
    cid = e.get("char_id")
    return {"id": e.get("id"), "ts": e.get("ts"), "ago_s": round(time.time() - (e.get("ts") or time.time())),
            "char_id": cid, "name": names.get(cid) or (cid or "(background)"),
            "purpose": _short_purpose(e.get("purpose")), "wake_reason": e.get("wake_reason"), "tick": e.get("tick"),
            "elapsed_s": e.get("elapsed_s"), "cached": bool(e.get("cached")), "error": e.get("error"),
            "messages": len(msgs),
            "prompt_chars": e.get("prompt_chars", sum(len(str(x.get("content") or "")) for x in msgs)),
            "response_chars": e.get("response_chars", len(str(e.get("response") or ""))),
            "prompt_tokens": m.get("prompt_tokens"), "completion_tokens": m.get("completion_tokens"),
            "model": m.get("model"), "profile": e.get("profile") or m.get("profile"), "done_reason": m.get("done_reason"),
            "response_start": str(e.get("response") or "")[:140]}


@router.get("/all")
@core_only                       # the prompt log lives in the core process (llm/llm_client.py)
def llm_all(char: str = "", purpose: str = "", errors: int = 0, limit: int = 300):
    from llm.llm_client import all_prompt_entries
    names = _names()
    rows = [_row(e, names) for e in all_prompt_entries()]
    if char:
        rows = [r for r in rows if r["char_id"] == char or (char == "_background" and not r["char_id"])]
    if purpose:
        rows = [r for r in rows if purpose.lower() in (r["purpose"] or "").lower()]
    if errors:
        rows = [r for r in rows if r["error"]]

    def totals(key):
        out = {}
        for r in rows:
            t = out.setdefault(r[key] or "?", {"calls": 0, "errors": 0, "cached": 0, "prompt_chars": 0,
                                                "response_chars": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                                "seconds": 0.0})
            t["calls"] += 1
            t["errors"] += bool(r["error"])
            t["cached"] += r["cached"]
            for k in ("prompt_chars", "response_chars", "prompt_tokens", "completion_tokens"):
                t[k] += r[k] or 0
            t["seconds"] = round(t["seconds"] + (r["elapsed_s"] or 0), 2)
        return out
    return {"count": len(rows), "by_purpose": totals("purpose"), "by_character": totals("name"),
            "entries": rows[:max(1, min(2000, limit))]}


@router.get("/entry/{entry_id}")
@core_only
def llm_entry(entry_id: str):
    from llm.llm_client import find_prompt_entry
    e = find_prompt_entry(entry_id)
    if not e:
        raise HTTPException(404, "no such entry (the log keeps the last 100 calls per character)")
    msgs = e.get("messages") or []
    return dict(_row(e, _names()), meta=e.get("meta") or {},
                messages=[dict(x, chars=len(str(x.get("content") or ""))) for x in msgs],
                response=e.get("response"))


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
