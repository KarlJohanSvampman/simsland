"""
brain/prompt_templates.py -- the decision prompt as editable templates (the Prompt Templates page,
frontend/prompt_editor.html; api/prompt_templates.py).

A character's decision prompt is two messages (brain/llm_brain.py::think):

    system   who they are to the model and how to reply   -- template "system"
    user     what they perceive, remember and feel now     -- template "user"

Each template is text with {variables}. A variable is either something worked out for this character and moment
(the narrative, the action menu, one narrative section, ...) or another template ("preamble", "reply_format"), so a
block can be edited on its own and placed where you like. VARIABLES below lists them all, with what each holds.

The defaults reproduce the prompt exactly as the code wrote it before templates. Edits are kept in
backend/prompt_templates.json -- only the templates that differ from the default -- and read again whenever the file
changes, by the core and the cognition workers alike (both see the backend folder), so a saved edit applies to the
next decision without a restart. Delete a template from the file (or press Reset on the page) for its default back.

Rendering: {name} is replaced by its value; an unknown name is left as written (the page flags it). Blank lines left
by empty variables collapse: never more than one empty line in a row, none at the start or end.
"""

import json
import os
import re
import threading

TEMPLATES_FILE = os.getenv("PROMPT_TEMPLATES_FILE",
                           os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "prompt_templates.json"))

_VAR = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _code_defaults():
    from brain import llm_brain as B
    return {
        "system": "{preamble}\n\nActions: {action_menu}\n{reply_format}{cpl_format}",
        "preamble": B._PREAMBLE,
        "reply_format": B._ENVELOPE_FORMAT,
        "user": "{narrative}\n\n{scene}\n\n{look_around}\n\n{more_actions}",
    }


# What each template is (the page shows it)
TEMPLATE_INFO = {
    "system": "The system message: how the model is to behave and reply. Sent first, every decision.",
    "preamble": "Who they are to the model -- the opening lines of the system message ({preamble}).",
    "reply_format": "The reply shape ({reply_format}). The reply is read line by line: keep the ACTION: line, and the "
                    "SAY:/THEN:/... labels as they are, or decisions stop being understood.",
    "user": "The user message: everything they perceive, remember and feel right now.",
}

# Every variable a template can use: name -> what it holds. "section_<key>" exists for each narrative section.
VARIABLES = {
    "preamble": "the preamble template",
    "reply_format": "the reply format template",
    "action_menu": "the core actions they can take, comma-separated (+ how many more via list_available_actions)",
    "cpl_format": "extra reply lines while in a managed conversation (CPL); empty otherwise",
    "narrative": "the whole narrative: wake line, staged knowledge, then every section that has something to say",
    "wake_line": "why they are thinking now (\"Anthony just said to you: ...\")",
    "staged": "what they just looked at or recalled (describe / recall results)",
    "sections": "every narrative section in order, without the wake line and staged knowledge",
    "scene": "the things and people around them, in prose (from the legal moves)",
    "look_around": "what they took stock of when they last looked around -- or the nudge to look around",
    "more_actions": "the fuller action menu, once they've asked for it (list_available_actions)",
    "character_name": "their name",
    "wake_reason": "the wake reason, as a word (heard_speech, idle, ...)",
    "mode": "\"full\" or \"brief\" -- how many narrative sections this decision got",
}

_lock = threading.Lock()
_cache = {"mtime": None, "overrides": {}}


def section_keys():
    try:
        from brain.context_builder import NARRATIVE_SECTIONS
        return [k for k, _tier, _fn in NARRATIVE_SECTIONS]
    except Exception:                                     # noqa: BLE001
        return []


def all_variables():
    out = dict(VARIABLES)
    try:
        from brain.context_builder import NARRATIVE_SECTIONS
        for k, tier, _fn in NARRATIVE_SECTIONS:
            out[f"section_{k}"] = f"narrative section \"{k}\" ({'every decision' if tier == 'core' else 'full decisions only'})"
    except Exception:                                     # noqa: BLE001
        pass
    return out


def overrides():
    """The saved edits (only what differs from the defaults), read again when the file changes."""
    try:
        mtime = os.path.getmtime(TEMPLATES_FILE)
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                with open(TEMPLATES_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                _cache["overrides"] = {k: v for k, v in (data.get("templates") or data).items()
                                       if isinstance(k, str) and isinstance(v, str)}
            except (OSError, ValueError) as exc:
                print(f"[prompt_templates] couldn't read {TEMPLATES_FILE}: {exc!r} -- using the defaults")
                _cache["overrides"] = {}
            _cache["mtime"] = mtime
        return dict(_cache["overrides"])


def templates(unsaved=None):
    """Defaults, with the saved edits on top (and `unsaved` on top of those: the page's preview)."""
    out = _code_defaults()
    out.update({k: v for k, v in overrides().items() if k in out})
    if unsaved:
        out.update({k: v for k, v in unsaved.items() if k in out and isinstance(v, str)})
    return out


def save(new_templates):
    """Keep the templates that differ from the default; a template equal to its default is dropped (reset)."""
    defaults = _code_defaults()
    keep = {k: v.replace("\r\n", "\n") for k, v in (new_templates or {}).items()
            if k in defaults and isinstance(v, str) and v.replace("\r\n", "\n") != defaults[k]}
    tmp = TEMPLATES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"templates": keep}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, TEMPLATES_FILE)
    return keep


def render_text(text, values, blocks=None, _depth=0):
    """{name} -> values[name] (or a block, itself rendered); unknown names stay as written."""
    blocks = blocks or {}

    def sub(m):
        name = m.group(1)
        if name in values:
            return str(values[name] if values[name] is not None else "")
        if name in blocks and _depth < 4:
            return render_text(blocks[name], values, blocks, _depth + 1)
        return m.group(0)
    return _VAR.sub(sub, text or "")


def tidy(text):
    """Blank lines left by empty variables: at most one empty line in a row, none at the ends."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def unknown_variables(text, blocks):
    known = set(all_variables()) | set(blocks)
    return sorted({n for n in _VAR.findall(text or "") if n not in known})


def render(name, values, unsaved=None):
    blocks = templates(unsaved)
    return tidy(render_text(blocks.get(name, ""), values, {k: v for k, v in blocks.items() if k != name}))


# ── the values, from a decision's context (brain/context_builder.py::build_context) ────────────────────────────────

def user_values(context):
    """Everything the user template can use, worked out from the context the core sent."""
    from brain import llm_brain as B
    parts = context.get("narrative_parts") or {}
    available = context.get("available_actions", {}) or {}
    scan = context.get("environment_scan")
    look = []
    if scan and scan.get("text"):
        look.append(f"What you took stock of when you last looked around:\n{scan['text']}")
    if scan and scan.get("focused"):
        look.append(scan["focused"])
    if not (scan and scan.get("text")) and any(available.get(k) for k in B._ID_ONLY_KEYS):
        look.append("There are some things nearby you haven't looked closely at — look_around to take stock, or "
                    "focus on something specific you already know about.")
    menu_cache = context.get("action_menu_cache")
    sections = parts.get("sections") or []
    values = {
        "narrative": context.get("narrative", ""),
        "wake_line": parts.get("wake_line") or "",
        "staged": "\n\n".join(parts.get("staged") or []),
        "sections": "\n\n".join(t for _k, t in sections if t),
        "scene": B._prose_scene(available) or "",
        "look_around": "\n\n".join(look),
        "more_actions": (f"Everything else you can currently do:\n{menu_cache['text']}"
                         if menu_cache and menu_cache.get("text") else ""),
        "character_name": parts.get("character_name") or "",
        "wake_reason": parts.get("wake_reason") or "",
        "mode": parts.get("mode") or "",
    }
    for k in section_keys():
        values[f"section_{k}"] = ""
    for k, t in sections:
        values[f"section_{k}"] = (values.get(f"section_{k}") + "\n\n" + t).strip() if values.get(f"section_{k}") else t
    return values


def system_values(available_actions, cpl=None):
    from brain import llm_brain as B
    extra = ""
    if cpl:
        from cpl.turns import FORMAT_LINES
        extra = FORMAT_LINES + "\n"
    return {"action_menu": B._format_action_menu(available_actions or {}), "cpl_format": extra}
