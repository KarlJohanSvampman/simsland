from brain.beliefs import compute_alignment, update_belief
POLICIES={
 "lower_taxes":{"primary":[("tax_rate",-0.04)],"secondary":[("health_quality",-0.02),("education_quality",-0.02)],"delayed":[{"key":"budget_deficit","delta":0.05,"delay":150}],"tags":["taxes","economy"]},
 "increase_policing":{"primary":[("crime_solve_rate",0.08)],"secondary":[("social_tension",0.05)],"delayed":[{"key":"crime_rate","delta":-0.03,"delay":120}],"tags":["crime","police"]},
 "support_welfare":{"primary":[("cost_of_living_index",-0.05)],"secondary":[("tax_rate",0.03)],"delayed":[{"key":"budget_deficit","delta":0.04,"delay":120}],"tags":["welfare","economy"]},
 "improve_healthcare":{"primary":[("health_quality",0.08)],"secondary":[("tax_rate",0.02),("health_cost_index",0.03)],"delayed":[],"tags":["healthcare"]}
}
def clamp(v): return max(0,min(2,v))
def build_factions(world):
    chars=list(world["characters"].values())
    for c in chars: compute_alignment(c)
    groups={"security":[],"welfare":[],"low_tax":[],"moderate":[]}
    for c in chars:
        a=c.get("political_alignment",{})
        g="security" if a.get("security",0)>0.35 else "welfare" if a.get("economic",0)<-0.25 else "low_tax" if a.get("economic",0)>0.25 else "moderate"
        groups[g].append(c["id"]); c["faction_id"]=g
    world["factions"]={
      "security":{"id":"security","name":"Order League","members":groups["security"],"agenda":["increase_policing"],"resources":1000},
      "welfare":{"id":"welfare","name":"Care Coalition","members":groups["welfare"],"agenda":["support_welfare","improve_healthcare"],"resources":1000},
      "low_tax":{"id":"low_tax","name":"Low Tax Bloc","members":groups["low_tax"],"agenda":["lower_taxes"],"resources":1000},
      "moderate":{"id":"moderate","name":"Moderates","members":groups["moderate"],"agenda":[],"resources":500}}
def apply_policy(world, policy):
    p=POLICIES.get(policy); env=world["environment"]
    if not p: return
    for key,delta in p.get("primary",[])+p.get("secondary",[]): env[key]=clamp(env.get(key,0)+delta)
    for eff in p.get("delayed",[]): world.setdefault("pending_effects",[]).append({**eff,"apply_tick":world["tick"]+eff["delay"],"policy":policy})
    world.setdefault("recent_policies",[]).append(policy); world["recent_policies"]=world["recent_policies"][-8:]
    world.setdefault("news",[]).append({"id":f"news_policy_{world['tick']}","type":"policy","headline":f"Policy enacted: {policy}","summary":"New policy may have tradeoffs.","sentiment":"mixed","intensity":0.7,"tags":p.get("tags",[]),"tick":world["tick"]})
def process_pending_effects(world):
    for eff in list(world.get("pending_effects",[])):
        if world["tick"]>=eff["apply_tick"]:
            world["environment"][eff["key"]]=clamp(world["environment"].get(eff["key"],0)+eff["delta"])
            world["pending_effects"].remove(eff)
            world["news"].append({"id":f"news_effect_{world['tick']}","type":"policy_effect","headline":f"Consequences of {eff.get('policy')} emerging","summary":f"{eff['key']} changed.","sentiment":"negative","intensity":0.6,"tags":["policy"],"tick":world["tick"]})
def check_election(world):
    e=world["election"]
    if world["tick"]==e["campaign_start_tick"]:
        build_factions(world); e["campaign_active"]=True; e["candidates"]=[fid for fid,f in world["factions"].items() if f["members"]]
    if e["campaign_active"]:
        for fid in e.get("candidates",[]):
            for cid in world["factions"][fid]["members"]:
                c=world["characters"][cid]
                for agenda in world["factions"][fid]["agenda"]: update_belief(c,agenda,"positive",.2,world["tick"])
    if world["tick"]>=e["next_tick"]:
        build_factions(world); votes={fid:0 for fid in world["factions"]}
        for c in world["characters"].values(): votes[c.get("faction_id") or "moderate"]=votes.get(c.get("faction_id") or "moderate",0)+1
        winner=max(votes,key=votes.get); e["result"]=winner; e["votes"]=votes; e["campaign_active"]=False; e["next_tick"]+=500; e["campaign_start_tick"]=e["next_tick"]-80
        for pol in world["factions"][winner].get("agenda",[])[:1]: apply_policy(world,pol)
