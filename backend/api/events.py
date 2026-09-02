"""
api/events.py

Read-only feed over world["events"] (offgrid_story + the 4 shared_event
subtypes -- see systems/offgrid.py::process_return() and
systems/events.py::create_shared_event()) for the viewer's event timeline.
Non-spatial by design: events aren't tied to a viewport radius the way
characters/props/tiles are, so this is a plain REST poll, not part of the
WS snapshot/delta protocol.
"""

from fastapi import APIRouter

from db import load_world

router = APIRouter()

_SHARED_EVENT_LABELS = {
    "store_encounter": "ran into each other at a store",
    "cafe_meet":        "met up at a cafe",
    "street_argument":  "got into an argument on the street",
    "gym_incident":      "had an incident at the gym",
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

    # The 4 shared_event subtypes (store_encounter/cafe_meet/
    # street_argument/gym_incident) -- systems/events.py never generates a
    # summary sentence, only participants/location_id/outcome, so build a
    # one-line label here.
    names = [_character_name(world, cid) for cid in event.get("participants", [])]
    outcome = event.get("outcome") or {}
    label = _SHARED_EVENT_LABELS.get(etype, (etype or "event").replace("_", " "))
    summary = f"{' and '.join(names)} {label}" if names else label.capitalize()
    if outcome.get("type") and outcome["type"] != "neutral":
        summary += f" ({outcome['type']})"
    base["title"] = " & ".join(names) if names else (etype or "event").replace("_", " ").title()
    base["summary"] = summary
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
