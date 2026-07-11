"""
systems/harassment.py
──────────────────────
Models sexual harassment and inappropriate advances driven by the intersection
of libido, intoxication, sexism, and impaired self-control.

Core drive formula
──────────────────
  harassment_drive = effective_libido × sexism_level × (1.0 - self_control)

  effective_libido = base_libido
                   + ALCOHOL_LIBIDO_BOOST × alcohol_level
                   + DRUG_LIBIDO_BOOST    × drug_level
                   + PORN_LIBIDO_BOOST    × porn_habit

Pornography & fantasy reinforcement
─────────────────────────────────────
Each `watch_porn` or `masturbate` session increments porn_habit and slowly
drifts sexism_level upward (conditioning effect — treating women as objects).

Concealment (how openly acts are performed)
────────────────────────────────────────────
  concealment = self_control × (1 − alcohol_level) × (1 − drug_level × 0.5)

  Low concealment → act is visible to bystanders → reputation events fire.

Act severity tiers (by drive level)
────────────────────────────────────
  ≥ DRIVE_LEWD_STARE          → lewd_stare         (no social consequence if unnoticed)
  ≥ DRIVE_CRUDE_REMARK        → crude_remark        (verbal)
  ≥ DRIVE_UNWANTED_TOUCH      → unwanted_touch      (physical)
  ≥ DRIVE_EXPLICIT_PROP       → explicit_proposition (direct advance)

Fields on character
───────────────────
intoxication_state : {
    alcohol_level    : 0–1   (decays ~0.04/hr)
    drug_level       : 0–1   (decays ~0.025/hr)
    porn_habit       : 0–1   (accumulates; decays very slowly)
    libido_boost     : 0–1   (computed each tick from above)
    sessions_today   : int   (porn/masturbation sessions today)
}
"""

import random

# ── tunables ─────────────────────────────────────────────────────────────────
ALCOHOL_LIBIDO_BOOST    = 0.45
DRUG_LIBIDO_BOOST       = 0.35
PORN_LIBIDO_BOOST       = 0.20

ALCOHOL_DECAY_PER_TICK  = 0.00067   # ~0.04/hr at 1 tick/min → sober after ~25 hrs
DRUG_DECAY_PER_TICK     = 0.00042   # slower — ~0.025/hr

PORN_HABIT_GAIN         = 0.015     # per session
PORN_HABIT_DECAY        = 0.0003    # per day — very slow
PORN_SEXISM_DRIFT       = 0.002     # per session — slow desensitisation

# Drive thresholds
DRIVE_LEWD_STARE        = 0.10
DRIVE_CRUDE_REMARK      = 0.22
DRIVE_UNWANTED_TOUCH    = 0.38
DRIVE_EXPLICIT_PROP     = 0.55

# Harassment cooldown (ticks between acts targeting same person)
HARASSMENT_COOLDOWN     = 60 * 60 * 3  # 3 game-hours

# Trauma severity by act type
TRAUMA_BY_ACT = {
    "lewd_stare":           0.02,
    "crude_remark":         0.04,
    "unwanted_touch":       0.07,
    "explicit_proposition": 0.06,
}

# Reputation damage by act type when witnessed
REP_DAMAGE_BY_ACT = {
    "lewd_stare":           "minor_creep_behaviour",
    "crude_remark":         "verbal_harassment",
    "unwanted_touch":       "sexual_harassment",
    "explicit_proposition": "sexual_harassment",
}

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def init_intoxication_state(c):
    c.setdefault("intoxication_state", {
        "alcohol_level":   0.0,
        "drug_level":      0.0,
        "porn_habit":      0.0,
        "libido_boost":    0.0,
        "sessions_today":  0,
        "last_harass_tick": {},   # {target_id: tick}
    })


def consume_alcohol(c, units, world):
    """
    Called when a character drinks something with alcohol_units.
    units: standard alcohol units (1 unit ≈ 1 glass of wine)
    """
    init_intoxication_state(c)
    state = c["intoxication_state"]
    # Each unit raises level by ~0.08 (capped at 1.0)
    state["alcohol_level"] = min(1.0, state["alcohol_level"] + units * 0.08)
    _recompute_libido_boost(c)


def consume_drug(c, drug_id, world):
    """Called when a character consumes a drug item."""
    init_intoxication_state(c)
    state = c["intoxication_state"]
    # Generic drug effect — can be tuned by drug_id later
    state["drug_level"] = min(1.0, state["drug_level"] + 0.30)
    _recompute_libido_boost(c)


def on_porn_session(c, world):
    """
    Called after watch_porn or masturbate interaction completes.
    Reinforces porn_habit and slowly drifts sexism_level.
    """
    init_intoxication_state(c)
    state = c["intoxication_state"]
    state["porn_habit"]    = min(1.0, state["porn_habit"] + PORN_HABIT_GAIN)
    state["sessions_today"] = state.get("sessions_today", 0) + 1
    _recompute_libido_boost(c)

    # Sexism drift — treating women as objects reinforces sexist attitudes
    imp = c.setdefault("impulse_state", {})
    current_sexism = imp.get("sexism_level", 0.0)
    # Drift only for male characters (main pathway described)
    if c.get("sex") == "male":
        imp["sexism_level"] = min(1.0, current_sexism + PORN_SEXISM_DRIFT)


def tick_harassment(world):
    """
    Per-tick: decay intoxication, recompute libido boost, check for harassment acts.
    Called every sim tick from sim_loop.
    """
    characters = world.get("characters", {})
    tick       = world.get("tick", 0)

    for c in characters.values():
        init_intoxication_state(c)
        state = c["intoxication_state"]

        # Decay substances
        if state["alcohol_level"] > 0:
            state["alcohol_level"] = max(0.0, state["alcohol_level"] - ALCOHOL_DECAY_PER_TICK)
        if state["drug_level"] > 0:
            state["drug_level"]    = max(0.0, state["drug_level"]    - DRUG_DECAY_PER_TICK)

        _recompute_libido_boost(c)

        # Only evaluate harassment for adults
        if c.get("age", 0) < 18:
            continue

        drive = _compute_harassment_drive(c)
        if drive < DRIVE_LEWD_STARE:
            continue

        # Pick a target in the same location
        target = _pick_target(c, world)
        if not target:
            continue

        # Cooldown check
        t_id = target.get("id", "")
        last = state["last_harass_tick"].get(t_id, 0)
        if tick - last < HARASSMENT_COOLDOWN:
            continue

        act_type = _drive_to_act(drive)
        concealment = _compute_concealment(c)

        _execute_harassment(c, target, act_type, concealment, world)
        state["last_harass_tick"][t_id] = tick


def tick_harassment_daily(world):
    """
    Daily: decay porn_habit, reset sessions_today.
    Called from sim_loop daily bucket.
    """
    for c in world.get("characters", {}).values():
        state = c.get("intoxication_state")
        if not state:
            continue
        state["porn_habit"]    = max(0.0, state["porn_habit"] - PORN_HABIT_DECAY)
        state["sessions_today"] = 0
        _recompute_libido_boost(c)


def get_harassment_context(c, world):
    """Context lines for LLM."""
    lines = []
    state = c.get("intoxication_state", {})

    al = state.get("alcohol_level", 0.0)
    dl = state.get("drug_level",    0.0)
    ph = state.get("porn_habit",    0.0)
    lb = state.get("libido_boost",  0.0)

    imp    = c.get("impulse_state", {})
    sexism = imp.get("sexism_level", 0.0)
    sc     = imp.get("self_control", 0.5)

    if al >= 0.25:
        lines.append(
            f"Intoxicated (alcohol level {al:.2f}) — inhibitions lowered, "
            "libido elevated, self-control impaired."
        )
    if dl >= 0.20:
        lines.append(
            f"Under influence of drugs (level {dl:.2f}) — significantly impaired judgement."
        )
    if ph >= 0.40:
        lines.append(
            f"Heavy pornography habit ({ph:.2f}) — conditioned to view partners as objects; "
            "feeds into sexist attitudes and reduced empathy."
        )
    if lb >= 0.25 and (sexism >= 0.40 or sc <= 0.35):
        drive = _compute_harassment_drive(c)
        if drive >= DRIVE_CRUDE_REMARK:
            lines.append(
                f"Harassment drive {drive:.2f}: likely to make inappropriate advances, "
                f"crude remarks, or act on sexual impulses with little restraint "
                f"(sexism={sexism:.2f}, self-control={sc:.2f})."
            )
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _recompute_libido_boost(c):
    state  = c["intoxication_state"]
    al     = state.get("alcohol_level", 0.0)
    dl     = state.get("drug_level",    0.0)
    ph     = state.get("porn_habit",    0.0)
    boost  = (ALCOHOL_LIBIDO_BOOST * al
              + DRUG_LIBIDO_BOOST  * dl
              + PORN_LIBIDO_BOOST  * ph)
    state["libido_boost"] = min(1.0, boost)


def _compute_harassment_drive(c):
    """
    harassment_drive = effective_libido × sexism_level × (1 - self_control)
    """
    profile  = c.get("attraction_profile") or {}
    base_lib = profile.get("libido", 0.50)
    boost    = c.get("intoxication_state", {}).get("libido_boost", 0.0)
    eff_lib  = min(1.0, base_lib + boost)

    imp      = c.get("impulse_state", {})
    sexism   = imp.get("sexism_level", 0.0)
    sc       = imp.get("self_control", 0.5)

    return eff_lib * sexism * (1.0 - sc)


def _compute_concealment(c):
    """
    How much the character tries to hide the harassment.
    0 = completely open/blatant; 1 = covert.
    """
    imp  = c.get("impulse_state", {})
    sc   = imp.get("self_control", 0.5)
    al   = c.get("intoxication_state", {}).get("alcohol_level", 0.0)
    dl   = c.get("intoxication_state", {}).get("drug_level",    0.0)
    return sc * (1.0 - al) * (1.0 - dl * 0.5)


def _drive_to_act(drive):
    if drive >= DRIVE_EXPLICIT_PROP:
        return "explicit_proposition"
    elif drive >= DRIVE_UNWANTED_TOUCH:
        return "unwanted_touch"
    elif drive >= DRIVE_CRUDE_REMARK:
        return "crude_remark"
    else:
        return "lewd_stare"


def _pick_target(harasser, world):
    """
    Pick a nearby female (or same-sex if gay) adult character as target.
    Prefers strangers or low-relationship characters (less social inhibition).
    """
    h_id  = harasser.get("id", "")
    h_sex = harasser.get("sex", "male")
    h_ori = harasser.get("sexual_orientation", "heterosexual")
    loc   = harasser.get("current_location")
    if not loc:
        return None

    by_loc = world.get("characters_by_location", {})
    chars  = world.get("characters", {})
    nearby = [chars.get(cid) for cid in by_loc.get(loc, []) if cid != h_id]
    nearby = [c for c in nearby if c and c.get("age", 0) >= 18]

    # Filter by orientation
    if h_ori in ("heterosexual",):
        targets = [c for c in nearby if c.get("sex") in ("female", "intersex")]
    elif h_ori == "homosexual":
        targets = [c for c in nearby if c.get("sex") == h_sex]
    else:
        targets = [c for c in nearby if c.get("sex") in ("female", "intersex", h_sex)]

    if not targets:
        return None

    # Prefer targets with lower relationship trust (harasser is less inhibited toward strangers)
    def trust_score(t):
        rel = harasser.get("relationships", {}).get(t.get("id", ""), {})
        return rel.get("trust", 0)

    targets.sort(key=trust_score)
    return targets[0]


def _execute_harassment(harasser, target, act_type, concealment, world):
    h_id = harasser.get("id", "")
    t_id = target.get("id",   "")
    tick = world.get("tick",   0)

    # Trauma on target
    severity = TRAUMA_BY_ACT.get(act_type, 0.04)
    try:
        from systems.trauma import add_trauma_event
        add_trauma_event(target, f"harassment_{act_type}", h_id, world,
                         severity_override=severity)
    except Exception:
        pass

    # Grievance: target holds grievance against harasser
    try:
        from systems.grievances import add_grievance
        add_grievance(target, h_id, "sexual_harassment", world)
    except Exception:
        pass

    # Self-confidence hit for target
    sc_hit = {"lewd_stare": 0.01, "crude_remark": 0.02,
              "unwanted_touch": 0.03, "explicit_proposition": 0.02}
    target["self_confidence"] = max(
        0.05, target.get("self_confidence", 0.60) - sc_hit.get(act_type, 0.02)
    )

    # Reputation damage if witnessed (low concealment or witnessed)
    if concealment < 0.50 or act_type in ("unwanted_touch", "explicit_proposition"):
        loc = harasser.get("current_location")
        if loc:
            observers = [
                cid for cid in world.get("characters_by_location", {}).get(loc, [])
                if cid not in (h_id, t_id)
            ]
            if observers or concealment < 0.25:
                try:
                    from systems.reputation import apply_reputation_event
                    rep_event = REP_DAMAGE_BY_ACT.get(act_type, "sexual_harassment")
                    apply_reputation_event(harasser, rep_event, world)
                except Exception:
                    pass

                # Gossip: witnesses tell others
                if observers and act_type in ("unwanted_touch", "explicit_proposition"):
                    try:
                        from core.events import emit
                        emit("social_transgression_gossip", {
                            "transgressor_id": h_id,
                            "victim_id":       t_id,
                            "gossiper_id":     observers[0],
                            "severity":        severity * 12,
                            "tick":            tick,
                        }, world)
                    except Exception:
                        pass

    # Target's partner gets anger
    _notify_partner(target, h_id, act_type, world)

    # Emit event for LLM awareness
    try:
        from core.events import emit
        emit("harassment_act", {
            "harasser_id":  h_id,
            "target_id":    t_id,
            "act_type":     act_type,
            "concealment":  round(concealment, 2),
            "tick":         tick,
        }, world)
    except Exception:
        pass


def _notify_partner(target, harasser_id, act_type, world):
    """If target has a partner, they get an anger grievance against the harasser."""
    t_rels = target.get("relationships", {})
    chars  = world.get("characters", {})
    for pid, rel in t_rels.items():
        if rel.get("relationship_type") in ("partner", "spouse", "boyfriend", "girlfriend"):
            partner = chars.get(pid)
            if partner:
                try:
                    from systems.grievances import add_grievance
                    add_grievance(partner, harasser_id, "partner_harassed", world)
                    # Anger pressure spike
                    imp = partner.setdefault("impulse_state", {})
                    imp["anger_pressure"] = min(
                        1.0, imp.get("anger_pressure", 0) + 0.20
                    )
                except Exception:
                    pass
            break
