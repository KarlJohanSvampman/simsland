import random, uuid
from brain.memory import store_memory
def create_shared_event(world, participants, event_type, location_id=None):
    event={"id":f"evt_{uuid.uuid4().hex[:8]}","type":event_type,"participants":participants,"location_id":location_id,"tick":world["tick"],"outcome":generate_outcome(world,event_type)}
    world.setdefault("shared_events",[]).append(event); world.setdefault("events",[]).append(event)
    for cid in participants:
        c=world["characters"].get(cid)
        if c: store_memory(c,f"Was involved in {event_type}; outcome was {event['outcome']['type']}.",.8,["shared_event",event_type,event["outcome"]["type"]],"shared_event",world["tick"],event_id=event["id"])
    return event
def generate_outcome(world,event_type):
    env=world["environment"]; r=random.random()
    if r<env.get("crime_rate",.2)*.5: return {"type":"crime","severity":random.uniform(.2,.9)}
    if r<.25: return {"type":"conflict","severity":random.uniform(.2,.8)}
    if r<.55: return {"type":"bonding","severity":random.uniform(.2,.7)}
    if r>env.get("traffic_safety",.7): return {"type":"accident","severity":random.uniform(.2,.8)}
    return {"type":"neutral","severity":.2}
def maybe_generate_shared_event(world):
    if random.random()>.01: return
    active=[c for c in world["characters"].values() if not c.get("off_grid") and c.get("legal",{}).get("status")!="jailed"]
    if len(active)>=2:
        pair=random.sample(active,2)
        create_shared_event(world,[p["id"] for p in pair],random.choice(["store_encounter","cafe_meet","street_argument","gym_incident"]),random.choice(list(world["locations"].keys())))
