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

# ── No non-consent mechanics — rejection always results in social consequences only

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
    c_mod = (c.get("attraction_profile") or {}).get("stage_gate_mod", 0)
    o_mod = (other.get("attraction_profile") or {}).get("stage_gate_mod", 0)
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

    # Reveal mechanic — female initiating toward male makes her attraction public
    p_sex = proposer.get("sex", "")
    r_sex = recipient.get("sex", "")
    if p_sex in ("female", "intersex") and r_sex in ("male", "intersex"):
        try:
            from systems.rival_cascade import reveal_attraction, check_rival_cascade
            is_new = reveal_attraction(proposer, recipient, world)
            if is_new:
                check_rival_cascade(proposer, recipient, world)
        except Exception:
            pass

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

    profile     = recipient.get("attraction_profile") or {}
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

    # Religious repression avoidance penalty
    repression_avoidance = recipient.get("intimacy_avoidance", 0.0)
    willingness -= repression_avoidance * 0.50

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

    # ── Conception check ──────────────────────────────────────────────────
    if act_stage >= 5:
        try:
            from systems.pregnancy import maybe_conceive
            female = initiator if initiator.get("sex") in ("female","intersex") else recipient
            male   = recipient if female is initiator else initiator
            maybe_conceive(female, male, world)
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




# ── Touch Proposal System (stages 1-3: hug, kiss, cuddle) ────────────────
# Parallel to the sexual-act negotiation channel but for non-explicit
# physical acts that still require both characters to animate together.

# Touch negotiation states (same semantics as NEG_* above)
TNEG_IDLE        = "idle"
TNEG_PROPOSED    = "proposed"
TNEG_ACCEPTED    = "accepted"
TNEG_REJECTED    = "rejected"

# Templates that go through the touch-proposal flow
TOUCH_PROPOSAL_TEMPLATES = {
    "hug",
    "kiss",
    "kiss_peck",
    "kiss_deep",
    "cuddle",
    "hold_hands",
    # if_reciprocated — near-instant auto-accept
    "handshake",
    "high_five",
}

# Templates where the recipient almost always accepts (if_reciprocated)
TOUCH_AUTO_ACCEPT = {"handshake", "high_five"}

# Stage requirement per template (minimum intimacy_stage needed)
TOUCH_STAGE_REQUIREMENT = {
    "hug":        1,
    "kiss":       2,
    "kiss_peck":  2,
    "kiss_deep":  3,
    "cuddle":     2,
    "hold_hands": 2,
    "handshake":  0,   # anyone
    "high_five":  0,   # anyone
}

# Dual animations: initiator / recipient
TOUCH_ANIMATIONS = {
    "hug":        ("anim_hug_give",         "anim_hug_receive"),
    "kiss":       ("anim_kiss_give",         "anim_kiss_receive"),
    "kiss_peck":  ("anim_kiss_peck_give",    "anim_kiss_peck_receive"),
    "kiss_deep":  ("anim_kiss_deep_give",    "anim_kiss_deep_receive"),
    "cuddle":     ("anim_cuddle_big_spoon",  "anim_cuddle_little_spoon"),
    "hold_hands": ("anim_hold_hands_a",      "anim_hold_hands_b"),
    "handshake":  ("anim_handshake_give",    "anim_handshake_receive"),
    "high_five":  ("anim_high_five_give",    "anim_high_five_receive"),
}

# How many ticks before an unanswered touch proposal auto-expires
TOUCH_PROPOSAL_TIMEOUT = 5


def ensure_touch_negotiation(rel):
    """Ensure touch_negotiation sub-dict exists on a relationship object."""
    rel.setdefault("touch_negotiation", {
        "state":        TNEG_IDLE,
        "template_id":  None,
        "proposed_by":  None,
        "last_tick":    0,
    })
    return rel


def propose_touch(proposer, recipient, template_id, world):
    """
    Proposer initiates a hug / kiss / cuddle toward recipient.
    Stores touch_negotiation state on both relationship objects.
    Returns {"ok": True} or {"ok": False, "reason": ...}
    """
    if template_id not in TOUCH_PROPOSAL_TEMPLATES:
        return {"ok": False, "reason": "not_a_touch_template"}

    pid = proposer["id"]
    rid = recipient["id"]

    p_rel = ensure_touch_negotiation(
        ensure_intimacy_state(
            proposer.setdefault("relationships", {}).setdefault(rid, {})))
    r_rel = ensure_touch_negotiation(
        ensure_intimacy_state(
            recipient.setdefault("relationships", {}).setdefault(pid, {})))

    # Already in a pending touch negotiation?
    if p_rel["touch_negotiation"]["state"] == TNEG_PROPOSED:
        return {"ok": False, "reason": "already_pending_touch"}

    # Stage gate — check intimacy_stage vs requirement
    req_stage = TOUCH_STAGE_REQUIREMENT.get(template_id, 1)
    cur_stage = p_rel.get("intimacy_stage", 0)
    # For hugs between close friends/family we relax the gate slightly
    labels = p_rel.get("labels", [])
    is_close = any(lbl in labels for lbl in ("partner", "spouse", "family", "friend_close"))
    if cur_stage < req_stage and not is_close:
        return {"ok": False, "reason": "stage_too_low"}

    tick = world.get("tick", 0)
    neg = {
        "state":       TNEG_PROPOSED,
        "template_id": template_id,
        "proposed_by": pid,
        "last_tick":   tick,
    }
    p_rel["touch_negotiation"] = dict(neg)
    r_rel["touch_negotiation"] = dict(neg)

    # Set proposer to waiting animation
    proposer["animation_state"] = "waiting_touch"

    return {"ok": True, "template_id": template_id}


def respond_to_touch_proposal(recipient, proposer, response, world):
    """
    Recipient responds to a pending touch proposal.
    response: "accept" | "reject"
    Returns {"ok": True, "result": ...} or {"ok": False, "reason": ...}
    """
    pid = proposer["id"]
    rid = recipient["id"]

    r_rel = ensure_touch_negotiation(
        recipient.setdefault("relationships", {}).setdefault(pid, {}))
    p_rel = ensure_touch_negotiation(
        proposer.setdefault("relationships", {}).setdefault(rid, {}))

    if r_rel["touch_negotiation"]["state"] != TNEG_PROPOSED:
        return {"ok": False, "reason": "no_active_touch_proposal"}

    tick = world.get("tick", 0)
    template_id = r_rel["touch_negotiation"]["template_id"]

    if response == "accept":
        new_state = TNEG_ACCEPTED
        _execute_touch(proposer, recipient, template_id, world)
    elif response == "reject":
        new_state = TNEG_REJECTED
        _handle_touch_rejection(proposer, recipient, template_id, world)
    else:
        return {"ok": False, "reason": "unknown_response"}

    idle = {
        "state":       TNEG_IDLE,
        "template_id": None,
        "proposed_by": None,
        "last_tick":   tick,
    }
    r_rel["touch_negotiation"] = dict(idle)
    p_rel["touch_negotiation"] = dict(idle)

    return {"ok": True, "result": new_state}


def recipient_touch_decision(recipient, proposer, world):
    """
    AI decision for an incoming touch proposal.
    Returns "accept" or "reject".

    Factors:
      - Relationship warmth / trust toward proposer
      - Template stage requirement vs current intimacy
      - Recipient personality (shy, romantic, cold)
      - Whether they are currently busy
    """
    pid = proposer["id"]
    rel = ensure_touch_negotiation(
        recipient.setdefault("relationships", {}).setdefault(pid, {}))
    inti = ensure_intimacy_state(rel)

    template_id = rel["touch_negotiation"].get("template_id", "hug")
    warmth      = rel.get("warmth",  50) / 100.0
    trust       = rel.get("trust",   50) / 100.0
    attraction  = rel.get("attraction", 0) / 100.0
    labels      = rel.get("labels", [])

    traits = set(recipient.get("traits", []) + recipient.get("personality_traits", []))

    # Base acceptance probability from warmth + attraction
    accept_prob = 0.40 + warmth * 0.35 + attraction * 0.20

    # Partner / spouse → almost always accepts touch
    if "partner" in labels or "spouse" in labels:
        accept_prob += 0.30
    elif "family" in labels:
        accept_prob += 0.15
    elif "friend_close" in labels:
        accept_prob += 0.10

    # Personality modifiers
    if "romantic" in traits or "affectionate" in traits:
        accept_prob += 0.15
    if "shy" in traits or "reserved" in traits:
        accept_prob -= 0.15
    if "cold" in traits or "distant" in traits:
        accept_prob -= 0.20
    if "easily_embarrassed" in traits:
        accept_prob -= 0.10

    # Stage-specific modifiers
    req_stage = TOUCH_STAGE_REQUIREMENT.get(template_id, 1)
    cur_stage = inti.get("intimacy_stage", 0)
    if cur_stage < req_stage:
        accept_prob -= 0.25  # asking for more than earned

    # Auto-accept if_reciprocated gestures (handshake, high_five)
    if template_id in TOUCH_AUTO_ACCEPT:
        return "accept"

    # Recipient busy?
    activity = recipient.get("activity", {})
    if activity and activity.get("type") not in (None, "idle", "wait", "socialize"):
        accept_prob -= 0.40  # don't interrupt important activities

    accept_prob = max(0.02, min(0.98, accept_prob))

    import random
    return "accept" if random.random() < accept_prob else "reject"


def _execute_touch(proposer, recipient, template_id, world):
    """
    Both characters begin the touch interaction simultaneously.
    Sets activity + animation_state on both.
    """
    init_anim, recv_anim = TOUCH_ANIMATIONS.get(
        template_id, ("anim_hug_give", "anim_hug_receive"))

    defs = world.get("defs", {})
    tpl  = defs.get("interaction_templates", {}).get(template_id, {})
    duration = tpl.get("duration_ticks", 4)

    tick = world.get("tick", 0)

    def _set_touch_activity(char, anim, partner_id):
        char["activity"] = {
            "type":               "touch_interaction",
            "interaction":        template_id,
            "phase":              "using",
            "phase_started_tick": tick,
            "duration":           duration,
            "target_id":          partner_id,
            "state":              {},
        }
        char["animation_state"] = anim

    _set_touch_activity(proposer, init_anim, recipient["id"])
    _set_touch_activity(recipient, recv_anim, proposer["id"])

    # Intimacy gains — comfort + progress toward next stage
    pid = proposer["id"]
    rid = recipient["id"]
    stage = TOUCH_STAGE_REQUIREMENT.get(template_id, 1)
    comfort_gain = COMFORT_GAIN.get(stage, 2)
    arousal_gain = AROUSAL_GAIN.get(stage, 0.02)

    for (c_a, c_b) in ((proposer, recipient), (recipient, proposer)):
        rel = c_a.setdefault("relationships", {}).setdefault(c_b["id"], {})
        ensure_intimacy_state(rel)
        rel["comfort"]      = min(100, rel.get("comfort", 0) + comfort_gain)
        rel["arousal_level"] = min(1.0, rel.get("arousal_level", 0.0) + arousal_gain)
        # Small warmth boost
        rel["warmth"] = min(100, rel.get("warmth", 50) + 1)


def _handle_touch_rejection(proposer, recipient, template_id, world):
    """
    Mild social consequence for rejected touch — much softer than intimate rejection.
    Only stings if asked for a kiss/cuddle from near-stranger.
    """
    req_stage = TOUCH_STAGE_REQUIREMENT.get(template_id, 1)
    cur_stage = proposer.get("relationships", {}).get(
        recipient["id"], {}).get("intimacy_stage", 0)

    severity = max(0.5, (req_stage - cur_stage) * 1.5)
    try:
        add_grievance(
            proposer, recipient["id"],
            "rejected_touch",
            world,
            severity=round(severity, 2),
            details={"template": template_id},
        )
    except Exception:
        pass


def tick_touch_proposals(world):
    """
    Per-tick: resolve pending touch proposals via AI decision.
    Called from tick_intimacy.

    For every relationship where touch_negotiation.state == PROPOSED
    and this character is NOT the proposer, call recipient_touch_decision
    and respond accordingly.  Expire stale proposals.
    """
    tick     = world.get("tick", 0)
    chars    = world.get("characters", {})

    seen_pairs = set()  # avoid processing the same proposal twice

    for cid, c in chars.items():
        for oid, rel in c.get("relationships", {}).items():
            tneg = rel.get("touch_negotiation", {})
            if tneg.get("state") != TNEG_PROPOSED:
                continue

            proposer_id = tneg.get("proposed_by")
            if proposer_id is None:
                continue

            # This character is the RECIPIENT (not the proposer)
            if cid == proposer_id:
                continue

            pair_key = tuple(sorted([cid, oid]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            proposer  = chars.get(proposer_id)
            recipient = c
            if not proposer:
                # Proposer gone — clear
                _clear_touch_neg(recipient, proposer_id, tick)
                continue

            # Expire stale proposals
            if tick - tneg.get("last_tick", 0) > TOUCH_PROPOSAL_TIMEOUT:
                _clear_touch_neg(proposer, recipient["id"], tick)
                _clear_touch_neg(recipient, proposer_id, tick)
                continue

            # Both must be at the same location
            if proposer.get("current_location") != recipient.get("current_location"):
                continue

            # AI decision
            decision = recipient_touch_decision(recipient, proposer, world)
            respond_to_touch_proposal(recipient, proposer, decision, world)


def _clear_touch_neg(c, other_id, tick):
    """Reset touch_negotiation to idle on c's relationship toward other_id."""
    rel = c.get("relationships", {}).get(other_id)
    if rel is not None:
        rel["touch_negotiation"] = {
            "state":       TNEG_IDLE,
            "template_id": None,
            "proposed_by": None,
            "last_tick":   tick,
        }
    if c.get("animation_state") == "waiting_touch":
        c["animation_state"] = "idle"


# ── Tick ──────────────────────────────────────────────────────────────────

def tick_intimacy(world):
    """
    Per-tick: decay arousal slowly on all relationships + resolve touch proposals.
    Called from sim_loop.
    """
    for c in world.get("characters", {}).values():
        for oid, rel in c.get("relationships", {}).items():
            if "arousal_level" in rel:
                rel["arousal_level"] = max(0.0, rel["arousal_level"] - AROUSAL_DECAY)
    # Resolve pending hug/kiss/cuddle proposals
    tick_touch_proposals(world)


# ── Rejection fallout ─────────────────────────────────────────────────────

def _handle_rejection_fallout(proposer, recipient, world):
    """
    If proposer has low rejection resilience, add mild grievance toward recipient.
    Repeated rejections build resentment.
    """
    profile    = proposer.get("attraction_profile") or {}
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


# ── Social consequences of ignoring rejection ─────────────────────────────

def handle_ignored_rejection(proposer, recipient, world):
    """
    Called when a character ignores a rejection and persists with an unwanted
    advance.  No criminal mechanics — consequences are entirely social:
      1. Deep disrespect grievance on the recipient
      2. Significant trust/resentment damage
      3. If in recipient's home → expulsion queued
      4. High chance (0.70 base) the recipient gossips → reputation damage
         and nearby characters hear of the transgression

    Returns "disrespected".
    """
    pid = proposer["id"]
    rid = recipient["id"]

    # 1. Grievance — this is a serious disrespect
    add_grievance(recipient, pid, "ignored_rejection", world,
                  details={"context": "ignored_intimate_rejection"})

    # 2. Relationship damage
    r_to_p = recipient.get("relationships", {}).setdefault(pid, {})
    r_to_p["trust"]      = max(0, r_to_p.get("trust",      50) - 35)
    r_to_p["resentment"] = min(100, r_to_p.get("resentment", 0) + 45)
    r_to_p["warmth"]     = max(0, r_to_p.get("warmth",     50) - 20)

    # 3. Expulsion — if recipient is in their own home, they throw the proposer out
    r_home = recipient.get("home_id") or recipient.get("household_id")
    p_home = proposer.get("home_id")  or proposer.get("household_id")
    if r_home and r_home != p_home:
        recipient.setdefault("reaction_queue", []).append({
            "type":      "expel_visitor",
            "target_id": pid,
            "reason":    "ignored_rejection",
            "tick":      world.get("tick", 0),
        })

    # 4. Gossip — recipient tells others what happened
    gossip_chance = 0.70
    r_traits = set(recipient.get("traits", []) + recipient.get("personality_traits", []))
    if "discreet" in r_traits or "shy" in r_traits:
        gossip_chance -= 0.20
    if "dramatic" in r_traits or "gossip" in r_traits or "outspoken" in r_traits:
        gossip_chance += 0.15
    gossip_chance = min(0.90, max(0.10, gossip_chance))

    if random.random() < gossip_chance:
        # Direct reputation hit for proposer
        apply_reputation_event(proposer, "disrespected_rejection", world,
                               severity=0.12, observer_id=rid)
        # Broadcast so any subscribed handler can spread word to the social network
        try:
            from core.event_bus import emit
            emit("social_transgression_gossip", {
                "gossiper_id":   rid,
                "accused_id":    pid,
                "transgression": "ignored_intimate_rejection",
                "tick":          world.get("tick", 0),
                "severity":      0.60,
            })
        except Exception:
            pass

    # Reset negotiation to idle
    tick = world.get("tick", 0)
    idle_neg = {
        "state": NEG_IDLE, "proposed_act": None, "proposed_by": None,
        "counter_act": None, "condition": None, "last_tick": tick,
    }
    if rid in proposer.get("relationships", {}):
        proposer["relationships"][rid]["negotiation"] = dict(idle_neg)
    if pid in recipient.get("relationships", {}):
        recipient["relationships"][pid]["negotiation"] = dict(idle_neg)

    return "disrespected"


# ── Context helper ────────────────────────────────────────────────────────

def get_intimacy_context(c, world):
    """
    Build LLM context for c's intimate relationships.
    Returns privacy-safe summary — no explicit act names, only stage + mood.
    """
    lines = []
    chars = {x["id"]: x for x in world.get("characters", {}).values()}

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
