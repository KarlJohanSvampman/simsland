"""
core/client_view.py -- what a character looks like on its way to the browser.

The Inspector lists a character's conversations (frontend/src/main.js::_renderConversationLog) from the character the
page was sent, but it only needs the transcript when one is opened in its modal. A conversation_log entry carries every
line and the full tag reading (issues, confrontations, agreements, ...); 60 of them made up much of a whole-character
send (~90 KB), and the whole log went again every time a conversation ended.

So the page is sent a summary of each entry -- who, when, how it ended, how many lines, the light tags the list shows
-- and the modal asks GET /api/conversation/{id}?participants=<character> (api/events.py) for the full entry when it is
opened. Used by main.py::_character_patches (WebSocket deltas) and api/view.py::get_view (the first snapshot).
"""

_ENTRY_KEYS = ("id", "conv_id", "conv_ids", "with", "names", "participants", "initiator", "medium", "mediums",
               "started_tick", "ended_tick", "end_reason", "topic", "subject", "tone", "issue_ids", "interaction_tags")
_TAG_KEYS = ("subject", "opening", "tags", "interaction_tags", "tone", "relates_to", "initiative_response")


def summarize_entry(entry):
    if not isinstance(entry, dict):
        return entry
    out = {k: entry[k] for k in _ENTRY_KEYS if k in entry}
    out["line_count"] = len(entry.get("lines") or [])
    out["summary_only"] = True                     # the page fetches the rest when the modal opens
    t = entry.get("tags")
    if isinstance(t, dict):
        tags = {k: t[k] for k in _TAG_KEYS if k in t}
        conf = t.get("confrontation")
        if isinstance(conf, dict):
            tags["confrontation"] = {"type": conf.get("type"), "outcome": conf.get("outcome")}
        if t.get("agreement"):
            tags["agreement"] = {"title": (t["agreement"] or {}).get("title") if isinstance(t["agreement"], dict) else None}
        out["tags"] = tags
    return out


def client_value(key, value):
    """The value of character field `key` as the browser gets it."""
    if key == "conversation_log" and isinstance(value, list):
        return [summarize_entry(e) for e in value]
    return value


def client_character(c, skip=()):
    return {k: client_value(k, v) for k, v in c.items() if k not in skip}
