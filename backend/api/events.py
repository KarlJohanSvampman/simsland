"""
api/events.py

Read-only feed over world["events"] (offgrid_story + the 5 shared_event
encounter tiers -- see systems/offgrid.py::process_return() and
systems/events.py::create_shared_event()) for the viewer's event timeline.
Non-spatial by design: events aren't tied to a viewport radius the way
characters/props/tiles are, so this is a plain REST poll, not part of the
WS snapshot/delta protocol.
"""

from fastapi import APIRouter

from db import load_world

router = APIRouter()

# Fallback labels only -- create_shared_event() always stamps a real,
# narrated event["text"] (llm/shared_event_narration.py), so this is
# just the never-blank backstop if that's ever somehow missing.
_SHARED_EVENT_LABELS = {
    "neutral":    "crossed paths",
    "pleasant":   "had a pleasant exchange",
    "unpleasant": "had an unpleasant exchange",
    "argument":   "got into an argument",
    "conflict":   "had a real conflict",
}


def _character_name(world, char_id):
    c = world.get("characters", {}).get(char_id)
    return c.get("name", char_id) if c else (char_id or "someone")


def _format_event(world, event):
    etype = event.get("type")
    base = {"id": event.get("id"), "type": etype, "tick": event.get("tick")}

    if etype == "offgrid_story":
        name = _character_name(world, event.get("character_id"))
        story = event.get("story") or {}
        base["title"] = name
        base["summary"] = story.get("summary", "")
        return base

    if etype == "choice_made":
        name = _character_name(world, event.get("character_id"))
        choice_type = (event.get("choice_type") or "choice").replace("_", " ")
        chosen = event.get("chosen_label") or "something"
        base["title"] = f"{name} — {choice_type}"
        base["summary"] = f"{name} picked {chosen} for {choice_type}."
        return base

    # The 5 real, rolled encounter tiers (neutral/pleasant/unpleasant/
    # argument/conflict) -- systems/events.py::create_shared_event() now
    # stamps a real, narrated "text" onto the event itself (llm/
    # shared_event_narration.py), so this just surfaces that directly.
    # A negative tier also carries a real "severity" (Minor..Intense).
    names = [_character_name(world, cid) for cid in event.get("participants", [])]
    label = _SHARED_EVENT_LABELS.get(etype, (etype or "event").replace("_", " "))
    summary = event.get("text") or (f"{' and '.join(names)} {label}" if names else label.capitalize())
    title = " & ".join(names) if names else (etype or "event").replace("_", " ").title()
    severity = event.get("severity")
    if severity:
        title += f" ({severity} {etype})"
    medium = event.get("medium")
    if medium:
        title += f" [{medium}]"
    base["title"] = title
    base["summary"] = summary
    base["severity"] = severity
    base["medium"] = medium
    subcategory = event.get("subcategory")
    base["subcategory"] = subcategory.get("subcategory") if subcategory else None
    # The fuller 2-4 sentence account (llm/shared_event_narration.py),
    # when narration actually succeeded -- None for the deterministic
    # fallback (whose own "detail" is just a copy of "text", not worth
    # showing twice) or for an event created before this field existed.
    detail = event.get("detail")
    base["detail"] = detail if detail and detail != summary else None
    base["category"] = event.get("category")
    return base


@router.get("/events")
def get_events(sim_id: str = "default", limit: int = 50):
    world = load_world(sim_id)
    events = world.get("events", [])
    recent = list(reversed(events[-limit:]))  # newest-first
    return {
        "ok": True,
        "tick": world.get("tick", 0),
        "events": [_format_event(world, e) for e in recent],
    }
