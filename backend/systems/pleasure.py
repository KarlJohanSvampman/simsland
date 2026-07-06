"""
systems/pleasure.py

Pleasure, climax, and satisfaction engine for intimate encounters.

Key design principles:
- Male characters climax faster on average; probability declines with each
  successive session (refractory), but skill with a specific partner improves.
- Female climax probability starts lower but increases with partner experience —
  the more a character has been intimate with this specific person, the better
  they know how to pleasure them. Tracked via sexual_preferences.partner_experience.
- Pleasure score is composite: position fit, kink alignment, arousal level,
  comfort, and mutual preference matching.
- Aftercare need is flagged post-encounter based on kinks and intensity.
"""

import random

# ── Base climax probabilities ─────────────────────────────────────────────
# Per full intimate encounter (stage 6 acts completed)
BASE_CLIMAX_MALE   = 0.92   # most of the time
BASE_CLIMAX_FEMALE = 0.40   # lower baseline; experience with partner improves this

# How much each session with the SAME partner improves female climax probability
FEMALE_CLIMAX_SKILL_GAIN = 0.04   # +4% per session, caps at ~90%
FEMALE_CLIMAX_CAP        = 0.90

# How much refractory cycle reduces male 2nd-climax probability
MALE_REFRACTORY_PENALTY  = 0.60   # 60% less likely to climax again within same session

# Kink satisfaction bonus when partner shares kink (mutual kink match)
MUTUAL_KINK_PLEASURE_BONUS = 0.15
# Penalty when a kink_hard_no is violated
KINK_HARD_NO_PENALTY       = -0.40

# Position pleasure modifiers loaded from definitions
# (accessed via world["defs"]["positions_registry"])

# Satisfaction impact on relationship
CLIMAX_SATISFACTION_GAIN     = 8.0    # relationship satisfaction boost
NO_CLIMAX_SATISFACTION_DELTA = -2.0   # mild dissatisfaction for recipient
MUTUAL_CLIMAX_BONUS          = 5.0    # extra if both climax


# ── Core pleasure computation ─────────────────────────────────────────────

def compute_pleasure_score(c, other, act, position_id, world):
    """
    Compute 0-1 pleasure score for character c during an intimate act with other.

    Factors:
      - Position preference match
      - Kink alignment (shared kinks → bonus; hard-no violated → penalty)
      - Current arousal level
      - Comfort in this relationship
      - Kink mutual match
    Returns float 0-1.
    """
    defs = world.get("defs", {})
    prefs     = c.get("sexual_preferences", {})
    o_prefs   = other.get("sexual_preferences", {})
    positions_reg = defs.get("positions_registry", {})
    kinks_reg     = defs.get("kinks_registry", {})

    rel   = c.get("relationships", {}).get(other["id"], {})
    comfort  = rel.get("comfort",       0) / 100.0
    arousal  = rel.get("arousal_level", 0.0)
    c_arousal = c.get("arousal_level", 0.0)

    base = 0.50

    # 1. Arousal contribution
    combined_arousal = (arousal + c_arousal) / 2.0
    base += combined_arousal * 0.20

    # 2. Comfort contribution
    base += comfort * 0.15

    # 3. Position preference
    if position_id:
        pos = positions_reg.get(position_id, {})
        if position_id in prefs.get("positions_liked", []):
            base += 0.10
        elif position_id in prefs.get("positions_disliked", []):
            base -= 0.12
        # Position's own pleasure modifier for this role
        role = _get_role_for_act(c, other, act, pos)
        pm = pos.get("pleasure_modifier", {}).get(role, 0.0)
        base += pm
        # Emotional intimacy modifier
        base += pos.get("emotional_intimacy", 0.0) * 0.1

    # 4. Kink alignment
    c_kinks   = set(prefs.get("kinks",         []))
    o_kinks   = set(o_prefs.get("kinks",       []))
    c_hard_no = set(prefs.get("kinks_hard_no", []))
    o_hard_no = set(o_prefs.get("kinks_hard_no", []))

    # Mutual kinks — both enjoy the same thing
    mutual = c_kinks & o_kinks
    for kink_id in mutual:
        kink = kinks_reg.get(kink_id, {})
        if kink.get("mutual"):
            base += kink.get("pleasure_bonus", 0.0) * 1.5  # mutual = bigger bonus
        else:
            base += kink.get("pleasure_bonus", 0.0)

    # One-sided kinks that c has and other is willing to do
    one_sided = c_kinks - o_kinks - o_hard_no
    for kink_id in one_sided:
        kink = kinks_reg.get(kink_id, {})
        if not kink.get("mutual"):
            base += kink.get("pleasure_bonus", 0.0) * 0.5  # partial satisfaction

    # Hard-no violations — other performs something c absolutely doesn't want
    violated = o_kinks & c_hard_no
    for _ in violated:
        base += KINK_HARD_NO_PENALTY

    return max(0.0, min(1.0, round(base, 4)))


def _get_role_for_act(c, other, act, position):
    """Return 'initiator' or 'recipient' for this character in this act/position."""
    # Heuristic: if c proposed the act they're initiator
    c_rel = c.get("relationships", {}).get(other["id"], {})
    neg   = c_rel.get("negotiation", {})
    if neg.get("proposed_by") == c["id"]:
        return "initiator"
    return "recipient"


# ── Climax engine ─────────────────────────────────────────────────────────

def compute_climax(c, other, pleasure_score, world, session_climax_count=0):
    """
    Return True/False: does character c climax during this encounter?

    For male characters: high base probability, reduced by session_climax_count.
    For female characters: base probability + (partner_experience * SKILL_GAIN).

    pleasure_score modulates the final probability.
    """
    sex = c.get("sex", "male")
    prefs = c.get("sexual_preferences", {})
    partner_exp = prefs.get("partner_experience", {}).get(other["id"], 0)

    if sex == "male":
        if session_climax_count == 0:
            base_prob = BASE_CLIMAX_MALE
        else:
            base_prob = BASE_CLIMAX_MALE * (MALE_REFRACTORY_PENALTY ** session_climax_count)

        # Sexual dependency: conditioned to dominant partner style
        dep = c.get("sexual_dependency", {})
        dep_score = dep.get("dependency_score", 0.0)
        if dep_score > 0.20:
            if dep.get("dominant_partner_id") == other.get("id"):
                base_prob = min(0.98, base_prob * (1.0 + dep_score * 0.30))   # easier with them
            else:
                base_prob = base_prob * (1.0 - dep_score * 0.40)              # harder without them
    else:
        # Female: starts lower, improves with experience with THIS partner
        skill_bonus = min(FEMALE_CLIMAX_CAP - BASE_CLIMAX_FEMALE,
                          partner_exp * FEMALE_CLIMAX_SKILL_GAIN)
        base_prob = min(FEMALE_CLIMAX_CAP, BASE_CLIMAX_FEMALE + skill_bonus)

    # Pleasure score modulates: high pleasure → more likely to climax
    prob = base_prob * (0.7 + pleasure_score * 0.6)
    prob = max(0.02, min(0.98, prob))

    return random.random() < prob


def resolve_encounter_outcome(initiator, recipient, act_id, position_id, world):
    """
    Full encounter resolution: compute pleasure for both parties, determine who
    climaxes and in what order, apply relationship satisfaction effects, increment
    partner_experience counter.

    Returns a dict with the full outcome for logging and animation use.
    """
    defs    = world.get("defs", {})
    acts_reg = defs.get("sexual_acts", {})
    act      = acts_reg.get(act_id, {})

    # Pleasure scores
    i_pleasure = compute_pleasure_score(initiator, recipient, act, position_id, world)
    r_pleasure = compute_pleasure_score(recipient, initiator, act, position_id, world)

    # Climax resolution — male tends to go first
    # Determine order based on sex and pleasure score
    i_sex = initiator.get("sex", "male")
    r_sex = recipient.get("sex",  "female")

    i_climax_prob_mod = 0
    r_climax_prob_mod = 0

    # Male tends to climax before female unless high skill
    if i_sex == "male" and r_sex == "female":
        # Initiator goes first round
        i_climaxed = compute_climax(initiator, recipient, i_pleasure, world, 0)
        if i_climaxed:
            # After male climax, female probability slightly reduced (act may end)
            r_pleasure_adj = r_pleasure * 0.75
        else:
            r_pleasure_adj = r_pleasure
        r_climaxed = compute_climax(recipient, initiator, r_pleasure_adj, world, 0)
    elif r_sex == "male" and i_sex == "female":
        # Recipient (male) likely goes first, then initiator (female)
        r_climaxed_first = compute_climax(recipient, initiator, r_pleasure, world, 0)
        if r_climaxed_first:
            i_pleasure_adj = i_pleasure * 0.75
        else:
            i_pleasure_adj = i_pleasure
        i_climaxed = compute_climax(initiator, recipient, i_pleasure_adj, world, 0)
        r_climaxed = r_climaxed_first
    else:
        # Same sex or both same sex — no ordering bias
        i_climaxed = compute_climax(initiator, recipient, i_pleasure, world, 0)
        r_climaxed = compute_climax(recipient, initiator, r_pleasure, world, 0)

    # Satisfaction delta on relationship
    _apply_satisfaction(initiator, recipient, i_climaxed, r_climaxed)
    _apply_satisfaction(recipient, initiator, r_climaxed, i_climaxed)

    # Increment partner experience counter
    _increment_partner_experience(initiator, recipient)
    _increment_partner_experience(recipient, initiator)

    # Aftercare flag
    i_needs_aftercare = _needs_aftercare(initiator, world)
    r_needs_aftercare = _needs_aftercare(recipient, world)

    outcome = {
        "act_id":            act_id,
        "position_id":       position_id,
        "initiator_id":      initiator["id"],
        "recipient_id":      recipient["id"],
        "initiator_pleasure": round(i_pleasure, 3),
        "recipient_pleasure": round(r_pleasure, 3),
        "initiator_climaxed": i_climaxed,
        "recipient_climaxed": r_climaxed,
        "mutual_climax":      i_climaxed and r_climaxed,
        "initiator_aftercare_needed": i_needs_aftercare,
        "recipient_aftercare_needed": r_needs_aftercare,
        "tick": world.get("tick", 0),
    }

    # Store on relationship history
    i_rel = initiator.setdefault("relationships", {}).setdefault(recipient["id"], {})
    i_rel.setdefault("encounter_history", []).append(outcome)
    r_rel = recipient.setdefault("relationships", {}).setdefault(initiator["id"], {})
    r_rel.setdefault("encounter_history", []).append(outcome)

    return outcome


def _apply_satisfaction(c, other, c_climaxed, other_climaxed):
    """Apply satisfaction to c's relationship with other."""
    rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
    delta = 0.0
    if c_climaxed:
        delta += CLIMAX_SATISFACTION_GAIN
    else:
        delta += NO_CLIMAX_SATISFACTION_DELTA
    if c_climaxed and other_climaxed:
        delta += MUTUAL_CLIMAX_BONUS

    # Update a 'sexual_satisfaction' field (separate from general friendship)
    current = rel.get("sexual_satisfaction", 50.0)
    rel["sexual_satisfaction"] = max(0.0, min(100.0, current + delta))

    # Bleed into chemistry and attraction slightly
    rel["chemistry"] = max(0, min(100, rel.get("chemistry", 0) + delta * 0.3))


def _increment_partner_experience(c, other):
    """Track how many sessions c has had with other."""
    prefs = c.setdefault("sexual_preferences", {})
    exp   = prefs.setdefault("partner_experience", {})
    exp[other["id"]] = exp.get(other["id"], 0) + 1


def _needs_aftercare(c, world):
    """Return True if this character needs significant aftercare."""
    prefs    = c.get("sexual_preferences", {})
    kinks    = set(prefs.get("kinks", []))
    defs     = world.get("defs", {})
    kinks_reg = defs.get("kinks_registry", {})

    # High-need kinks
    high_need = {"aftercare_important", "bondage", "masochism", "sadism",
                 "rough_sex", "light_bdsm"}
    if kinks & high_need:
        return True
    # High anxiety also generates aftercare need
    profile = c.get("attraction_profile", {}) or {}
    return profile.get("sexual_anxiety", 0.0) > 0.6


# ── Context helper ────────────────────────────────────────────────────────

def get_pleasure_context(c, world):
    """Summarise recent encounter history for LLM context."""
    lines = []
    chars = {x["id"]: x for x in world.get("characters", [])}

    for oid, rel in c.get("relationships", {}).items():
        history = rel.get("encounter_history", [])
        if not history:
            continue
        last = history[-1]
        name = chars.get(oid, {}).get("name", oid)
        sat  = rel.get("sexual_satisfaction", 50.0)
        exp  = c.get("sexual_preferences", {}).get("partner_experience", {}).get(oid, 0)
        climaxed_str = "climaxed" if last.get("initiator_climaxed" if last["initiator_id"] == c["id"] else "recipient_climaxed") else "did not climax"
        lines.append(f"{name}: satisfaction={sat:.0f}/100, sessions={exp}, last_encounter={climaxed_str}")

    return {"sexual_history": lines} if lines else {}
