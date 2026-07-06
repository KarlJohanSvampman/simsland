"""
systems/intimacy.py

Intimacy ladder (stages 0-6) and act proposal/negotiation engine.

Stage gating:
  0 – strangers (no intimacy)
  1 – social touch (hug_brief, handshake_lingering)
  2 – affectionate touch (hug_long, kiss_cheek, cuddling)
  3 – romantic touch (kiss_lips, kiss_passionate, lap_sitting)
  4 – sensual (massage_sensual, undressing, mutual_touch)
  5 – explicit foreplay (oral_sex, manual_stimulation, breast_play)
  6 – intercourse (intercourse_*, tribadism, anal_intercourse, frottage)

Each act in definitions.json["sexual_acts"] has a "tier" matching stage 4-6.
Stages 1-3 are social/romantic acts defined in interaction_templates.

Negotiation state machine per relationship:
  IDLE → PROPOSED → (ACCEPTED | REJECTED | COUNTER | CONDITIONAL)
  COUNTER loops back to PROPOSED from the other side.
  CONDITIONAL: proposee agrees IF condition is met (e.g. "only if we're alone")

Acts execute only when ACCEPTED.
"""

import random
import uuid

from systems.grievances import add_grievance
from systems.reputation import apply_reputation_event

# ── Feature flag ─────────────────────────────────────────────────────────
# Set COERCION_ENABLED = True to activate non-consent escalation mechanics.
# While False, maybe_ignore_rejection() always returns "backed_off" and
# the trauma system is never triggered from intimacy events.
COERCION_ENABLED = False

# ── Boundary respect thresholds ───────────────────────────────────────────
# Characters with boundary_violator trait may ignore rejection
COERCION_TRAIT_RISK    = {"boundary_violator", "aggressive", "controlling",
                           "possessive", "manipulative", "ruthless"}
BOUNDARY_SAFE_TRAITS   = {"boundary_respectful", "compassionate", "honest",
                           "empathetic", "loyal"}
IGNORE_REJECTION_BASE  = 0.05   # 5% base chance any rejected proposal escalates
COERCION_RISK_MULT     = 8.0    # multiplier for high-risk traits

# ── Stage configuration ───────────────────────────────────────────────────

STAGE_LABELS = {
    0: "none",
    1: "social_touch",
    2: "affectionate",
    3: "romantic",
    4: "sensual",
    5: "foreplay",
    6: "intercourse",
}

# Thresholds: (attraction_min, trust_min, comfort_min) to attempt next stage
STAGE_THRESHOLDS = {
    1: {"attraction": 10, "trust": 0,  "comfort": 5,  "familiarity": 5},
    2: {"attraction": 25, "trust": 15, "comfort": 15, "familiarity": 10},
    3: {"attraction": 45, "trust": 30, "comfort": 25, "familiarity": 20},
    4: {"attraction": 60, "trust": 45, "comfort": 40, "familiarity": 30},
    5: {"attraction": 72, "trust": 55, "comfort": 55, "familiarity": 40},
    6: {"attraction": 82, "trust": 65, "comfort": 65, "familiarity": 50},
}

# Acts available per tier (maps to definitions.json sexual_acts keys by tier)
TIER_TO_STAGE = {3: 3, 4: 4, 5: 5, 6: 6}

# Negotiation state values
NEG_IDLE        = "idle"
NEG_PROPOSED    = "proposed"
NEG_ACCEPTED    = "accepted"
NEG_REJECTED    = "rejected"
NEG_COUNTER     = "counter"
NEG_CONDITIONAL = "conditional"

# Arousal decay per tick (very slow)
AROUSAL_DECAY   = 0.0002
# Arousal gain per intimate interaction
AROUSAL_GAIN    = {1: 0.02, 2: 0.05, 3: 0.08, 4: 0.15, 5: 0.20, 6: 0.25}
# Comfort gain per successful intimate stage
COMFORT_GAIN    = {1: 2, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12}


# ── Relationship intimacy fields ──────────────────────────────────────────

def ensure_intimacy_state(rel):
    """Ensure intimacy sub-dict exists on a relationship object."""
    rel.setdefault("intimacy_stage",   0)
    rel.setdefault("intimacy_progress", 0.0)   # 0-100 toward next stage
    rel.setdefault("arousal_level",    0.0)    # 0-1, current session arousal
    rel.setdefault("negotiation",      {
        "state":         NEG_IDLE,
        "proposed_act":  None,
        "proposed_by":   None,
        "counter_act":   None,
        "condition":     None,
        "last_tick":     0,
    })
    rel.setdefault("intimacy_history", [])     # list of completed act records
    return rel


# ── Stage eligibility ─────────────────────────────────────────────────────

def can_advance_stage(c, other, world):
    """
    Return the maximum intimacy stage c and other can currently reach,
    given attraction, trust, comfort, and profile modifiers.
    """
    c_rel   = ensure_intimacy_state(c.get("relationships", {}).get(other["id"], {}))
    o_rel   = ensure_intimacy_state(other.get("relationships", {}).get(c["id"], {}))
    current = c_rel.get("intimacy_stage", 0)

    # Use the lower of both parties' relationship values (mutual requirement)
    attraction  = min(c_rel.get("attraction",  0), o_rel.get("attraction",  0))
    trust       = min(c_rel.get("trust",       0), o_rel.get("trust",       0))
    comfort     = min(c_rel.get("comfort",     0), o_rel.get("comfort",     0))
    familiarity = min(c_rel.get("familiarity", 0), o_rel.get("familiarity", 0))

    # Stage gate modifier from attraction profiles
    c_mod = c.get("attraction_profile", {}).get("stage_gate_mod", 0)
    o_mod = other.get("attraction_profile", {}).get("stage_gate_mod", 0)
    gate_mod = c_mod + o_mod  # combined: promiscuous pair can unlock faster

    max_stage = current
    for stage in range(current + 1, 7):
        thresh = STAGE_THRESHOLDS.get(stage, {})
        adj_attraction = thresh.get("attraction", 999) - gate_mod * 8
        if (attraction  >= adj_attraction and
            trust       >= thresh.get("trust",       0) and
            comfort     >= thresh.get("comfort",     0) and
            familiarity >= thresh.get("familiarity", 0)):
            max_stage = stage
        else:
            break

    return max_stage


# ── Act catalog lookup ────────────────────────────────────────────────────

def get_available_acts(c, other, world, max_stage=None):
    """
    Return list of act dicts from definitions.json that are available given:
      - current intimacy stage
      - sexual compatibility (orientation / act.compatibility)
      - max_stage cap (if None, compute from can_advance_stage)
    """
    defs = world.get("defs", {})
    acts_registry = defs.get("sexual_acts", {})
    if not acts_registry:
        return []

    if max_stage is None:
        max_stage = can_advance_stage(c, other, world)

    c_sex   = c.get("sex",   "male")
    o_sex   = other.get("sex", "female")
    c_orient = c.get("sexual_orientation", "heterosexual")

    available = []
    for act_id, act in acts_registry.items():
        tier = act.get("tier", 3)
        stage = TIER_TO_STAGE.get(tier, tier)
        if stage > max_stage:
            continue

        # Compatibility check
        compat = act.get("compatibility", "any")
        if compat == "heterosexual_only" and c_sex == o_sex:
            continue
        if compat == "same_sex_female_only" and not (c_sex == "female" and o_sex == "female"):
            continue
        if compat == "same_sex_male_only" and not (c_sex == "male" and o_sex == "male"):
            continue

        available.append({"id": act_id, **act})
    return available


# ── Proposal engine ───────────────────────────────────────────────────────

def propose_act(proposer, recipient, act_id, world):
    """
    Proposer initiates an act proposal toward recipient.
    Stores negotiation state on both relationship objects.
    Returns {"ok": True} or {"ok": False, "reason": ...}
    """
    pid = proposer["id"]
    rid = recipient["id"]

    p_rel = ensure_intimacy_state(
        proposer.setdefault("relationships", {}).setdefault(rid, {}))
    r_rel = ensure_intimacy_state(
        recipient.setdefault("relationships", {}).setdefault(pid, {}))

    # Can't propose if already negotiating
    if p_rel["negotiation"]["state"] not in (NEG_IDLE, NEG_REJECTED):
        return {"ok": False, "reason": "already_negotiating"}

    # Check act exists and is available
    acts = get_available_acts(proposer, recipient, world)
    act_ids = [a["id"] for a in acts]
    if act_id not in act_ids:
        return {"ok": False, "reason": "act_not_available"}

    tick = world.get("tick", 0)
    neg = {
        "state":        NEG_PROPOSED,
        "proposed_act": act_id,
        "proposed_by":  pid,
        "counter_act":  None,
        "condition":    None,
        "last_tick":    tick,
    }
    p_rel["negotiation"] = dict(neg)
    r_rel["negotiation"] = dict(neg)
    return {"ok": True, "act_id": act_id}


def respond_to_proposal(recipient, proposer, response, world,
                         counter_act=None, condition=None):
    """
    Recipient responds to an active proposal.
    response: "accept" | "reject" | "counter" | "conditional"
    counter_act: act_id for COUNTER response
    condition: string describing condition for CONDITIONAL

    Returns {"ok": True, "result": ...} or {"ok": False, "reason": ...}
    """
    pid = proposer["id"]
    rid = recipient["id"]

    r_rel = ensure_intimacy_state(
        recipient.setdefault("relationships", {}).setdefault(pid, {}))
    p_rel = ensure_intimacy_state(
        proposer.setdefault("relationships", {}).setdefault(rid, {}))

    if r_rel["negotiation"]["state"] != NEG_PROPOSED:
        return {"ok": False, "reason": "no_active_proposal"}

    tick = world.get("tick", 0)

    if response == "accept":
        neg_state = NEG_ACCEPTED
    elif response == "reject":
        neg_state = NEG_REJECTED
        # Rejection adds a tiny grievance if pushy proposer
        _handle_rejection_fallout(proposer, recipient, world)
    elif response == "counter":
        if not counter_act:
            return {"ok": False, "reason": "counter_requires_act"}
        neg_state = NEG_COUNTER
    elif response == "conditional":
        if not condition:
            return {"ok": False, "reason": "conditional_requires_condition"}
        neg_state = NEG_CONDITIONAL
    else:
        return {"ok": False, "reason": "unknown_response"}

    neg = {
        "state":        neg_state,
        "proposed_act": counter_act if neg_state == NEG_COUNTER
                        else r_rel["negotiation"]["proposed_act"],
        "proposed_by":  rid if neg_state == NEG_COUNTER
                        else r_rel["negotiation"]["proposed_by"],
        "counter_act":  counter_act,
        "condition":    condition,
        "last_tick":    tick,
    }
    r_rel["negotiation"] = dict(neg)
    p_rel["negotiation"] = dict(neg)
    return {"ok": True, "result": neg_state, "negotiation": neg}


# ── Recipient decision (AI-driven) ────────────────────────────────────────

def recipient_decision(recipient, proposer, world):
    """
    Compute the AI decision for the recipient given the current proposal.
    Returns one of: "accept", "reject", "counter", "conditional"

    Factors:
      - recipient's attraction to proposer
      - current arousal level
      - trust and comfort
      - sexual anxiety
      - personality traits (promiscuous, romantic, etc.)
      - proposed act stage vs current comfort zone
    """
    pid = proposer["id"]
    rid = recipient["id"]

    r_rel = ensure_intimacy_state(
        recipient.setdefault("relationships", {}).setdefault(pid, {}))
    neg   = r_rel["negotiation"]

    if neg["state"] != NEG_PROPOSED:
        return None

    defs      = world.get("defs", {})
    acts_reg  = defs.get("sexual_acts", {})
    act_id    = neg["proposed_act"]
    act       = acts_reg.get(act_id, {})
    act_tier  = act.get("tier", 3)
    act_stage = TIER_TO_STAGE.get(act_tier, act_tier)

    # ── Preference-aware scoring ──────────────────────────────────────────
    prefs = recipient.get("sexual_preferences", {})
    # Hard-no kinks requested in the proposed act
    act_kinks = set(act.get("kinks", []))
    hard_no   = set(prefs.get("kinks_hard_no", []))
    if act_kinks & hard_no:
        # Proposing a hard-no kink → immediate reject
        return "reject"
    # Liked kinks boost willingness
    liked_kinks = set(prefs.get("kinks", []))
    kink_match  = len(act_kinks & liked_kinks)
    # Trauma: intimacy_avoidance reduces willingness
    trauma_avoidance = recipient.get("trauma", {}).get("intimacy_avoidance", 0.0)

    # Gather recipient relationship state
    attraction  = r_rel.get("attraction",  0) / 100.0
    trust       = r_rel.get("trust",       0) / 100.0
    comfort     = r_rel.get("comfort",     0) / 100.0
    arousal     = r_rel.get("arousal_level", 0.0)
    current_stage = r_rel.get("intimacy_stage", 0)

    profile     = recipient.get("attraction_profile", {})
    anxiety     = profile.get("sexual_anxiety",   0.25)
    gate        = profile.get("emotional_gate",   0.25)
    casual_rel  = profile.get("casual_reluctance", 0.0)
    stage_mod   = profile.get("stage_gate_mod",   0)

    r_traits    = set(recipient.get("traits", []) + recipient.get("personality_traits", []))

    # Base willingness — combination of attraction, trust, arousal
    willingness = (attraction * 0.5 + trust * 0.25 + comfort * 0.15 + arousal * 0.10)

    # Kink match bonus
    willingness += kink_match * 0.08

    # Trauma avoidance penalty
    willingness -= trauma_avoidance * 0.4

    # Trust floor check (trauma raises minimum trust required)
    trust_floor = recipient.get("trauma", {}).get("trust_floor", 0.0)
    if trust_floor > 0 and trust < trust_floor:
        willingness -= (trust_floor - trust) * 0.8

    # Anxiety penalty
    willingness -= anxiety * 0.25

    # Casual reluctance penalty for high stages without emotional bond
    if act_stage >= 5 and gate > 0.2:
        willingness -= casual_rel * 0.2

    # Stage jump penalty — proposing too far beyond current stage
    stage_jump = act_stage - current_stage
    if stage_jump > 1:
        willingness -= (stage_jump - 1) * 0.2 + stage_mod * 0.05

    # Trait modifiers
    if "promiscuous" in r_traits:
        willingness += 0.15
    if "romantic" in r_traits and act_stage < 3:
        willingness -= 0.10   # romantic type wants romance first
    if "impulsive" in r_traits:
        willingness += 0.10
    if "cautious" in r_traits or "reserved" in r_traits:
        willingness -= 0.10
    if "sexually_confident" in r_traits:
        willingness += 0.08

    # Decide
    rand = random.random()
    if willingness > 0.70:
        return "accept"
    elif willingness > 0.45:
        # Maybe suggest a less intense act instead
        if act_stage > 1 and rand < 0.35:
            return "counter"
        return "accept"
    elif willingness > 0.25:
        if rand < 0.45:
            return "conditional"
        return "reject"
    else:
        return "reject"


# ── Act execution ─────────────────────────────────────────────────────────

def execute_act(initiator, recipient, act_id, world):
    """
    Execute an accepted intimate act.

    Effects:
      - Update intimacy_stage + progress on both relationship objects
      - Apply arousal gain
      - Apply comfort/trust gain
      - Apply relationship stat changes from act["effects"]
      - Log to intimacy_history
      - Apply reputation events if in public / if observed
    Returns summary dict.
    """
    pid = initiator["id"]
    rid = recipient["id"]

    p_rel = ensure_intimacy_state(
        initiator.setdefault("relationships", {}).setdefault(rid, {}))
    r_rel = ensure_intimacy_state(
        recipient.setdefault("relationships", {}).setdefault(pid, {}))

    defs     = world.get("defs", {})
    acts_reg = defs.get("sexual_acts", {})
    act      = acts_reg.get(act_id)
    if not act:
        return {"ok": False, "reason": "act_not_found"}

    act_tier  = act.get("tier", 3)
    act_stage = TIER_TO_STAGE.get(act_tier, act_tier)
    tick      = world.get("tick", 0)

    # Apply effects from act definition
    effects = act.get("effects", {})
    for rel_obj in (p_rel, r_rel):
        for stat, delta in effects.items():
            if stat in rel_obj:
                rel_obj[stat] = max(0, min(100, rel_obj[stat] + delta))

    # Arousal gain
    arousal_gain = AROUSAL_GAIN.get(act_stage, 0.05)
    p_rel["arousal_level"] = min(1.0, p_rel.get("arousal_level", 0) + arousal_gain)
    r_rel["arousal_level"] = min(1.0, r_rel.get("arousal_level", 0) + arousal_gain)

    # Comfort + trust gain for both
    comfort_gain = COMFORT_GAIN.get(act_stage, 4)
    p_rel["comfort"] = min(100, p_rel.get("comfort", 0) + comfort_gain)
    r_rel["comfort"] = min(100, r_rel.get("comfort", 0) + comfort_gain)
    p_rel["trust"]   = min(100, p_rel.get("trust",   0) + int(comfort_gain * 0.4))
    r_rel["trust"]   = min(100, r_rel.get("trust",   0) + int(comfort_gain * 0.4))

    # Stage progression
    progress_gain = 20.0 * (act_stage / 3.0)
    for rel_obj in (p_rel, r_rel):
        cur_stage = rel_obj["intimacy_stage"]
        if act_stage >= cur_stage:
            rel_obj["intimacy_progress"] = min(100, rel_obj["intimacy_progress"] + progress_gain)
            if rel_obj["intimacy_progress"] >= 100:
                rel_obj["intimacy_stage"]    = min(6, cur_stage + 1)
                rel_obj["intimacy_progress"] = 0.0

    # Log
    record = {
        "tick":      tick,
        "act_id":    act_id,
        "with":      rid if rel_obj is p_rel else pid,
        "stage":     act_stage,
        "formation": act.get("spatial", {}).get("formation", ""),
    }
    p_rel["intimacy_history"].append({"tick": tick, "act_id": act_id, "with": rid,   "stage": act_stage})
    r_rel["intimacy_history"].append({"tick": tick, "act_id": act_id, "with": pid,   "stage": act_stage})

    # Reset negotiation to idle
    idle_neg = {"state": NEG_IDLE, "proposed_act": None, "proposed_by": None,
                "counter_act": None, "condition": None, "last_tick": tick}
    p_rel["negotiation"] = dict(idle_neg)
    r_rel["negotiation"] = dict(idle_neg)

    # If observed or in public → reputation hit
    location = world.get("characters_by_location", {})
    loc_id   = initiator.get("current_location")
    if loc_id and act_stage >= 4:
        occupants = location.get(loc_id, [])
        observers  = [oid for oid in occupants if oid not in (pid, rid)]
        if observers and act_stage >= 5:
            apply_reputation_event(initiator, "public_indecency", world)
            apply_reputation_event(recipient, "public_indecency", world)

    # ── Pleasure + climax resolution ─────────────────────────────────────
    pleasure_outcome = None
    if act_stage >= 5:   # only for explicit stages
        try:
            from systems.pleasure import resolve_encounter_outcome
            pleasure_outcome = resolve_encounter_outcome(
                initiator, recipient, act_id,
                position_id=None,    # position set separately by action_router
                world=world
            )
        except Exception:
            pass

    return {
        "ok":         True,
        "act_id":     act_id,
        "act_name":   act.get("name", act_id),
        "act_stage":  act_stage,
        "formation":  act.get("spatial", {}).get("formation", ""),
        "initiator_animation": act.get("animations", {}).get("initiator", ""),
        "recipient_animation": act.get("animations", {}).get("recipient", ""),
        "pleasure_outcome":    pleasure_outcome,
    }


# ── Tick ──────────────────────────────────────────────────────────────────

def tick_intimacy(world):
    """
    Per-tick: decay arousal slowly on all relationships.
    Called from sim_loop.
    """
    for c in world.get("characters", []):
        for oid, rel in c.get("relationships", {}).items():
            if "arousal_level" in rel:
                rel["arousal_level"] = max(0.0, rel["arousal_level"] - AROUSAL_DECAY)


# ── Rejection fallout ─────────────────────────────────────────────────────

def _handle_rejection_fallout(proposer, recipient, world):
    """
    If proposer has low rejection resilience, add mild grievance toward recipient.
    Repeated rejections build resentment.
    """
    profile    = proposer.get("attraction_profile", {})
    resilience = profile.get("rejection_resilience", 0.5)
    if resilience > 0.6:
        return  # bounces back easily, no grievance

    # Low resilience → hurt feelings → grievance
    severity = (1.0 - resilience) * 4.0
    add_grievance(
        proposer, recipient["id"],
        "rejected_advance",
        world,
        severity=round(severity, 2),
        details={"context": "intimate_proposal"}
    )

    # Also add to relationship resentment
    rel = proposer.get("relationships", {}).get(recipient["id"], {})
    if rel:
        rel["resentment"] = min(100, rel.get("resentment", 0) + severity)


# ── Non-consent escalation ────────────────────────────────────────────────

def maybe_ignore_rejection(proposer, recipient, world):
    """
    After a rejection, check whether the proposer ignores it and forces the act.
    Only called when rejection state is set.

    Returns:
      "backed_off" — character respected the rejection
      "escalated"  — character ignored rejection → triggers resolve_sexual_assault()
    """
    if not COERCION_ENABLED:
        return "backed_off"

    pid = proposer["id"]
    rid = recipient["id"]

    p_traits = set(proposer.get("traits", []) + proposer.get("personality_traits", []))

    # Safe traits make coercion nearly impossible
    if p_traits & BOUNDARY_SAFE_TRAITS:
        return "backed_off"

    # Compute coercion risk
    risk = IGNORE_REJECTION_BASE
    risk_traits = p_traits & COERCION_TRAIT_RISK
    if risk_traits:
        risk *= COERCION_RISK_MULT * (1 + 0.3 * (len(risk_traits) - 1))

    # Arousal amplifies risk
    p_rel = proposer.get("relationships", {}).get(rid, {})
    arousal = p_rel.get("arousal_level", 0.0)
    risk += arousal * 0.15

    # High attraction and prior relationship reduces (more invested in consent)
    attraction = p_rel.get("attraction", 0) / 100.0
    trust      = p_rel.get("trust",      0) / 100.0
    if attraction > 0.7 and trust > 0.6:
        risk *= 0.5   # cares about the relationship

    risk = min(0.90, risk)

    if random.random() > risk:
        return "backed_off"

    # Escalation — call trauma system
    try:
        from systems.trauma import resolve_sexual_assault
        outcome = resolve_sexual_assault(proposer, recipient, world)
        # Reset negotiation to idle — the act is over (with terrible consequences)
        tick = world.get("tick", 0)
        idle_neg = {"state": NEG_IDLE, "proposed_act": None, "proposed_by": None,
                    "counter_act": None, "condition": None, "last_tick": tick}
        p_rel["negotiation"] = dict(idle_neg)
        r_rel = recipient.get("relationships", {}).setdefault(pid, {})
        r_rel["negotiation"] = dict(idle_neg)
        return "escalated"
    except Exception:
        return "backed_off"


# ── Context helper ────────────────────────────────────────────────────────

def get_intimacy_context(c, world):
    """
    Build LLM context for c's intimate relationships.
    Returns privacy-safe summary — no explicit act names, only stage + mood.
    """
    lines = []
    chars = {x["id"]: x for x in world.get("characters", [])}

    for oid, rel in c.get("relationships", {}).items():
        stage   = rel.get("intimacy_stage", 0)
        arousal = rel.get("arousal_level",  0.0)
        neg     = rel.get("negotiation",    {})
        if stage == 0 and arousal < 0.1 and neg.get("state") == NEG_IDLE:
            continue
        name = chars.get(oid, {}).get("name", oid)
        stage_label = STAGE_LABELS.get(stage, "unknown")
        line = f"{name}: intimacy_stage={stage_label}({stage})"
        if arousal > 0.2:
            line += f", arousal={'high' if arousal > 0.6 else 'moderate'}"
        if neg.get("state") not in (NEG_IDLE, None):
            line += f", negotiation={neg['state']}"
        lines.append(line)

    return {"intimacy": lines} if lines else {}
