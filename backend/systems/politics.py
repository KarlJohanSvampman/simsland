import random
from brain.opinions import compute_political_lean, nudge_opinion
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
    for c in chars: compute_political_lean(c)

    # Party-aware path: when definitions.json's political_party_templates
    # exist, match each character with a compiled mentality to their
    # best-tag-overlap party -- resolve_legislation_votes()/
    # _character_leans_for() only ever read faction["agenda"]/["members"],
    # never the faction's key name, so this is a drop-in for them.
    defs = world.get("definitions") or {}
    parties = defs.get("political_party_templates") or {}
    if parties:
        ensure_party_policies(world)
        groups = {pid: [] for pid in parties}
        fallback_groups = {"security":[],"welfare":[],"low_tax":[],"moderate":[]}
        for c in chars:
            tags = set((c.get("mentality") or {}).get("tags") or [])
            if tags:
                best_pid, best_overlap = None, -1
                for pid, party in parties.items():
                    overlap = len(tags & set(party.get("ideology_tags", [])))
                    if overlap > best_overlap:
                        best_pid, best_overlap = pid, overlap
                groups[best_pid].append(c["id"])
                c["faction_id"] = best_pid
            else:
                # No compiled mentality yet (a workplace NPC, or a
                # character generated before this round) -- falls back to
                # the original alignment split so nobody's left unbucketed.
                a = c.get("political_lean", {})
                g = "security" if a.get("security",0)>0.35 else "welfare" if a.get("economic",0)<-0.25 else "low_tax" if a.get("economic",0)>0.25 else "moderate"
                fallback_groups[g].append(c["id"])
                c["faction_id"] = g

        parties_runtime = world.get("political_parties") or {}
        factions = {
            pid: {"id": pid, "name": party["name"], "members": groups[pid],
                  # Static authored agenda + any AI-generated policies
                  # (llm/party_policy.py) cached at world level -- merged
                  # here at read time rather than mutating the shared,
                  # cross-world definitions.json content.
                  "agenda": list(party.get("agenda", []))
                            + list(parties_runtime.get(pid, {}).get("generated_policies", {}).values()),
                  "resources": 1000}
            for pid, party in parties.items()
        }
        for g, members in fallback_groups.items():
            if members:
                factions[g] = {"id": g, "name": g.replace("_", " ").title(),
                                "members": members, "agenda": [], "resources": 500}
        world["factions"] = factions
        return

    # Legacy path -- no party templates defined, unchanged.
    groups={"security":[],"welfare":[],"low_tax":[],"moderate":[]}
    for c in chars:
        a=c.get("political_lean",{})
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
                # Real fix made during the beliefs->opinions migration: the
                # old update_belief() call nudged a belief keyed by the
                # POLICY id itself (e.g. "increase_policing"), which
                # compute_alignment()/IDEOLOGY_AXES never actually read
                # (only real topic ids like "crime"/"police" are) -- so
                # this reinforcement never once reached political_alignment.
                # Nudging the policy's own real tags closes that gap.
                for agenda in world["factions"][fid]["agenda"]:
                    for topic in POLICIES.get(agenda,{}).get("tags",[]):
                        nudge_opinion(c,topic,"positive",.2,world["tick"])
    if world["tick"]>=e["next_tick"]:
        # Eligibility fix: this used to count a vote from EVERY character
        # in world["characters"] with no filter at all -- toddlers voted
        # identically to adults. Same age>=18 filter resolve_legislation_
        # votes() already uses, plus a real ID requirement (the user's own
        # "something they need to go vote" ask) -- a fake ID still counts
        # here (that IS the fraud vector), see personal_items.py::
        # has_valid_id()'s own docstring for why real/fake aren't
        # distinguished at this checkpoint.
        from systems.personal_items import has_valid_id
        build_factions(world); votes={fid:0 for fid in world["factions"]}
        for c in world["characters"].values():
            if c.get("age",0)<18 or not has_valid_id(c): continue
            votes[c.get("faction_id") or "moderate"]=votes.get(c.get("faction_id") or "moderate",0)+1
        winner=max(votes,key=votes.get); e["result"]=winner; e["votes"]=votes; e["campaign_active"]=False; e["next_tick"]+=500; e["campaign_start_tick"]=e["next_tick"]-80
        for pol in world["factions"][winner].get("agenda",[])[:1]: apply_policy(world,pol)


def choose_political_topic(a, b, world):
    """Weights mentality_compiler.POLITICAL_TOPICS by the higher of the
    two participants' party's topic_awareness for each topic, then
    weighted-picks one -- a debate leans toward whatever either party
    actually campaigns hardest on. Falls back to a uniform random topic
    if neither participant has a resolved party/topic_awareness yet."""
    import random
    from llm.mentality_compiler import POLITICAL_TOPICS

    defs = world.get("definitions") or {}
    parties = defs.get("political_party_templates") or {}
    a_aware = parties.get(a.get("faction_id"), {}).get("topic_awareness", {})
    b_aware = parties.get(b.get("faction_id"), {}).get("topic_awareness", {})

    weights = [max(a_aware.get(t, 0), b_aware.get(t, 0)) for t in POLITICAL_TOPICS]
    if sum(weights) <= 0:
        return random.choice(POLITICAL_TOPICS)
    return random.choices(POLITICAL_TOPICS, weights=weights, k=1)[0]


_POLICY_GENERATION_THRESHOLD = 0.75


def ensure_party_policies(world):
    """Lazily generates a real, AI-authored policy (llm/party_policy.py)
    for any (party, topic) pair a party is highly aware of but hasn't
    authored a real POLICIES entry for yet. Called from build_factions()
    itself so it naturally piggybacks on however often that already
    runs -- a no-op after the first successful generation per pair, per
    party_policy.py's own world-level caching."""
    from llm.party_policy import generate_party_policy

    defs = world.get("definitions") or {}
    parties = defs.get("political_party_templates") or {}
    for pid, party in parties.items():
        for topic, weight in party.get("topic_awareness", {}).items():
            if weight >= _POLICY_GENERATION_THRESHOLD:
                generate_party_policy(world, pid, topic)


def tick_environment_opinion_drift(world):
    """Monthly re-nudge (sim_loop.py's _is_month_start_midnight block) --
    keeps opinions drifting with real, current conditions over time, not
    just the one-time generation seed compile_political_views() applies.
    Reuses nudge_opinion() (brain/opinions.py, shipped in the earlier
    beliefs->opinions round) and llm/mentality_compiler.py's own
    environment-stat gates/topic-nudge table directly -- no new
    mechanism, just a new, small, real periodic caller of both."""
    from llm.mentality_compiler import active_environment_topic_nudges

    active_nudges = active_environment_topic_nudges(world)
    if not active_nudges:
        return

    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        if c.get("is_workplace_npc"):
            continue
        for topic, delta in active_nudges:
            # A small monthly drift, not a big jump -- a fraction of the
            # one-time generation-seed nudge magnitude.
            nudge_opinion(
                c, topic, "positive" if delta > 0 else "negative", abs(delta) / 6.0, tick,
                reasoning="Real local conditions.",
            )
