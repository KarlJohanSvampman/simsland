"""
/admin/prompt_templates -- the decision prompt's templates, for the Prompt Templates page (frontend/prompt_editor.html;
brain/prompt_templates.py):

    GET  /admin/prompt_templates            the templates in use, their defaults, which are edited, what each is,
                                            every variable they can use, and the characters (for the preview)
    PUT  /admin/prompt_templates            save {"templates": {name: text}} -- a template equal to its default is
                                            dropped from the file (that's a reset); applies to the next decision
    POST /admin/prompt_templates/preview    {"char_id", "templates"?: unsaved edits, "mode"?: "brief" | "full"}: the exact
                                            messages that character would be sent right now, with every variable's
                                            value and the sizes. Works on a copy of the character: nothing changes.
"""

import copy

from fastapi import APIRouter, Body, HTTPException

from core.commands import core_only
from db import load_world, world_lock

router = APIRouter(prefix="/admin/prompt_templates", tags=["prompt-templates"])

DEFAULT_SIM_ID = "default"


def _checks(tpls):
    """What would break: unknown variables, a reply format the reply parser can't read, an empty message."""
    from brain import prompt_templates as PT
    warnings = []
    for name, text in tpls.items():
        unknown = PT.unknown_variables(text, tpls)
        if unknown:
            warnings.append(f"{name}: unknown variable(s) {', '.join('{' + u + '}' for u in unknown)} -- sent as written")
    rf = tpls.get("reply_format", "")
    if "ACTION:" not in rf:
        warnings.append("reply_format: no \"ACTION:\" line -- the reply is read by its ACTION: line; without it no "
                        "decision is understood")
    if "{reply_format}" not in tpls.get("system", "") and "ACTION:" not in tpls.get("system", ""):
        warnings.append("system: doesn't include {reply_format} -- the model won't be told how to reply")
    if not tpls.get("user", "").strip():
        warnings.append("user: empty -- the character would be told nothing about their situation")
    elif "{narrative}" not in tpls["user"] and "{sections}" not in tpls["user"] and "{section_" not in tpls["user"]:
        warnings.append("user: none of {narrative}, {sections} or a {section_...} -- the character's situation is left out")
    return warnings


@router.get("")
def get_templates():
    from brain import prompt_templates as PT
    current = PT.templates()
    defaults = PT._code_defaults()
    try:                                                  # who can be previewed
        world = load_world(DEFAULT_SIM_ID)
        characters = sorted(({"id": cid, "name": c.get("name") or cid} for cid, c in (world.get("characters") or {}).items()),
                            key=lambda x: x["name"])
    except Exception:                                     # noqa: BLE001
        characters = []
    return {"templates": current, "defaults": defaults, "characters": characters,
            "edited": sorted(k for k in current if current[k] != defaults[k]),
            "info": PT.TEMPLATE_INFO, "variables": PT.all_variables(), "sections": PT.section_keys(),
            "file": PT.TEMPLATES_FILE, "warnings": _checks(current)}


@router.put("")
def put_templates(payload: dict = Body(...)):
    from brain import prompt_templates as PT
    tpls = payload.get("templates")
    if not isinstance(tpls, dict):
        raise HTTPException(400, "send {\"templates\": {name: text}}")
    unknown = sorted(k for k in tpls if k not in PT._code_defaults())
    if unknown:
        raise HTTPException(400, f"no such template(s): {', '.join(unknown)}")
    kept = PT.save(tpls)
    return {"saved": True, "edited": sorted(kept), "warnings": _checks(PT.templates())}


@router.post("/preview")
@core_only                     # builds the character's live context, in the core where the world runs
def preview(payload: dict = Body(...)):
    from brain import prompt_templates as PT
    from brain.context_builder import build_context
    from brain.llm_brain import build_system_prompt, build_prompt, _render_history_entry
    char_id = payload.get("char_id")
    unsaved = payload.get("templates") if isinstance(payload.get("templates"), dict) else None
    mode = payload.get("mode") or "brief"
    with world_lock():
        world = load_world(DEFAULT_SIM_ID)
        chars = world.get("characters") or {}
        if char_id not in chars:
            raise HTTPException(404, f"no character '{char_id}'")
        c = copy.deepcopy(chars[char_id])                # a copy: building the context changes nothing real
        if mode == "full":
            c["_last_full_context_tick"] = None
        else:
            c["_last_full_context_tick"] = world.get("tick", 0)
        from brain.cognition_scheduler import wake_line
        context = build_context(c, world, trigger_reason=(c.get("cognition") or {}).get("wake_reason") or "idle",
                                wake_line=wake_line(c), staged=(c.get("cognition") or {}).get("staged_knowledge") or ())
        try:
            from cpl.turns import context_block
            block = context_block(world, c)
            if block:
                context["cpl"] = block
        except Exception:                                 # noqa: BLE001
            pass
        history = list(((c.get("_llm_session") or {}).get("history") or [])[-6:])
    tpls = PT.templates(unsaved)
    system = build_system_prompt(context.get("available_actions") or {}, context.get("cpl"), unsaved)
    user = build_prompt(context, unsaved)
    if context.get("cpl"):
        from cpl.turns import prompt_section
        user = user + "\n\n" + prompt_section(context["cpl"])
    messages = [{"role": "system", "content": system}]
    if history:
        messages.append({"role": "system", "content": "Your recent turns:\n" + "\n".join(
            _render_history_entry(h) for h in history)})
    messages.append({"role": "user", "content": user})
    values = dict(PT.user_values(context), **PT.system_values(context.get("available_actions") or {},
                                                              context.get("cpl")))
    for name in ("preamble", "reply_format"):
        values[name] = tpls.get(name, "")
    return {"char_id": char_id, "name": chars[char_id].get("name"), "mode": (context.get("narrative_parts") or {}).get("mode"),
            "messages": [dict(m, chars=len(m["content"])) for m in messages],
            "total_chars": sum(len(m["content"]) for m in messages),
            "approx_tokens": round(sum(len(m["content"]) for m in messages) / 4),
            "values": {k: {"chars": len(str(v or "")), "text": str(v or "")} for k, v in values.items()},
            "warnings": _checks(tpls)}
