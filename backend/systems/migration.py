import random
from brain.memory import store_memory
def classify_tier(ses): return "lower" if ses<.33 else "upper" if ses>.66 else "middle"
def update_mobility(c, world):
    hid = c.get("household_id")

    if not hid:
        return

    h = world.get(
        "households",
        {}
    ).get(
        hid,
        {}
    )
    delta=.0005*(h.get("wealth",0)/1000-.8)
    delta += .0008 if c.get("employed") else -.0015
    if c.get("health",{}).get("conditions"): delta-=.0008
    c["ses"]=max(0,min(1,c.get("ses",.5)+delta)); c["class_tier"]=classify_tier(c["ses"]); c["mobility_score"]=c.get("mobility_score",0)+delta
def consider_migration(c, world):
    update_mobility(c,world); cur=world["neighborhoods"].get(c.get("neighborhood","n1"),{"quality":.5,"cost":500})
    dissatisfaction=world["environment"].get("cost_of_living_index",1)-cur.get("quality",.5)+(.4-c.get("ses",.5))
    if dissatisfaction>.7 and random.random()<.002:
        choices=[k for k in world["neighborhoods"] if k!=c.get("neighborhood")]; new=min(choices, key=lambda n: world["neighborhoods"][n]["cost"]); old=c.get("neighborhood"); c["neighborhood"]=new
        store_memory(c,f"Moved from {old} to {new} because life felt unaffordable.",.85,["migration","money"],"migration",world["tick"])
