import uuid, random
from brain.memory import store_memory
def create_911_call(world, caller, emergency_type, report):
    call={"id":f"call_{uuid.uuid4().hex[:6]}","type":emergency_type,"caller":caller["id"],"location":{"x":caller["x"],"y":caller["y"]},"report":report,"status":"pending","tick":world["tick"]}
    world.setdefault("calls",[]).append(call); store_memory(caller,f"Called 911: {report}",.8,["911",emergency_type],"emergency",world["tick"])
    return call
def trigger_incident(world,c):
    if c.get("emotional_temperature",0)>92 and random.random()<.02:
        world.setdefault("incidents",[]).append({"id":f"inc_{uuid.uuid4().hex[:6]}","type":"domestic_disturbance","participants":[c["id"]],"location":{"x":c["x"],"y":c["y"]},"reported":False,"tick":world["tick"]})
    if random.random()<.0008:
        world.setdefault("incidents",[]).append({"id":f"inc_{uuid.uuid4().hex[:6]}","type":"injury","participants":[c["id"]],"location":{"x":c["x"],"y":c["y"]},"reported":False,"tick":world["tick"]})
        c["health"].setdefault("conditions",[]).append({"id":"injury","symptoms":["pain","fatigue"],"curable":True,"treated":False})
def auto_report_incidents(world):
    for inc in world.get("incidents",[]):
        if inc.get("reported"): continue
        caller=world["characters"][inc["participants"][0]]
        if inc["type"]=="domestic_disturbance" and random.random()<.2:
            create_911_call(world,caller,"police","There is a serious disturbance and someone may get hurt."); inc["reported"]=True
        elif inc["type"]=="injury" and random.random()<.4:
            create_911_call(world,caller,"medical","Someone is injured and needs help."); inc["reported"]=True
def dispatch(world):
    for call in world.get("calls",[]):
        if call["status"]=="pending":
            world.setdefault("responders",[]).append({"id":f"resp_{uuid.uuid4().hex[:6]}","type":call["type"],"call_id":call["id"],"location":call["location"],"status":"en_route","arrival_tick":world["tick"]+8})
            call["status"]="dispatched"
def resolve(world):
    for r in world.get("responders",[]):
        if r["status"]=="en_route" and world["tick"]>=r["arrival_tick"]:
            r["status"]="resolved"
            if r["type"]=="police":
                for c in world["characters"].values():
                    if abs(c["x"]-r["location"]["x"])+abs(c["y"]-r["location"]["y"])<4: c["emotional_temperature"]=max(0,c.get("emotional_temperature",20)-20)
            elif r["type"]=="medical":
                for c in world["characters"].values():
                    if abs(c["x"]-r["location"]["x"])+abs(c["y"]-r["location"]["y"])<4: c["health"]["treatment"]="first_response"
