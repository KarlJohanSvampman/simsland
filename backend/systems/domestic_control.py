"""
systems/domestic_control.py

Domestic control and abuse mechanics for controlling/abusive partner archetypes.

The model captures:
  1. Target selection — abusers preferentially target intimate partners when the
     power differential is high and social support is low (low perceived risk).

  2. Negging — periodic undermining of partner's self-esteem via cutting remarks,
     dismissals, and put-downs.  Degrades c["self_confidence"] over time.

  3. Shame threats — abuser uses knowledge of partner's secrets (from secrets system)
     to threaten exposure.  Raises partner relationship["fear"] and reduces
     their willingness to leave or seek help.

  4. Isolation pressure — abuser discourages or sabotages partner's relationships
     with support network (friends/family/coworkers).  Flagged as grievance source.

  5. Physical escalation — when anger boilover selects target, domestic_abuser
     trait biases selection toward intimate partner regardless of grievance score.
     Wire: impulse._trigger_outburst() checks intimate_target_bias.

Victim effects accumulate via trauma system:
  - self_confidence degradation
  - intimacy_avoidance
  - fear in the relationship (relationship["fear"])
  - dependency increase (trauma bonding — harder to leave)

Called from sim_loop on a medium cadence (every ~20 ticks).
"""

import random

from systems.grievances import add_grievance

# ── Constants ──────────────────────────────────────────────────────────────
NEGGING_CHANCE_PER_TICK     = 0.04   # per medium tick, if conditions met
SHAME_THREAT_CHANCE         = 0.25   # per tick if abuser knows partner secrets
SELF_CONFIDENCE_NEGGING_HIT = 0.04   # per negging event
SELF_CONFIDENCE_MIN         = 0.05   # floor — prevents total collapse
FEAR_GAIN_PER_THREAT        = 0.08   # relationship["fear"] rise per shame threat
DEPENDENCY_GAIN             = 0.04   # intimacy bonding under abuse
LEAVE_THRESHOLD             = 0.30   # self_confidence below this → hard to leave

# Power differential assessment
SUPPORT_NETWORK_WEIGHT = 0.35   # strong support makes victim more likely to leave
FINANCIAL_DEPENDENCE_WEIGHT = 0.25


# ── Main tick ──────────────────────────────────────────────────────────────

def tick_domestic_control(world):
    """
    Medium cadence pass.  For each character with controlling traits,
    assess intimate relationships and apply control tactics.
    """
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    for cid, c in chars.items():
        if c.get("is_offscreen"):
            continue
        traits = set(c.get("traits", []) + c.get("personality_traits", []))
        if not ({"controlling_partner", "domestic_abuser"} & traits):
            continue

        control_score = 0.6 if "controlling_partner" in traits else 0.0
        control_score = max(control_score, 0.9 if "domestic_abuser" in traits else 0.0)

        # Find intimate partner(s)
        partners = _find_intimate_partners(c, chars)
        for partner_id in partners:
            partner = chars.get(partner_id)
            if not partner:
                continue
            _apply_control_tactics(c, partner, control_score, world)


# ── Target selection helper for impulse system ─────────────────────────────

def get_domestic_target(abuser, chars):
    """
    Called by impulse._trigger_outburst() to override target selection.
    If abuser has domestic_abuser/controlling_partner trait, returns the
    intimate partner as priority target (if present and power diff is high).
    Returns partner_id or None.
    """
    traits = set(abuser.get("traits", []) + abuser.get("personality_traits", []))
    if not ({"controlling_partner", "domestic_abuser"} & traits):
        return None

    intimate_bias = 0.80 if "domestic_abuser" in traits else 0.50

    if random.random() > intimate_bias:
        return None   # sometimes directs at general target

    partners = _find_intimate_partners(abuser, chars)
    if not partners:
        return None

    # Prefer partner with lowest self_confidence + smallest support network
    best = None
    best_vuln = -1.0
    for pid in partners:
        p = chars.get(pid)
        if not p:
            continue
        vuln = _vulnerability_score(abuser, p, chars)
        if vuln > best_vuln:
            best_vuln = vuln
            best      = pid

    return best


# ── Control tactics ────────────────────────────────────────────────────────

def _apply_control_tactics(abuser, partner, control_score, world):
    """Apply a mix of psychological control tactics to the partner this tick."""
    pid = partner["id"]
    aid = abuser["id"]

    rel_a_to_p = abuser.get("relationships", {}).setdefault(pid, {})
    rel_p_to_a = partner.get("relationships", {}).setdefault(aid, {})

    # ── Negging ──────────────────────────────────────────────────────────
    if random.random() < NEGGING_CHANCE_PER_TICK * control_score:
        _apply_negging(abuser, partner, rel_p_to_a, world)

    # ── Shame / secret threats ───────────────────────────────────────────
    known_secrets = _get_known_secrets(abuser, partner)
    if known_secrets and random.random() < SHAME_THREAT_CHANCE * control_score:
        _apply_shame_threat(abuser, partner, known_secrets[0], rel_p_to_a, world)

    # ── Isolation pressure ───────────────────────────────────────────────
    if random.random() < 0.02 * control_score:
        _apply_isolation_pressure(abuser, partner, world)

    # ── Dependency increase (trauma bonding) ────────────────────────────
    dep = rel_p_to_a.get("dependency", 0)
    rel_p_to_a["dependency"] = min(100, dep + DEPENDENCY_GAIN * control_score * 100)


def _apply_negging(abuser, partner, rel_p_to_a, world):
    """Undermine partner's self-esteem."""
    p_traits = set(partner.get("traits", []) + partner.get("personality_traits", []))

    # Vulnerability modifier
    vuln = 1.0
    if "low_self_esteem" in p_traits:
        vuln = 1.40
    if "codependent" in p_traits:
        vuln = max(vuln, 1.30)
    if "confident" in p_traits or "assertive" in p_traits:
        vuln = 0.60

    hit = SELF_CONFIDENCE_NEGGING_HIT * vuln
    partner["self_confidence"] = round(
        max(SELF_CONFIDENCE_MIN, partner.get("self_confidence", 0.60) - hit), 4
    )

    # Fear rises slightly — partner learns this person is unpredictable/cruel
    rel_p_to_a["fear"] = min(100, rel_p_to_a.get("fear", 0) + 3)

    # Trauma accumulation (slow, from repeated incidents)
    try:
        from systems.trauma import add_trauma_event
        add_trauma_event(partner, "betrayal_intimate", abuser["id"], world,
                         severity_override=0.04,
                         details={"tactic": "negging"})
    except Exception:
        pass

    try:
        from core.event_bus import emit
        emit("domestic_control_tactic", {
            "abuser_id":  abuser["id"],
            "victim_id":  partner["id"],
            "tactic":     "negging",
            "tick":       world.get("tick", 0),
        })
    except Exception:
        pass


def _apply_shame_threat(abuser, partner, secret, rel_p_to_a, world):
    """
    Threaten to expose partner's secret to keep them in line.
    Raises partner's fear and suppresses help-seeking.
    """
    rel_p_to_a["fear"] = min(100, rel_p_to_a.get("fear", 0) + int(FEAR_GAIN_PER_THREAT * 100))

    # Partner too afraid to confide — reduces support network effectiveness
    partner["_shame_suppressed"] = True   # checked by trauma.decide_report equivalent

    # Minor trauma
    try:
        from systems.trauma import add_trauma_event
        add_trauma_event(partner, "betrayal_intimate", abuser["id"], world,
                         severity_override=0.06,
                         details={"tactic": "shame_threat", "secret_type": secret.get("type")})
    except Exception:
        pass

    try:
        from core.event_bus import emit
        emit("domestic_control_tactic", {
            "abuser_id":  abuser["id"],
            "victim_id":  partner["id"],
            "tactic":     "shame_threat",
            "secret":     secret.get("type", "unknown"),
            "tick":       world.get("tick", 0),
        })
    except Exception:
        pass


def _apply_isolation_pressure(abuser, partner, world):
    """
    Discourage partner from maintaining outside relationships.
    Adds a grievance on abuser's behalf and flags key relationships as "monitored".
    """
    aid = abuser["id"]
    pid = partner["id"]

    # Abuser adds jealousy grievances against partner's close contacts
    for oid, rel in partner.get("relationships", {}).items():
        if oid == aid:
            continue
        trust = rel.get("trust", 0)
        if trust < 40:
            continue
        # Flag the contact relationship as under pressure
        rel["_isolation_pressure"] = True
        # Abuser gets grievance against this contact (jealousy of their influence)
        add_grievance(abuser, oid, "partner_jealousy", world, severity=6.0,
                      details={"monitored_contact": oid, "partner": pid})
        break   # one target per tick to keep it gradual


# ── Helpers ────────────────────────────────────────────────────────────────

def _find_intimate_partners(c, chars):
    """Return list of char IDs who are intimate partners (stage ≥ 3 or labeled)."""
    partners = []
    for oid, rel in c.get("relationships", {}).items():
        if oid not in chars:
            continue
        stage  = rel.get("intimacy_stage", 0)
        labels = rel.get("labels", [])
        if stage >= 3 or "partner" in labels or "spouse" in labels:
            partners.append(oid)
    return partners


def _vulnerability_score(abuser, partner, chars):
    """
    0-1 score: how vulnerable the partner is to abuse (low support, dependent, low confidence).
    Higher = abuser more likely to target this person.
    """
    sc = partner.get("self_confidence", 0.60)
    vuln = (1.0 - sc) * 0.40   # low self-confidence → higher vulnerability

    # Support network size (trusted friends/family)
    support = sum(
        1 for oid, rel in partner.get("relationships", {}).items()
        if oid in chars and oid != abuser["id"]
        and rel.get("trust", 0) >= 55
        and rel.get("state", "") in ("close_friend", "friend", "family")
    )
    vuln += max(0, (3 - support)) * SUPPORT_NETWORK_WEIGHT * 0.10

    # Financial dependence proxy: partner earns less or isn't employed
    if not partner.get("employed"):
        vuln += FINANCIAL_DEPENDENCE_WEIGHT * 0.20

    # Codependent trait
    p_traits = set(partner.get("traits", []) + partner.get("personality_traits", []))
    if "codependent" in p_traits:
        vuln += 0.15
    if "low_self_esteem" in p_traits:
        vuln += 0.10

    return min(1.0, vuln)


def _get_known_secrets(abuser, partner):
    """Return secrets abuser knows about partner (from relationship knowledge)."""
    known = []
    for sec in partner.get("secrets", []):
        # Abuser knows if in known_by list or they're intimate enough to have learned
        if abuser["id"] in sec.get("known_by", []):
            known.append(sec)
        elif (partner.get("relationships", {})
              .get(abuser["id"], {})
              .get("intimacy_stage", 0)) >= 4:
            # Deep intimacy — assume some secrets were shared
            known.append(sec)
    return known


# ── Context helper ─────────────────────────────────────────────────────────

def get_domestic_control_context(c, world):
    """LLM context for victim: fear, self-confidence, isolation pressure."""
    lines = []
    sc = c.get("self_confidence", 0.60)
    if sc < 0.30:
        lines.append(f"self_confidence critically low ({sc:.2f}) — psychologically worn down")
    elif sc < 0.45:
        lines.append(f"self_confidence low ({sc:.2f}) — feels inadequate, doubts own judgment")

    if c.get("_shame_suppressed"):
        lines.append("afraid to seek help — partner has threatened exposure/shame")

    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {ch["id"]: ch for ch in chars}

    for oid, rel in c.get("relationships", {}).items():
        fear = rel.get("fear", 0)
        if fear >= 40:
            name = chars.get(oid, {}).get("name", oid)
            lines.append(f"deeply afraid of {name} (fear={fear}) — feels trapped")
        elif fear >= 20:
            name = chars.get(oid, {}).get("name", oid)
            lines.append(f"fearful of {name} (fear={fear})")

    return {"domestic_situation": lines} if lines else {}


# ── Community outrage when abuse is revealed ───────────────────────────────

OUTRAGE_ANGER_BOOST = 0.35   # anger pressure added to outraged bystander


def on_abuse_revealed(abuser_id, victim_id, world):
    """
    Called when domestic abuse becomes known (gossip, witness, victim discloses).
    Nearby men who learn about it:
      - get significant anger pressure boost toward abuser
      - protective types may immediately confront
    """
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    abuser = chars.get(abuser_id)
    victim = chars.get(victim_id)
    if not abuser or not victim:
        return

    from systems.impulse import add_anger_pressure

    for cid, c in chars.items():
        if cid in (abuser_id, victim_id) or c.get("is_offscreen"):
            continue
        if c.get("sex") != "male":
            continue   # this branch specifically models male community response

        # Must know victim or abuser to care
        knows_victim = c.get("relationships", {}).get(victim_id, {}).get("trust", 0) >= 20
        knows_abuser = c.get("relationships", {}).get(abuser_id, {}).get("familiarity", 0) >= 10
        if not (knows_victim or knows_abuser):
            continue

        c_traits = set(c.get("traits", []) + c.get("personality_traits", []))

        # Base outrage — most men react to revealed domestic abuse
        anger = OUTRAGE_ANGER_BOOST
        if "protective" in c_traits or "compassionate" in c_traits:
            anger *= 1.40
        if "aggressive" in c_traits or "hot_tempered" in c_traits:
            anger *= 1.25
        if knows_victim and c.get("relationships", {}).get(victim_id, {}).get("trust", 0) >= 55:
            anger *= 1.60   # close friend of victim

        add_anger_pressure(c, anger, "witnessed_domestic_abuse", world)

        # Grievance against abuser
        from systems.grievances import add_grievance
        add_grievance(c, abuser_id, "witnessed_transgression", world,
                      severity=18.0,
                      details={"context": "domestic_abuse_revealed", "victim": victim_id})

        # Emit confrontation for very high anger + protective
        if anger >= 0.45 and ("protective" in c_traits or "aggressive" in c_traits):
            try:
                from core.event_bus import emit
                emit("confrontation_desired", {
                    "initiator_id": cid,
                    "target_id":    abuser_id,
                    "score":        70.0,
                    "context":      "defending_abuse_victim",
                    "victim_id":    victim_id,
                })
            except Exception:
                pass


# ── Victim revenge paths ───────────────────────────────────────────────────

REVENGE_TRAUMA_THRESHOLD   = 0.45   # trauma.score above which revenge considered
REVENGE_FEAR_THRESHOLD     = 35     # relationship fear above which direct confrontation avoided
POISON_PLANNING_TICKS      = 60 * 60 * 24 * 7   # one week planning window


def check_victim_revenge(victim, world):
    """
    Called periodically (daily cadence) for victims of domestic abuse.
    If trauma is high + direct escape seems impossible, victim may plan revenge.

    Three paths weighted by traits and impulse control:
      1. Direct violence    — low impulse control + physical opportunity
      2. Poison / covert    — patient + calculated + desperate
      3. Staged accident    — high intelligence + planning + low impulsivity
    """
    trauma = victim.get("trauma", {})
    if trauma.get("score", 0) < REVENGE_TRAUMA_THRESHOLD:
        return

    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    v_traits = set(victim.get("traits", []) + victim.get("personality_traits", []))
    imp      = victim.get("impulse_state", {})
    sc       = imp.get("self_control", 0.5)

    # Find the abuser (highest fear relationship)
    abuser_id = None
    max_fear  = 0
    for oid, rel in victim.get("relationships", {}).items():
        fear = rel.get("fear", 0)
        if fear > max_fear and oid in chars:
            max_fear  = fear
            abuser_id = oid

    if not abuser_id or max_fear < REVENGE_FEAR_THRESHOLD:
        return

    # Already planning? Don't stack
    if victim.get("_revenge_plan"):
        _advance_revenge_plan(victim, abuser_id, world)
        return

    abuser = chars[abuser_id]
    trauma_score = trauma["score"]
    anger_p      = imp.get("anger_pressure", 0.0)

    # ── Path 1: Direct violence (impulse-driven) ────────────────────────
    # Low self-control + high anger = snap attack when abuser is vulnerable
    if sc < 0.30 and anger_p > 0.65:
        if random.random() < (anger_p - 0.50) * 1.5:
            _execute_direct_attack(victim, abuser, world)
            return

    # ── Path 2: Poison / covert ─────────────────────────────────────────
    # Patient + calculated + not physically dominant
    poison_prone = (
        ("patient" in v_traits or "calculating" in v_traits or "cunning" in v_traits)
        and sc > 0.35
        and trauma_score > 0.60
    )
    # ── Path 3: Staged accident ─────────────────────────────────────────
    # High intelligence + long-suffering + methodical
    staged_prone = (
        ("intelligent" in v_traits or "methodical" in v_traits or "strategic" in v_traits)
        and sc > 0.50
        and trauma_score > 0.55
    )

    if not (poison_prone or staged_prone):
        return

    # Decide which covert path to begin planning
    if poison_prone and staged_prone:
        method = random.choice(["poison", "staged_accident"])
    elif poison_prone:
        method = "poison"
    else:
        method = "staged_accident"

    victim["_revenge_plan"] = {
        "method":        method,
        "target_id":     abuser_id,
        "plan_started":  world.get("tick", 0),
        "plan_ready":    False,
        "execution_tick": world.get("tick", 0) + POISON_PLANNING_TICKS,
    }

    try:
        from core.event_bus import emit
        emit("revenge_plan_started", {
            "planner_id": victim["id"],
            "target_id":  abuser_id,
            "method":     method,
            "tick":       world.get("tick", 0),
        })
    except Exception:
        pass


def _advance_revenge_plan(victim, abuser_id, world):
    """Tick a revenge plan toward execution."""
    plan = victim.get("_revenge_plan", {})
    if plan.get("target_id") != abuser_id:
        return

    tick = world.get("tick", 0)
    if tick < plan.get("execution_tick", 0):
        return   # still planning

    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    abuser = chars.get(abuser_id)
    if not abuser:
        victim.pop("_revenge_plan", None)
        return

    method = plan.get("method", "poison")
    _execute_covert_revenge(victim, abuser, method, world)
    victim.pop("_revenge_plan", None)


def _execute_direct_attack(victim, abuser, world):
    """Snap attack — victim strikes abuser when opportunity allows."""
    vid = victim["id"]
    aid = abuser["id"]

    # Physical outcome — victim may be smaller/weaker; outcome uncertain
    from systems.domestic_control import _vulnerability_score
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    # Build fighting strength
    v_bf = victim.get("body_features", {})
    a_bf = abuser.get("body_features", {})
    BUILD = {"slim": 0.3, "average": 0.5, "athletic": 0.8, "stocky": 0.7, "heavy": 0.55}
    v_str = BUILD.get(v_bf.get("build", "average"), 0.5) + random.gauss(0, 0.15)
    a_str = BUILD.get(a_bf.get("build", "average"), 0.5) + random.gauss(0, 0.15)

    # Surprise factor: victim chooses moment → +0.25 boost
    v_str += 0.25

    victim_wins = v_str > a_str

    if victim_wins:
        health = abuser.setdefault("health", {})
        health["pain"] = min(1.0, health.get("pain", 0.0) + 0.40)
        health.setdefault("conditions", [])
        if "injured" not in health["conditions"]:
            health["conditions"].append("injured")
    else:
        # Failed attack — abuser retaliates; victim takes more damage
        health = victim.setdefault("health", {})
        health["pain"] = min(1.0, health.get("pain", 0.0) + 0.35)

    # Trauma release — some relief regardless of outcome
    trauma = victim.get("trauma", {})
    trauma["score"] = max(0.0, trauma.get("score", 0) - 0.08)

    try:
        from core.event_bus import emit
        emit("fight_physical", {
            "parties":  [vid, aid],
            "winner":   vid if victim_wins else aid,
            "loser":    aid if victim_wins else vid,
            "context":  "domestic_revenge_direct",
            "tick":     world.get("tick", 0),
        })
    except Exception:
        pass


def _execute_covert_revenge(victim, abuser, method, world):
    """
    Execute a planned covert revenge after planning period.
    poison: direct harm attempt (may succeed/fail based on opportunity)
    staged_accident: engineered incident (requires specific world condition)
    """
    vid = victim["id"]
    aid = abuser["id"]
    tick = world.get("tick", 0)

    # Success probability — increases with planning time + victim traits
    v_traits = set(victim.get("traits", []) + victim.get("personality_traits", []))
    success_base = 0.40
    if "calculating" in v_traits or "cunning" in v_traits:
        success_base += 0.15
    if "intelligent" in v_traits:
        success_base += 0.10
    if method == "staged_accident":
        success_base += 0.10   # harder to detect

    success = random.random() < success_base

    if success:
        health = abuser.setdefault("health", {})
        severity = 0.55 if method == "poison" else 0.45
        health["pain"] = min(1.0, health.get("pain", 0.0) + severity)
        conditions = health.setdefault("conditions", [])
        if method == "poison":
            if "poisoned" not in conditions:
                conditions.append("poisoned")
        else:
            if "injured" not in conditions:
                conditions.append("injured")

        # Trauma relief for victim — acted on urge
        trauma = victim.get("trauma", {})
        trauma["score"] = max(0.0, trauma.get("score", 0) - 0.12)
    else:
        # Failed — abuser may suspect, escalating danger
        rel = victim.get("relationships", {}).setdefault(aid, {})
        rel["fear"] = min(100, rel.get("fear", 0) + 15)

    try:
        from core.event_bus import emit
        emit("covert_revenge_attempt", {
            "actor_id":  vid,
            "target_id": aid,
            "method":    method,
            "success":   success,
            "tick":      tick,
        })
    except Exception:
        pass


# ── Authority-figure concealment ───────────────────────────────────────────
# Abusers in positions of authority (police, doctors, managers, politicians)
# enjoy institutional protection: reports are less believed, colleagues cover for
# them, and they can leverage the legal/professional system against the victim.

# Jobs that confer concealment bonus
AUTHORITY_JOBS = {
    "police_officer", "detective", "sheriff", "security_guard",
    "doctor", "nurse", "therapist", "psychiatrist",
    "lawyer", "judge",
    "manager", "director", "ceo", "executive",
    "politician", "city_official",
    "teacher", "professor",
}

AUTHORITY_CONCEALMENT_BASE = 0.35   # reduces gossip spread + report belief


def _compute_authority_concealment(abuser):
    """
    Returns 0-1 concealment multiplier.  Higher = harder to expose, reports
    less believed, institutional protection available.
    """
    traits  = set(abuser.get("traits", []) + abuser.get("personality_traits", []))
    job     = abuser.get("job", {})
    job_id  = (job.get("job_template") or job.get("title") or "").lower().replace(" ", "_")

    concealment = 0.0
    if "authority_abuser" in traits:
        concealment += 0.50
    if any(j in job_id for j in AUTHORITY_JOBS):
        concealment += AUTHORITY_CONCEALMENT_BASE
    if abuser.get("reputation", {}).get("community", 0.5) > 0.70:
        concealment += 0.15   # respected in community → even less believed against

    return min(0.90, concealment)


def _apply_authority_retaliation(abuser, victim, world):
    """
    When victim tries to report: authority abuser can use institutional access
    to file counter-reports, threaten victim's job, or manipulate legal process.
    """
    traits = set(abuser.get("traits", []) + abuser.get("personality_traits", []))
    if "authority_abuser" not in traits and "retaliation_access" not in str(traits):
        return

    aid = abuser["id"]
    vid = victim["id"]

    # Increase victim fear
    rel_v_to_a = victim.setdefault("relationships", {}).setdefault(aid, {})
    rel_v_to_a["fear"] = min(100, rel_v_to_a.get("fear", 0) + 20)

    # Suppress help-seeking
    victim["_shame_suppressed"] = True

    # Add a grievance FROM victim against abuser (legal retaliation)
    add_grievance(victim, aid, "betrayed", world, severity=18.0,
                  details={"context": "authority_retaliation"})

    try:
        from core.event_bus import emit
        emit("authority_retaliation", {
            "abuser_id": aid,
            "victim_id": vid,
            "tick":      world.get("tick", 0),
        })
    except Exception:
        pass


# Patch on_abuse_revealed to respect concealment
_original_on_abuse_revealed = on_abuse_revealed

def on_abuse_revealed(abuser_id, victim_id, world):
    """
    Extended version: authority concealment reduces spread probability.
    """
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    abuser = chars.get(abuser_id)
    if abuser:
        concealment = _compute_authority_concealment(abuser)
        # Concealment suppresses revelation entirely some fraction of the time
        if random.random() < concealment * 0.6:
            # Covered up — victim may face retaliation instead
            victim = chars.get(victim_id)
            if victim:
                _apply_authority_retaliation(abuser, victim, world)
            return   # suppressed — community never hears

    # Passes through to original logic
    _original_on_abuse_revealed(abuser_id, victim_id, world)


# ── Quid-pro-quo / transactional power abuse ──────────────────────────────
# The abuser is a gatekeeper: controls career contacts, job references, casting
# decisions, promotions, or professional opportunities.  Victims face a choice
# between tolerating the abuse and losing access.

QP_BASE_CHANCE    = 0.08   # per medium tick, chance abuser applies pressure
QP_COMPLIANCE_REP = 0.04   # abuser gets small reputation hit even when complied with
QP_REFUSAL_BLOCK  = True   # refused victims get blacklisted from abuser's network


def tick_quid_pro_quo(world):
    """
    Medium cadence.  For each power_gatekeeper character, assess dependents
    in their professional network and apply transactional pressure.
    """
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    for cid, c in chars.items():
        if c.get("is_offscreen"):
            continue
        traits = set(c.get("traits", []) + c.get("personality_traits", []))
        if "power_gatekeeper" not in traits:
            continue

        # Find professionally dependent contacts
        for oid, rel in c.get("relationships", {}).items():
            if oid not in chars:
                continue
            target = chars[oid]
            if _is_professionally_dependent(target, c, chars):
                if random.random() < QP_BASE_CHANCE:
                    _apply_qp_pressure(c, target, world)


def _is_professionally_dependent(target, gatekeeper, chars):
    """True if gatekeeper controls something target needs for career."""
    # Same industry + gatekeeper has higher seniority/reputation
    t_job = target.get("job", {}).get("sector", "")
    g_job = gatekeeper.get("job", {}).get("sector", "")
    if t_job and t_job == g_job:
        t_rep = target.get("reputation", {}).get("community", 0.5)
        g_rep = gatekeeper.get("reputation", {}).get("community", 0.5)
        if g_rep > t_rep + 0.20:
            return True
    # Direct reports (company match)
    if (target.get("company_id") and
        target.get("company_id") == gatekeeper.get("company_id") and
        gatekeeper.get("job", {}).get("title") in
            ("Manager", "Director", "CEO", "Executive", "Supervisor")):
        return True
    return False


def _apply_qp_pressure(gatekeeper, target, world):
    """
    Gatekeeper leverages their position for inappropriate demands.
    Target decides to comply or refuse based on career drive vs self-respect.
    """
    gid = gatekeeper["id"]
    tid = target["id"]

    t_traits = set(target.get("traits", []) + target.get("personality_traits", []))
    g_traits = set(gatekeeper.get("traits", []) + gatekeeper.get("personality_traits", []))

    # Target's compliance probability
    career_drive   = 0.60 if "career_ambitious" in t_traits else 0.30
    self_respect   = target.get("self_confidence", 0.60)
    desperation    = 1.0 - (target.get("wealth", 500) / 2000.0)
    desperation    = max(0, min(1, desperation))

    compliance_p = (career_drive * 0.4 + desperation * 0.4 - self_respect * 0.3 + 0.1)
    compliance_p = max(0.05, min(0.85, compliance_p))

    complies = random.random() < compliance_p

    if complies:
        # Target gets career benefit but psychological harm
        target["self_confidence"] = round(
            max(SELF_CONFIDENCE_MIN, target.get("self_confidence", 0.60) - 0.06), 4
        )
        rel_t_to_g = target.setdefault("relationships", {}).setdefault(gid, {})
        rel_t_to_g["fear"]     = min(100, rel_t_to_g.get("fear", 0) + 8)
        rel_t_to_g["resentment"] = min(100, rel_t_to_g.get("resentment", 0) + 12)

        # Trauma accumulation
        try:
            from systems.trauma import add_trauma_event
            add_trauma_event(target, "betrayal_intimate", gid, world,
                             severity_override=0.07,
                             details={"tactic": "quid_pro_quo_compliance"})
        except Exception:
            pass

        # Gatekeeper gets minor reputation hit (these things leak)
        if random.random() < 0.10:
            try:
                from systems.reputation import apply_reputation_event
                apply_reputation_event(gatekeeper, "professional_misconduct", world,
                                       severity=QP_COMPLIANCE_REP, observer_id=tid)
            except Exception:
                pass

    else:
        # Refusal — gatekeeper retaliates by blocking opportunities
        rel_g_to_t = gatekeeper.setdefault("relationships", {}).setdefault(tid, {})
        rel_g_to_t["_career_blocked"] = True
        rel_g_to_t["resentment"] = min(100, rel_g_to_t.get("resentment", 0) + 20)

        # Target gets grievance — recognizes the coercion
        add_grievance(target, gid, "threatened", world, severity=15.0,
                      details={"context": "quid_pro_quo_refused"})

        # May gossip / report — higher chance when self-confidence is higher
        gossip_p = target.get("self_confidence", 0.60) * 0.50
        if random.random() < gossip_p:
            try:
                from core.event_bus import emit
                emit("social_transgression_gossip", {
                    "gossiper_id":   tid,
                    "accused_id":    gid,
                    "transgression": "quid_pro_quo_pressure",
                    "tick":          world.get("tick", 0),
                    "severity":      0.75,
                })
            except Exception:
                pass

    try:
        from core.event_bus import emit
        emit("quid_pro_quo_incident", {
            "gatekeeper_id": gid,
            "target_id":     tid,
            "complied":      complies,
            "tick":          world.get("tick", 0),
        })
    except Exception:
        pass
