CRISES={
 "economic_crash":{"trigger":lambda e:e.get("unemployment_rate",0)>.3 and e.get("cost_of_living_index",1)>1.3,"duration":180,"effects":{"unemployment_rate":.1,"average_salary_index":-.1}},
 "riots":{"trigger":lambda e:e.get("crime_rate",0)>.5 and e.get("social_tension",0)>.4,"duration":120,"effects":{"crime_rate":.1,"power_availability":-.05}},
 "healthcare_collapse":{"trigger":lambda e:e.get("health_quality",1)<.4 and e.get("health_cost_index",1)>1.3,"duration":150,"effects":{"health_quality":-.1,"health_cost_index":.1}}
}
def check_crises(world):
    env=world["environment"]; active={c["type"] for c in world.get("active_crises",[])}
    for name,cr in CRISES.items():
        if name not in active and cr["trigger"](env):
            world.setdefault("active_crises",[]).append({"type":name,"start_tick":world["tick"],"end_tick":world["tick"]+cr["duration"],"phase":"active","recovery_progress":0})
            for k,d in cr["effects"].items(): env[k]=max(0,min(2,env.get(k,0)+d))
            world.setdefault("news",[]).append({"id":f"news_crisis_{world['tick']}","type":"crisis","headline":f"{name.replace('_',' ').title()} unfolding","summary":"Major disruption affects society.","sentiment":"negative","intensity":1,"tags":["crisis"],"tick":world["tick"]})
def process_crises(world):
    for cr in list(world.get("active_crises",[])):
        if cr["phase"]=="active" and world["tick"]>=cr["end_tick"]: cr["phase"]="recovering"
        if cr["phase"]=="recovering":
            cr["recovery_progress"]+=0.01
            if cr["recovery_progress"]>=1:
                world["active_crises"].remove(cr)
                world["news"].append({"id":f"news_recovery_{world['tick']}","type":"recovery","headline":f"Recovery from {cr['type']} completed","summary":"The world stabilizes, but scars remain.","sentiment":"mixed","intensity":.6,"tags":["recovery"],"tick":world["tick"]})
