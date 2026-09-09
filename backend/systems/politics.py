import random
from brain.beliefs import compute_alignment, update_belief
POLICIES={
 "lower_taxes":{"primary":[("tax_rate",-0.04)],"secondary":[("health_quality",-0.02),("education_quality",-0.02)],"delayed":[{"key":"budget_deficit","delta":0.05,"delay":150}],"tags":["taxes","economy"]},
 "increase_policing":{"primary":[("crime_solve_rate",0.08)],"secondary":[("social_tension",0.05)],"delayed":[{"key":"crime_rate","delta":-0.03,"delay":120}],"tags":["crime","police"]},
 "support_welfare":{"primary":[("cost_of_living_index",-0.05)],"secondary":[("tax_rate",0.03)],"delayed":[{"key":"budget_deficit","delta":0.04,"delay":120}],"tags":["welfare","economy"]},
 "improve_healthcare":{"primary":[("health_quality",0.08)],"secondary":[("tax_rate",0.02),("health_cost_index",0.03)],"delayed":[],"tags":["healthcare"]},
 # New for the legislation system below -- kept on the SAME 0-2-range
 # environment keys as the 4 above (apply_policy()'s clamp() is hardcoded
 # to [0,2], not per-key-aware, so a 0-100-scale key like traffic_
 # congestion_pct or high_school_graduation would get destroyed by it;
 # feeding Phase C's budget categories with a *safe* key instead).
 "housing_investment":{"primary":[("cost_of_living_index",-0.03)],"secondary":[("tax_rate",0.02)],"delayed":[{"key":"budget_deficit","delta":0.03,"delay":150}],"tags":["housing","economy"]},
 "anti_corruption_reform":{"primary":[("crime_solve_rate",0.05)],"secondary":[("social_tension",-0.03)],"delayed":[],"tags":["corruption","governance"]},
}

# =========================================================
# LEGISLATION -- scheduled upcoming bills, additive to the election
# cycle above (left otherwise untouched). A policy no longer only ever
# arrives as an election winner's automatic prize -- it can also be
# proposed and voted on independently, with a real future vote date.
# =========================================================

LEGISLATION_POOL = list(POLICIES.keys())

# Vote happens roughly 1-2 sim-weeks after a bill is proposed.
_TICKS_PER_DAY = 86400
LEGISLATION_LEAD_TICKS = (7 * _TICKS_PER_DAY, 14 * _TICKS_PER_DAY)
MIN_PENDING_BILLS = 1


def schedule_upcoming_legislation(world):
    """Weekly cadence (see sim_loop.py). Keeps world["legislation"]
    stocked with at least one pending bill at all times."""
    legislation = world.setdefault("legislation", [])
    pending = [b for b in legislation if b["status"] == "pending"]
    if len(pending) >= MIN_PENDING_BILLS:
        return

    policy_id = random.choice(LEGISLATION_POOL)
    lead = random.randint(*LEGISLATION_LEAD_TICKS)
    legislation.append({
        "id":            f"bill_{world['tick']}_{policy_id}",
        "title":         policy_id.replace("_", " ").title(),
        "policy_id":     policy_id,
        "proposed_tick": world["tick"],
        "vote_tick":     world["tick"] + lead,
        "status":        "pending",
        "votes_for":     0,
        "votes_against": 0,
    })
    world["legislation"] = legislation[-50:]  # bounded history


def _character_leans_for(faction, bill):
    """Reuses build_factions()'s existing alignment computation --
    a character votes for a bill if it's on their own faction's agenda,
    or if the bill's tags overlap with what their faction already stands
    for. No new belief axis."""
    if bill["policy_id"] in faction.get("agenda", []):
        return True
    bill_tags = set(POLICIES.get(bill["policy_id"], {}).get("tags", []))
    faction_tags = set()
    for pol in faction.get("agenda", []):
        faction_tags |= set(POLICIES.get(pol, {}).get("tags", []))
    return bool(bill_tags & faction_tags)


def resolve_legislation_votes(world):
    """Checked on the same cadence as check_election (see sim_loop.py).
    Once a bill's vote_tick passes, tallies one alignment-weighted vote
    per adult character and applies apply_policy() on passage."""
    pending = [b for b in world.get("legislation", []) if b["status"] == "pending"]
    due = [b for b in pending if world["tick"] >= b["vote_tick"]]
    if not due:
        return

    build_factions(world)
    factions = world.get("factions", {})
    adults = [c for c in world["characters"].values() if c.get("age", 0) >= 18]

    for bill in due:
        votes_for = votes_against = 0
        for c in adults:
            faction = factions.get(c.get("faction_id"), {})
            if _character_leans_for(faction, bill):
                votes_for += 1
            else:
                votes_against += 1

        bill["votes_for"] = votes_for
        bill["votes_against"] = votes_against
        if votes_for > votes_against:
            bill["status"] = "passed"
            apply_policy(world, bill["policy_id"])
        else:
            bill["status"] = "failed"
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
