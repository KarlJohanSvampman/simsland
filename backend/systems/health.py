import random
from brain.memory import store_memory
DISEASES={"flu":{"curable":True,"symptoms":["fatigue","fever","cough"],"base_duration":70,"treatment_cost":80,"med_weekly":15},"chronic_pain":{"curable":False,"symptoms":["fatigue","pain"],"base_duration":999999,"treatment_cost":120,"med_weekly":25}}
def apply_health_cost(c, world, cost):
    ins=c.get("insurance",{})
    if ins.get("health"): cost *= (1-ins.get("coverage",.5))
    h=world["households"].get(c["household_id"])
    if h: h["wealth"]-=cost
    return cost
def trigger_health_event(c, world):
    if c.get("health",{}).get("conditions"): return
    if random.random()<.0008*(1.5-world["environment"].get("health_quality",.7)):
        disease="flu" if random.random()<.85 else "chronic_pain"; d=DISEASES[disease]
        c["health"]["conditions"].append({"id":disease,"symptoms":d["symptoms"],"curable":d["curable"],"treated":False,"start_tick":world["tick"],"recovery_tick":world["tick"]+d["base_duration"]})
        store_memory(c,f"Started feeling symptoms of {disease}.",.75,["health",disease],"health",world["tick"])
def process_health(c, world):
    for cond in list(c.get("health",{}).get("conditions",[])):
        c["fatigue"]=min(100,c.get("fatigue",0)+.02*len(cond.get("symptoms",[])))
        if not cond.get("treated") and random.random()<.005:
            cost=apply_health_cost(c,world,DISEASES.get(cond["id"],{}).get("treatment_cost",100)*world["environment"].get("health_cost_index",1))
            cond["treated"]=True; c["health"]["treatment"]="doctor_visit_and_medication"
            store_memory(c,f"Went to the doctor for {cond['id']} and paid ${cost:.0f}.",.8,["health","money"],"health",world["tick"])
        if cond.get("curable") and world["tick"]>=cond.get("recovery_tick",999999):
            c["health"]["conditions"].remove(cond); c["health"]["treatment"]=None
            store_memory(c,f"Recovered from {cond['id']}.",.7,["health","recovery"],"health",world["tick"])
