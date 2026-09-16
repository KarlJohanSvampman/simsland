import random, uuid
from brain.memory import store_memory


def _location_name(world, location_id):
    if not location_id:
        return None
    building = next((b for b in world.get("buildings", []) if b.get("id") == location_id), None)
    return (building or {}).get("name") or (building or {}).get("template")


def create_shared_event(world, participants, event_type, location_id=None):
    event={"id":f"evt_{uuid.uuid4().hex[:8]}","type":event_type,"participants":participants,"location_id":location_id,"tick":world["tick"]}
    world.setdefault("shared_events",[]).append(event)
    events = world.setdefault("events", [])
    events.append(event)
    del events[:-300]  # world["events"] otherwise grows forever

    # Real, freely-narrated semantic account (who/where/what/remarkable
    # detail) -- per the user's explicit ask, no pre-rolled outcome/
    # severity mechanic constraining it (removed entirely, see the
    # session history: it was also the reason "accident" was the only
    # outcome type that could ever become a Notable Story, a keyword-
    # match accident rather than a designed one).
    from llm.shared_event_narration import generate_shared_event_narration
    characters = world.get("characters", {})
    participant_names = [characters[cid]["name"] for cid in participants if cid in characters]
    narration = generate_shared_event_narration(
        world, event, participant_names, _location_name(world, location_id)
    )
    # Stamped onto the event itself too (not just each participant's own
    # memory) so api/events.py's timeline feed can show the real
    # narration instead of a generic label.
    event["text"] = narration["text"]
    event["topic"] = narration.get("topic")

    for cid in participants:
        c = characters.get(cid)
        if not c:
            continue
        store_memory(
            c, narration["text"], .8,
            ["shared_event", event_type],
            "shared_event", world["tick"], event_id=event["id"],
            detail=narration.get("detail"), topic=narration.get("topic"),
            # Real category from the ACTUAL generated content, not a
            # keyword-match gamble against a flat template string --
            # every event now has a fair shot at becoming a real
            # Notable Story on its own real merits.
            story_category=narration.get("category"), story_value=.8,
        )
    return event
def maybe_generate_shared_event(world):
    if random.random()>.01: return
    active=[c for c in world["characters"].values() if not c.get("off_grid") and c.get("legal",{}).get("status")!="jailed"]
    if len(active)>=2:
        # world has no top-level "locations" registry (only "buildings"); source
        # the location_id from there and degrade to None if there's nothing to pick.
        buildings=world.get("buildings") or []
        location_id=random.choice(buildings)["id"] if buildings else None
        pair=random.sample(active,2)
        create_shared_event(world,[p["id"] for p in pair],random.choice(["store_encounter","cafe_meet","street_argument","gym_incident"]),location_id)
