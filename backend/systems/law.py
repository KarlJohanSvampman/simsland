import random, uuid
from brain.memory import store_memory
def schedule_trial(c, world, crime):
    case={"id":f"case_{uuid.uuid4().hex[:6]}","character_id":c["id"],"crime":crime,"trial_tick":world["tick"]+40,"status":"scheduled"}
    world.setdefault("court_cases",[]).append(case); c["legal"]["status"]="awaiting_trial"; c["legal"]["trial_tick"]=case["trial_tick"]
    store_memory(c,f"Was charged with {crime} and scheduled for trial.",.9,["law","trial"],"legal",world["tick"])
def maybe_arrest_from_incidents(world):
    for inc in world.get("incidents",[]):
        if inc.get("arrest_checked"): continue
        inc["arrest_checked"]=True
        if inc["type"] in ["domestic_disturbance","crime"] and random.random()<world["environment"].get("crime_solve_rate",.5):
            for cid in inc.get("participants",[])[:1]:
                c=world["characters"].get(cid)
                if c and c["legal"]["status"]=="free": schedule_trial(c,world,inc["type"])
def process_trials(world):
    for case in list(world.get("court_cases",[])):
        if world["tick"]<case["trial_tick"] or case.get("status")!="scheduled": continue
        c=world["characters"].get(case["character_id"])
        if not c: continue
        guilty=random.random()<world["environment"].get("crime_solve_rate",.5)
        if guilty:
            c["legal"]["status"]="jailed"; c["legal"]["jail_until"]=world["tick"]+80; c["off_grid"]=True; c["off_grid_reason"]="jail"; c["status"]["reputation"]-=.25; c["legal"].setdefault("record",[]).append({"crime":case["crime"],"tick":world["tick"]})
            store_memory(c,f"Was found guilty of {case['crime']} and sent to jail.",.95,["law","jail","shame"],"legal",world["tick"])
        else:
            c["legal"]["status"]="free"; store_memory(c,f"Was found not guilty of {case['crime']}.",.75,["law","relief"],"legal",world["tick"])
        case["status"]="resolved"
def process_jail(c, world):
    if c["legal"].get("status")=="jailed" and world["tick"]>=(c["legal"].get("jail_until") or 0):
        c["legal"]["status"]="free"; c["off_grid"]=False; c["off_grid_reason"]=None
        store_memory(c,"Was released from jail.",.9,["law","jail","release"],"legal",world["tick"])
