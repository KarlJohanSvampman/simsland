"""
systems/rival_cascade.py

Attraction privacy + reveal mechanic + rival cascade.

Privacy model:
  A woman's attraction to a man is private by default —
  relationship["attraction_visible"] = False on her side.
  No other character can observe or infer her interest unless she makes
  a public approach.

Reveal:
  reveal_attraction(woman, man, world)
    Sets attraction_visible = True and emits "attraction_revealed".
    Called from intimacy.py when a female character INITIATES a romantic/
    intimate proposal (stage ≥ 1 initiation toward a man).

Rival cascade:
  check_rival_cascade(woman, man, world)
    After a reveal, scans all other female characters who also have hidden
    interest in the same man (attraction > RIVAL_THRESHOLD, not yet visible).
    Each rival:
      1. Learns about the competition (attraction_visible updated internally)
      2. Gets a grievance against the revealing woman ("romantic_rivalry")
      3. Raises their own seduction intent (intimacy initiation_bias bump)
      4. Chance of direct conflict — verbal → physical fight

Competition escalation:
  _escalate_rivalry(rival, revealer, man, world)
    Verbal confrontation → always.
    Physical fight chance: based on rivalry score + aggression trait + envy_sensitivity.
    Fight outcome: one loses (injury + humiliation grievance), winner gets
    a temporary seduction confidence boost.
"""

import random
import uuid

from systems.grievances import add_grievance

# ── Thresholds ────────────────────────────────────────────────────────────
RIVAL_THRESHOLD      = 30    # attraction score (0-100) above which woman is a competitor
FIGHT_BASE_CHANCE    = 0.20  # base probability of physical fight when rivalry is triggered
SEDUCTION_BIAS_BOOST = 0.25  # added to initiation_bias when rivalry detected


# ── Reveal mechanic ───────────────────────────────────────────────────────

def reveal_attraction(woman, man, world):
    """
    Mark woman's attraction to man as publicly visible.
    Should be called when she initiates a romantic/intimate approach.
    No-op if already visible.
    Returns True if this is a new reveal (triggers cascade check).
    """
    wid = woman["id"]
    mid = man["id"]

    rel = woman.setdefault("relationships", {}).setdefault(mid, {})
    if rel.get("attraction_visible"):
        return False   # already public

    rel["attraction_visible"] = True

    # Mirror: man now knows she's interested
    m_rel = man.get("relationships", {}).setdefault(wid, {})
    m_rel["known_attracted_to_me"] = True

    try:
        from core.event_bus import emit
        emit("attraction_revealed", {
            "revealer_id": wid,
            "target_id":   mid,
            "tick":        world.get("tick", 0),
        })
    except Exception:
        pass

    return True


def check_rival_cascade(woman, man, world):
    """
    After woman reveals attraction to man, check for other women who also
    have hidden interest.  Trigger rivalry responses for each.

    Returns list of rival character ids who responded.
    """
    wid = woman["id"]
    mid = man["id"]

    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    rivals_triggered = []

    for cid, candidate in chars.items():
        if cid == wid or cid == mid:
            continue
        # Only female characters' hidden attraction is private
        if candidate.get("sex") not in ("female", "intersex"):
            continue
        if candidate.get("is_offscreen"):
            continue

        c_rel = candidate.get("relationships", {}).get(mid, {})
        attraction = c_rel.get("attraction", 0)

        # Must have real interest and it must still be hidden
        if attraction < RIVAL_THRESHOLD:
            continue
        if c_rel.get("attraction_visible"):
            continue   # already declared; rivalry already known

        # Rival learns about the competition
        _on_rival_learns(candidate, woman, man, attraction, world)
        rivals_triggered.append(cid)

    return rivals_triggered


# ── Internal rival response ───────────────────────────────────────────────

def _on_rival_learns(rival, revealer, man, rival_attraction, world):
    """
    Called for each competitor who hears of the reveal.
    """
    rid  = rival["id"]
    wid  = revealer["id"]
    mid  = man["id"]

    # 1. Grievance against revealer — she made her move first
    envy_mult = rival.get("attraction_profile", {}).get("envy_sensitivity", 0.5)
    grievance_sev = 10.0 + (rival_attraction / 100.0) * 12.0 * envy_mult
    add_grievance(
        rival, wid,
        "romantic_rivalry",
        world,
        severity=round(grievance_sev, 2),
        details={"target_man": mid, "context": "rival_revealed_attraction"},
    )

    # 2. Rival raises her own seduction drive
    r_profile = rival.setdefault("attraction_profile", {})
    r_profile["initiation_bias"] = min(
        1.0,
        r_profile.get("initiation_bias", 0.0) + SEDUCTION_BIAS_BOOST
    )

    # 3. Rivalry flag on rival→revealer relationship
    rev_rel = rival.setdefault("relationships", {}).setdefault(wid, {})
    rev_rel["rivalry"]  = min(100, rev_rel.get("rivalry", 0) + int(grievance_sev * 1.5))
    rev_rel.setdefault("conflict_flags", []).append("romantic_rivalry")

    # 4. Escalation — verbal confrontation + possible physical fight
    _escalate_rivalry(rival, revealer, man, world)


def _escalate_rivalry(rival, revealer, man, world):
    """
    Rivalry confrontation: verbal → always; physical → probability-based.
    """
    rid = rival["id"]
    wid = revealer["id"]
    mid = man["id"]
    tick = world.get("tick", 0)

    r_traits  = set(rival.get("traits",    []) + rival.get("personality_traits", []))
    rev_traits = set(revealer.get("traits", []) + revealer.get("personality_traits", []))

    # Verbal confrontation — queue as a confrontation_desired event
    try:
        from core.event_bus import emit
        emit("confrontation_desired", {
            "initiator_id": rid,
            "target_id":    wid,
            "score":        50.0,
            "context":      "romantic_rivalry",
            "man_id":       mid,
        })
    except Exception:
        pass

    # Physical fight probability
    fight_chance = FIGHT_BASE_CHANCE
    if "aggressive" in r_traits or "hot_tempered" in r_traits:
        fight_chance += 0.20
    if "competitive" in r_traits:
        fight_chance += 0.10
    envy_sens = rival.get("attraction_profile", {}).get("envy_sensitivity", 0.5)
    fight_chance += envy_sens * 0.15
    fight_chance = min(0.75, fight_chance)

    if random.random() > fight_chance:
        return   # stays verbal

    # Physical fight — determine winner
    rival_str   = _fighting_strength(rival)
    revealer_str = _fighting_strength(revealer)
    total = rival_str + revealer_str or 1.0
    rival_wins = random.random() < (rival_str / total)

    winner = rival    if rival_wins else revealer
    loser  = revealer if rival_wins else rival

    # Loser: injury chance + humiliation grievance against winner
    _apply_fight_loss(loser, winner, world)

    # Winner: seduction confidence bump toward the man
    w_profile = winner.setdefault("attraction_profile", {})
    w_profile["initiation_bias"] = min(1.0, w_profile.get("initiation_bias", 0.0) + 0.15)
    w_profile["rejection_resilience"] = min(1.0,
        w_profile.get("rejection_resilience", 0.5) + 0.10)

    try:
        from core.event_bus import emit
        emit("fight_physical", {
            "parties":  [rid, wid],
            "winner":   winner["id"],
            "loser":    loser["id"],
            "context":  "romantic_rivalry",
            "man_id":   mid,
            "tick":     tick,
        })
    except Exception:
        pass


def _fighting_strength(c):
    """Rough fighting strength: build + athletic traits + randomness."""
    bf = c.get("body_features", {})
    BUILD_SCORES = {"slim": 0.30, "average": 0.50, "athletic": 0.80,
                    "stocky": 0.70, "heavy": 0.55}
    base = BUILD_SCORES.get(bf.get("build", "average"), 0.50)
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    if "athletic" in traits or "martial_arts" in c.get("hobbies", []):
        base += 0.20
    if "aggressive" in traits:
        base += 0.10
    return base + random.gauss(0, 0.15)


def _apply_fight_loss(loser, winner, world):
    """Apply consequences to the fight loser."""
    wid = winner["id"]

    # Humiliation grievance
    add_grievance(loser, wid, "fight_loss_humiliation", world,
                  severity=12.0,
                  details={"context": "romantic_rivalry_fight"})

    # Minor injury (random chance)
    if random.random() < 0.45:
        health = loser.setdefault("health", {})
        health["pain"] = min(1.0, health.get("pain", 0.0) + 0.25)
        conditions = health.setdefault("conditions", [])
        if "bruised" not in conditions:
            conditions.append("bruised")

    # Reputation hit — public brawl
    try:
        from systems.reputation import apply_reputation_event
        apply_reputation_event(loser, "public_brawl_loss", world, severity=0.06,
                               observer_id=wid)
    except Exception:
        pass


# ── Context helper ────────────────────────────────────────────────────────

def get_rival_context(c, world):
    """LLM context: active romantic rivalries this character is aware of."""
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {ch["id"]: ch for ch in chars}

    lines = []
    for oid, rel in c.get("relationships", {}).items():
        flags = rel.get("conflict_flags", [])
        if "romantic_rivalry" in flags:
            rival_name = chars.get(oid, {}).get("name", oid)
            rivalry    = rel.get("rivalry", 0)
            lines.append(
                f"romantic rival: {rival_name} (rivalry={rivalry}) "
                f"— both interested in the same person"
            )
    return {"rivalries": lines} if lines else {}
