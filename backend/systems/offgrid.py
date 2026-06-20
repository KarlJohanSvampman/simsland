import random, uuid
from brain.memory import store_memory
def send_offgrid(c, world, reason, duration):
    if c.get("off_grid") or c.get("legal",{}).get("status")=="jailed": return False
    c["off_grid"]=True; c["off_grid_reason"]=reason; c["return_tick"]=world["tick"]+duration
    world.setdefault("offmap",[]).append({"character_id":c["id"],"reason":reason,"return_tick":c["return_tick"]})
    return True
def maybe_go_offgrid(c, world):
    if c.get("off_grid") or c.get("conversation"): return
    r=random.random()
    if c.get("employed") and world["calendar"]["minute_of_day"] in [480,490]: send_offgrid(c,world,"work",48)
    elif not c.get("employed") and r<0.01: send_offgrid(c,world,"job_search",20)
    elif r<0.004: send_offgrid(c,world,"shopping",18)
    elif r<0.008: send_offgrid(c,world,random.choice(["leisure","gym","cafe"]),28)
def _story(c, world, reason):
    env=world["environment"]; parts=[]; emotion="calm"; impact={"stress":0,"temp":0}; tags=[reason]
    if random.random()>0.25: parts.append(f"had a routine {reason} trip")
    else:
        if random.random()<env.get("crime_rate",.2): parts.append("saw something suspicious and felt unsafe"); emotion="fearful"; impact["stress"]+=8; tags+=["crime","fear"]
        if random.random()>env.get("traffic_safety",.7): parts.append("was delayed by a traffic scare"); emotion="annoyed"; impact["stress"]+=5; tags+=["traffic"]
        if random.random()>env.get("health_quality",.7): parts.append("felt unwell while out"); emotion="sad"; impact["stress"]+=4; tags+=["health"]
        if reason=="shopping" and random.random()<env.get("cost_of_living_index",1)-.7: parts.append("was shocked by high prices"); emotion="annoyed"; impact["stress"]+=5; tags+=["money","cost_of_living"]
        if not parts: parts.append(f"had an unexpectedly meaningful {reason} outing"); tags+=["positive"]
    return {"id":f"story_{uuid.uuid4().hex[:6]}","summary":f"{c['name']} " + " and ".join(parts) + ".","emotion":emotion,"impact":impact,"tags":tags}
def handle_return_transport(c, world):
    if c.get("transport", {}).get("mode") == "bus":

        bus_id = c["transport"]["bus_id"]

        bus = world["entities"].get(bus_id)
        if bus:
            pos = bus["components"]["position"]

            c["x"], c["y"] = pos["x"], pos["y"]

        c["transport"] = None
def process_return(c, world):
    if not c.get("off_grid") or world["tick"]<(c.get("return_tick") or 0): return
    
    reason=c.get("off_grid_reason") or "outing"; story=_story(c,world,reason)
    c["off_grid"]=False; c["off_grid_reason"]=None; c["return_tick"]=None
    c.setdefault("off_grid_story_arc",[]).append(story); c["off_grid_story_arc"]=c["off_grid_story_arc"][-8:]
    c["stress"]=max(0,min(100,c.get("stress",0)+story["impact"]["stress"]))
    if reason=="work" and c.get("employed"):
        h=world["households"].get(c["household_id"]); earned=c.get("hourly_wage",15)*8
        if h: h["wealth"]+=earned
        story["summary"] += f" Earned ${earned:.0f}."
    handle_return_transport(c, world)
    store_memory(c,story["summary"],.75,["offgrid"]+story["tags"],"offgrid_story",world["tick"],story=story)
    world.setdefault("events",[]).append({"id":story["id"],"type":"offgrid_story","character_id":c["id"],"tick":world["tick"],"story":story})
