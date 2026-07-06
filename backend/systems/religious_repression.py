"""
systems/religious_repression.py
────────────────────────────────
Models the psychological impact of being raised in a deeply religious,
sex-negative or homophobic family environment.

Key mechanics
─────────────
• Family objects can carry a `values` dict:
    religious_strictness : 0.0–1.0  (how devout/authoritarian)
    sex_negative         : bool     (sex is shameful/only for reproduction)
    homophobic           : bool     (homosexuality is sinful/forbidden)

• Characters get a `repression_state` field tracking accumulated shame,
  repression score, identity conflict, and addiction/self-destruction risk.

• Daily tick:
    - For each character that grew up in (or still lives in) a strict family:
        * LGBT+ identity vs homophobic family → escalating conflict events,
          trauma accumulation, identity crisis mental-health flag
        * Casual sexuality / pornography vs sex-negative family → shame
          events, self-esteem hits
    - Repression scores decay very slowly without re-exposure (family contact)
    - Repression effects propagate to:
        * intimacy.py  — reluctance / avoidance / dysfunction flags
        * trauma.py    — trauma events of type "identity_shame"
        * impulse.py   — raised addiction_pressure, self-destructive urge

Constants
─────────
CONFLICT_CHANCE_PER_DAY : base probability of a family conflict event
REPRESSION_DAILY_GAIN   : per-day increase while living with strict family
REPRESSION_SLOW_DECAY   : per-day decrease when no longer cohabiting
SHAME_TRAUMA_SEVERITY   : trauma score added per shame event
IDENTITY_CONFLICT_THRESH: repression score that triggers identity crisis flag
ADDICTION_PRESSURE_GAIN : per-day increase in addiction_pressure from repression
"""

import random

# ── tunables ────────────────────────────────────────────────────────────────
CONFLICT_CHANCE_PER_DAY       = 0.08    # 8 % chance of overt confrontation each day
REPRESSION_DAILY_GAIN         = 0.004   # while cohabiting with strict family
REPRESSION_SLOW_DECAY         = 0.001   # per day once independent
SHAME_TRAUMA_SEVERITY         = 0.07
IDENTITY_CONFLICT_THRESH      = 0.45    # triggers identity_crisis mental health flag
DEPRESSION_THRESH             = 0.55    # above this → depression risk escalates
ADDICTION_PRESSURE_GAIN       = 0.002   # per day while repressed
PORN_SHAME_DISCOVERY_CHANCE   = 0.05    # daily chance parent discovers + reacts
SELF_DESTRUCT_THRESH          = 0.70    # repression → self-destructive behaviour

# orientations considered LGBT+ for conflict purposes
LGBT_ORIENTATIONS = {"homosexual", "bisexual", "pansexual", "asexual", "demisexual"}

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def init_repression_state(c):
    """Stamp default repression_state on a character if absent."""
    c.setdefault("repression_state", {
        "repression_score":       0.0,   # 0–1 accumulated shame/suppression
        "identity_conflict":      False, # LGBT+ identity vs family values
        "shame_events":           0,     # lifetime count
        "addiction_pressure":     0.0,   # 0–1 risk accumulator
        "self_destructive_urge":  0.0,   # 0–1
        "intimacy_avoidance":     0.0,   # 0–1 sexual avoidance level
        "porn_shame_flag":        False, # discovered consuming forbidden content
        "last_conflict_tick":     0,
    })


def tick_religious_repression(world):
    """
    Call once per in-game day (daily bucket in sim_loop).
    """
    characters = world.get("characters", {})
    families   = world.get("families",   {})

    for c in characters.values():
        age = c.get("age", 0)
        if age < 10:
            continue  # no meaningful religious conflict before ~10

        fam_id = c.get("family_id")
        family = families.get(fam_id) if fam_id else None
        values = (family or {}).get("values", {})
        strictness = values.get("religious_strictness", 0.0)

        if strictness < 0.20:
            # Not a meaningfully strict family — passive decay only
            _decay_repression(c)
            continue

        sex_negative = values.get("sex_negative", False)
        homophobic   = values.get("homophobic",   False)

        # Is the character still in the household?
        cohabiting = _is_cohabiting_with_family(c, family, world)

        if cohabiting:
            _accumulate_repression(c, strictness, sex_negative, homophobic, world)
        else:
            _decay_repression(c)
            # Grown up — residual effects still tick
            _apply_residual_effects(c, world)

        _propagate_effects(c, world)


def get_repression_context(c, world):
    """Return a list of plain-text context lines for the LLM context builder."""
    rs = c.get("repression_state", {})
    score = rs.get("repression_score", 0.0)
    if score < 0.10:
        return []

    lines = []
    fam_id = c.get("family_id")
    family = world.get("families", {}).get(fam_id) if fam_id else None
    values = (family or {}).get("values", {})

    if values.get("religious_strictness", 0) >= 0.20:
        lines.append(
            f"Raised in a deeply religious family "
            f"(strictness {values['religious_strictness']:.2f}). "
            + ("Sex is treated as shameful outside reproduction. " if values.get("sex_negative") else "")
            + ("Homosexuality is condemned as sinful. " if values.get("homophobic") else "")
        )

    if rs.get("identity_conflict"):
        lines.append(
            "Experiencing severe internal conflict between their LGBT+ identity "
            "and family/religious values — source of deep shame and confusion."
        )

    if score >= DEPRESSION_THRESH:
        lines.append(
            f"Sexual repression score {score:.2f}: prone to depressive episodes, "
            "emotional withdrawal, and difficulty forming intimate connections."
        )

    if rs.get("addiction_pressure", 0) >= 0.40:
        lines.append(
            "Elevated addiction pressure from internalised shame — risk of substance "
            "use or compulsive behaviour as coping mechanism."
        )

    if rs.get("self_destructive_urge", 0) >= 0.50:
        lines.append(
            "Self-destructive urges present — may engage in risky, self-harming, "
            "or reckless behaviour."
        )

    if rs.get("intimacy_avoidance", 0) >= 0.30:
        lines.append(
            f"Intimacy avoidance level {rs['intimacy_avoidance']:.2f}: "
            "difficulty initiating or accepting sexual/romantic contact."
        )

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_cohabiting_with_family(c, family, world):
    """True if character shares a home location with at least one parent."""
    if not family:
        return False
    c_home = c.get("home_id")
    if not c_home:
        return False
    members = family.get("members", [])
    relations = family.get("relations", {})
    c_id = c.get("id", "")
    characters = world.get("characters", {})
    for mid in members:
        if mid == c_id:
            continue
        rel_key = f"{c_id}:{mid}"
        rel = relations.get(rel_key, "")
        if rel in ("child", "parent"):
            other = characters.get(mid)
            if other and other.get("home_id") == c_home:
                return True
    return False


def _accumulate_repression(c, strictness, sex_negative, homophobic, world):
    """Build repression score while living under strict family."""
    init_repression_state(c)
    rs = c["repression_state"]
    gain = REPRESSION_DAILY_GAIN * strictness

    orientation = c.get("sexual_orientation", "heterosexual")
    is_lgbt     = orientation in LGBT_ORIENTATIONS

    # Identity conflict: LGBT+ in homophobic household
    if is_lgbt and homophobic:
        rs["identity_conflict"] = True
        gain *= 1.8  # accelerated repression
        if random.random() < CONFLICT_CHANCE_PER_DAY:
            _trigger_family_conflict(c, "identity_shame", strictness, world)

    # Pornography discovery
    if sex_negative and random.random() < PORN_SHAME_DISCOVERY_CHANCE * strictness:
        rs["porn_shame_flag"] = True
        _trigger_family_conflict(c, "porn_shame", strictness, world)

    # General sexual curiosity conflict (adults)
    if sex_negative and c.get("age", 0) >= 16:
        if random.random() < CONFLICT_CHANCE_PER_DAY * 0.4 * strictness:
            _trigger_family_conflict(c, "sexual_curiosity_shame", strictness, world)

    rs["repression_score"] = min(1.0, rs["repression_score"] + gain)
    rs["addiction_pressure"] = min(1.0, rs.get("addiction_pressure", 0) + ADDICTION_PRESSURE_GAIN * strictness)


def _decay_repression(c):
    """Slow passive decay once out of the strict household."""
    rs = c.get("repression_state")
    if not rs:
        return
    rs["repression_score"]      = max(0.0, rs["repression_score"] - REPRESSION_SLOW_DECAY)
    rs["addiction_pressure"]    = max(0.0, rs.get("addiction_pressure", 0) - REPRESSION_SLOW_DECAY * 0.5)
    rs["self_destructive_urge"] = max(0.0, rs.get("self_destructive_urge", 0) - REPRESSION_SLOW_DECAY)
    rs["intimacy_avoidance"]    = max(0.0, rs.get("intimacy_avoidance", 0) - REPRESSION_SLOW_DECAY * 0.7)


def _apply_residual_effects(c, world):
    """
    Even when independent, high repression keeps producing effects —
    they just accumulate more slowly.
    """
    rs = c.get("repression_state", {})
    score = rs.get("repression_score", 0.0)
    if score < 0.20:
        return

    orientation = c.get("sexual_orientation", "heterosexual")
    is_lgbt     = orientation in LGBT_ORIENTATIONS

    if rs.get("identity_conflict") and is_lgbt:
        # Residual identity shame — ongoing depression/avoidance even when free
        if random.random() < 0.03 * score:
            _add_shame_trauma(c, "residual_identity_shame", score * 0.6, world)


def _propagate_effects(c, world):
    """
    Push repression values into other character fields that the
    intimacy/pleasure/impulse systems read.
    """
    init_repression_state(c)
    rs    = c["repression_state"]
    score = rs["repression_score"]

    # Intimacy avoidance grows with repression
    target_avoid = score * 0.80
    current      = rs.get("intimacy_avoidance", 0.0)
    rs["intimacy_avoidance"] = current + (target_avoid - current) * 0.05  # smooth

    # Self-destructive urge driven by repression above threshold
    if score >= SELF_DESTRUCT_THRESH:
        rs["self_destructive_urge"] = min(
            1.0,
            rs.get("self_destructive_urge", 0) + 0.003
        )

    # Identity conflict → identity_crisis mental health flag
    if rs.get("identity_conflict") and score >= IDENTITY_CONFLICT_THRESH:
        mh = c.setdefault("mental_health", {})
        if "identity_crisis" not in mh:
            mh["identity_crisis"] = {
                "active":    True,
                "severity":  min(1.0, score),
                "onset_tick": world.get("tick", 0),
            }
            _add_shame_trauma(c, "identity_crisis_onset", 0.15, world)

    # Depression risk: update existing depression entry or seed new one
    if score >= DEPRESSION_THRESH:
        mh = c.setdefault("mental_health", {})
        dep = mh.setdefault("depression", {"active": False, "severity": 0.0})
        if not dep.get("active") and random.random() < (score - DEPRESSION_THRESH) * 0.10:
            dep["active"]   = True
            dep["severity"] = round(score * 0.60, 2)
            dep["onset_tick"] = world.get("tick", 0)

    # Stamp intimacy_avoidance onto character root so intimacy.py can read it
    c["intimacy_avoidance"] = rs["intimacy_avoidance"]

    # Addiction pressure feeds impulse system
    imp = c.setdefault("impulse_state", {})
    imp["addiction_pressure"] = rs.get("addiction_pressure", 0.0)


def _trigger_family_conflict(c, conflict_type, strictness, world):
    """Fire a conflict event and add trauma."""
    tick = world.get("tick", 0)
    rs   = c["repression_state"]

    # Cooldown: max one confrontation per 3 in-game days
    if tick - rs.get("last_conflict_tick", 0) < 3 * 24 * 60:
        return

    rs["last_conflict_tick"] = tick
    rs["shame_events"] = rs.get("shame_events", 0) + 1

    severity_map = {
        "identity_shame":          SHAME_TRAUMA_SEVERITY * 1.60,
        "porn_shame":              SHAME_TRAUMA_SEVERITY * 0.90,
        "sexual_curiosity_shame":  SHAME_TRAUMA_SEVERITY * 0.70,
    }
    severity = severity_map.get(conflict_type, SHAME_TRAUMA_SEVERITY) * strictness

    _add_shame_trauma(c, conflict_type, severity, world)

    # Self-confidence hit
    sc = c.get("self_confidence", 0.60)
    c["self_confidence"] = max(0.05, sc - 0.04 * strictness)

    # Emit event for context / other systems
    try:
        from core.events import emit
        emit("family_religious_conflict", {
            "character_id":   c.get("id"),
            "conflict_type":  conflict_type,
            "strictness":     strictness,
            "tick":           tick,
        }, world)
    except Exception:
        pass


def _add_shame_trauma(c, trauma_type, severity, world):
    """Add a trauma event via systems/trauma.py."""
    try:
        from systems.trauma import add_trauma_event
        add_trauma_event(c, trauma_type, None, world, severity_override=severity)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Family values generation (called from family.py / character_gen.py)
# ─────────────────────────────────────────────────────────────────────────────

def generate_family_values():
    """
    Return a `values` dict for a new family.
    ~15 % of families are deeply religious/strict.
    """
    r = random.random()
    if r > 0.15:
        return {"religious_strictness": 0.0, "sex_negative": False, "homophobic": False}

    # Strictly religious family
    strictness   = random.uniform(0.50, 1.00)
    sex_negative = strictness >= 0.55 or random.random() < 0.70
    homophobic   = strictness >= 0.60 or random.random() < 0.75
    return {
        "religious_strictness": round(strictness, 2),
        "sex_negative":         sex_negative,
        "homophobic":           homophobic,
    }
