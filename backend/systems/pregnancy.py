"""
systems/pregnancy.py
─────────────────────
Models conception, pregnancy, and the decision to keep/abort/adopt — with
particular focus on the family drama that erupts around teen pregnancy.

Architecture
────────────
• Conception is checked once per completed penetrative sexual act (act_stage ≥ 5).
  The chance is tiny per act and is scaled by the female's fertility score and
  contraception use.

• Pregnancy is an off-grid process: we don't animate medical visits, just update
  a `pregnancy` dict on the female character and fire drama events at key milestones.

• Decision window:
    - Discovered at ~4–8 weeks (random delay after conception)
    - Decision period: up to 12 weeks from discovery to choose keep/abort/adopt
    - LLM context is informed of the pregnancy and family pressure so the agent
      can roleplay the decision organically; we also run an autonomous fallback
      decision if none is made within the window.

• Drama cascade on discovery:
    - Parents of the female: shock, anger, shame, grief (weighted by values)
    - Parents of the male: denial, blame, possibly cut contact
    - Religious family: dramatically amplified → conflict trauma, social shame events
    - Between families: grievances, possible confrontation events

Key fields on character
───────────────────────
pregnancy : {
    status          : "none" | "pregnant" | "postpartum" | "aborted" | "adopted_out"
    father_id       : str | None
    conception_tick : int
    discovered_tick : int | None
    decision        : "undecided" | "keep" | "abort" | "adopt"
    decision_tick   : int | None
    weeks           : int          # advances each weekly tick
    drama_fired     : list[str]    # which drama events already emitted
}
"""

import random

# ── tunables ──────────────────────────────────────────────────────────────────
BASE_CONCEPTION_CHANCE      = 0.04    # per explicit act (no contraception)
TEEN_CONCEPTION_MULTIPLIER  = 1.30    # teens slightly higher (less reliable protection)
FERTILITY_WEIGHT            = 0.60    # how much fertility_appeal score affects chance
CONTRACEPTION_REDUCTION     = 0.85    # effectiveness when contraception is used

DISCOVERY_DELAY_MIN_WEEKS   = 4
DISCOVERY_DELAY_MAX_WEEKS   = 8

DECISION_DEADLINE_WEEKS     = 12     # weeks from discovery before autonomous decision
ABORTION_MAX_WEEKS          = 14     # after this the option is no longer available

# Trauma / drama severities
DRAMA_TRAUMA_TEEN_FEMALE    = 0.14   # base trauma to the pregnant teen
DRAMA_TRAUMA_PARENT         = 0.08
DRAMA_TRAUMA_FATHER         = 0.06

RELIGIOUS_DRAMA_MULTIPLIER  = 2.0    # multiplies drama for strictly religious families

TICKS_PER_WEEK              = 7 * 24 * 60   # assuming 1 tick = 1 game minute

# ── public API ────────────────────────────────────────────────────────────────

def init_pregnancy_state(c):
    c.setdefault("pregnancy", {
        "status":          "none",
        "father_id":       None,
        "conception_tick": 0,
        "discovered_tick": None,
        "decision":        "undecided",
        "decision_tick":   None,
        "weeks":           0,
        "drama_fired":     [],
    })


def maybe_conceive(female, male, world):
    """
    Call after a completed explicit act between a male and female character.
    Returns True if conception occurred.
    """
    if female.get("sex") not in ("female", "intersex"):
        return False
    if male.get("sex") not in ("male", "intersex"):
        return False

    f_age = female.get("age", 0)
    m_age = male.get("age", 0)
    if f_age < 14 or m_age < 14:
        return False   # hard floor — no pregnancy under 14
    if female.get("pregnancy", {}).get("status") == "pregnant":
        return False   # already pregnant

    # Chance calculation
    fertility = female.get("body_features", {}).get("fertility_appeal", 0.5)
    chance = BASE_CONCEPTION_CHANCE * (1.0 - FERTILITY_WEIGHT + FERTILITY_WEIGHT * fertility)

    if f_age < 20:
        chance *= TEEN_CONCEPTION_MULTIPLIER

    # Contraception reduces chance significantly
    if _has_contraception(female, male):
        chance *= (1.0 - CONTRACEPTION_REDUCTION)
    else:
        # No contraception: male intoxication & low impulse control → more likely to
        # lose themselves in the moment and not pull out in time
        m_intox  = male.get("intoxication_state", {})
        al       = m_intox.get("alcohol_level", 0.0)
        dl       = m_intox.get("drug_level",    0.0)
        m_imp    = male.get("impulse_state", {})
        sc       = m_imp.get("self_control", 0.5)
        m_libido = male.get("attraction_profile", {}).get("libido", 0.5)
        # pull-out failure probability: higher when drunk/high + low self-control + high libido
        pullout_fail = (al * 0.50 + dl * 0.35 + (1.0 - sc) * 0.30 + m_libido * 0.15) / 1.30
        pullout_fail = min(1.0, pullout_fail)
        chance *= (1.0 + pullout_fail * 1.50)   # up to 2.5× base chance at max fail

    if random.random() >= chance:
        return False

    # Conception!
    tick = world.get("tick", 0)
    init_pregnancy_state(female)
    female["pregnancy"].update({
        "status":          "pregnant",
        "father_id":       male.get("id"),
        "conception_tick": tick,
        "discovered_tick": None,  # filled in later by tick
        "decision":        "undecided",
        "drama_fired":     [],
        "weeks":           0,
    })
    return True


def tick_pregnancy(world):
    """
    Weekly tick — advance pregnancy weeks, fire discovery and drama events.
    """
    characters = world.get("characters", {})
    tick       = world.get("tick", 0)

    for c in characters.values():
        preg = c.get("pregnancy", {})
        if preg.get("status") != "pregnant":
            continue

        preg["weeks"] = preg.get("weeks", 0) + 1
        weeks = preg["weeks"]

        # Discovery window
        if preg.get("discovered_tick") is None:
            delay_weeks = random.randint(DISCOVERY_DELAY_MIN_WEEKS, DISCOVERY_DELAY_MAX_WEEKS)
            if weeks >= delay_weeks:
                _on_discovery(c, preg, world)

        # After discovery — decision pressure
        if preg.get("discovered_tick") is not None and preg["decision"] == "undecided":
            weeks_since_discovery = (tick - preg["discovered_tick"]) // TICKS_PER_WEEK
            if weeks >= ABORTION_MAX_WEEKS and preg["decision"] == "undecided":
                # Window closed: autonomous keep
                _resolve_decision(c, preg, "keep", world)
            elif weeks_since_discovery >= DECISION_DEADLINE_WEEKS:
                # Fallback autonomous decision
                decision = _autonomous_decision(c, preg, world)
                _resolve_decision(c, preg, decision, world)

        # Drama milestones
        _check_drama_milestones(c, preg, world)


def make_pregnancy_decision(female, decision, world):
    """
    Called by action_router when a character explicitly chooses keep/abort/adopt.
    decision: "keep" | "abort" | "adopt"
    """
    preg = female.get("pregnancy", {})
    if preg.get("status") != "pregnant" or preg.get("decision") != "undecided":
        return {"ok": False, "reason": "no_active_undecided_pregnancy"}
    if decision == "abort" and preg.get("weeks", 0) > ABORTION_MAX_WEEKS:
        return {"ok": False, "reason": "too_late_to_abort"}
    _resolve_decision(female, preg, decision, world)
    return {"ok": True, "decision": decision}


def get_pregnancy_context(c, world):
    """Context lines for LLM."""
    preg = c.get("pregnancy", {})
    status = preg.get("status", "none")
    if status == "none":
        return []

    lines = []
    if status == "pregnant":
        weeks = preg.get("weeks", 0)
        discovered = preg.get("discovered_tick") is not None
        decision = preg.get("decision", "undecided")
        father_id = preg.get("father_id")
        father = world.get("characters", {}).get(father_id) if father_id else None
        f_name = f"{father.get('first_name','')} {father.get('last_name','')}" if father else "unknown"

        if discovered:
            lines.append(
                f"Pregnant ({weeks} weeks), father: {f_name.strip() or 'unknown'}. "
                f"Decision status: {decision}."
            )
            if decision == "undecided":
                lines.append(
                    "Facing pressure to decide: keep the baby, abort, or give up for adoption. "
                    "Family drama is active."
                )
        else:
            lines.append(f"Pregnant ({weeks} weeks) — not yet discovered.")

    elif status == "postpartum":
        lines.append("Recently gave birth; postpartum period with associated emotional and physical challenges.")
    elif status == "aborted":
        lines.append("Recently had an abortion; may be processing grief, relief, or conflict about the decision.")
    elif status == "adopted_out":
        lines.append("Gave up a child for adoption; may carry grief or guilt about this decision.")

    return lines


# ── Internal helpers ──────────────────────────────────────────────────────────

def _has_contraception(female, male):
    """Check inventory or relationship flags for contraception use."""
    # Future: check item inventory for contraceptive items
    # For now: characters with 'responsible' or 'cautious' traits assumed to use it
    female_traits = set(female.get("traits", []) + female.get("personality_traits", []))
    male_traits   = set(male.get("traits",   []) + male.get("personality_traits",   []))
    caution_traits = {"responsible", "cautious", "careful", "low_libido"}
    return bool(female_traits & caution_traits or male_traits & caution_traits)


def _on_discovery(female, preg, world):
    """Fire the discovery moment: trauma + family drama starts."""
    tick = world.get("tick", 0)
    preg["discovered_tick"] = tick

    if "discovery" in preg.get("drama_fired", []):
        return
    preg.setdefault("drama_fired", []).append("discovery")

    f_age = female.get("age", 0)
    is_teen = f_age < 20

    # Trauma for the female
    base_sev = DRAMA_TRAUMA_TEEN_FEMALE if is_teen else DRAMA_TRAUMA_TEEN_FEMALE * 0.6
    _add_trauma(female, "unplanned_pregnancy_discovery", None, base_sev, world)

    # Notify family
    _fire_family_drama(female, preg, "discovery", world)

    # LLM event
    try:
        from core.events import emit
        emit("pregnancy_discovered", {
            "character_id": female.get("id"),
            "father_id":    preg.get("father_id"),
            "is_teen":      is_teen,
            "weeks":        preg.get("weeks", 0),
            "tick":         tick,
        }, world)
    except Exception:
        pass


def _resolve_decision(female, preg, decision, world):
    """Apply consequences of the final keep/abort/adopt decision."""
    tick = world.get("tick", 0)
    preg["decision"]      = decision
    preg["decision_tick"] = tick

    if decision == "abort":
        preg["status"] = "aborted"
        _add_trauma(female, "abortion_grief", None, 0.10, world)
        female["self_confidence"] = max(0.05, female.get("self_confidence", 0.60) - 0.05)
        _fire_family_drama(female, preg, "abortion_decision", world)

    elif decision == "adopt":
        preg["status"] = "adopted_out"
        _add_trauma(female, "adoption_grief", None, 0.12, world)
        _fire_family_drama(female, preg, "adoption_decision", world)

    elif decision == "keep":
        # remains "pregnant" until postpartum; handled by milestone
        _fire_family_drama(female, preg, "keep_decision", world)

    try:
        from core.events import emit
        emit("pregnancy_decision", {
            "character_id": female.get("id"),
            "father_id":    preg.get("father_id"),
            "decision":     decision,
            "tick":         tick,
        }, world)
    except Exception:
        pass


def _autonomous_decision(female, preg, world):
    """
    Fallback decision when no agent choice is made within the window.
    Weighted by age, values, family pressure.
    """
    f_age = female.get("age", 0)
    traits = set(female.get("traits", []) + female.get("personality_traits", []))

    # Base weights: keep / abort / adopt
    w_keep  = 0.50
    w_abort = 0.35
    w_adopt = 0.15

    # Younger → more likely abort (less ready) or adopt
    if f_age < 17:
        w_abort += 0.15
        w_keep  -= 0.15

    # Religious family → much less likely to abort
    fam_id = female.get("family_id")
    family = world.get("families", {}).get(fam_id) if fam_id else None
    if family:
        strictness = family.get("values", {}).get("religious_strictness", 0.0)
        if strictness >= 0.50:
            w_abort = max(0.02, w_abort - strictness * 0.30)
            w_keep  += strictness * 0.20
            w_adopt += strictness * 0.10

    # Maternal trait → keep
    if "maternal" in traits or "nurturing" in traits:
        w_keep += 0.15
        w_abort -= 0.10

    # Career-focused → more likely abort
    if "career_ambitious" in traits:
        w_abort += 0.10
        w_keep  -= 0.05

    total = w_keep + w_abort + w_adopt
    r = random.random() * total
    if r < w_keep:
        return "keep"
    elif r < w_keep + w_abort:
        return "abort"
    else:
        return "adopt"


def _check_drama_milestones(female, preg, world):
    """Fire inter-family drama at key pregnancy milestones."""
    weeks  = preg.get("weeks", 0)
    fired  = preg.get("drama_fired", [])

    # ~3 months: visibly showing → social reputation event
    if weeks == 12 and "showing" not in fired:
        fired.append("showing")
        preg["drama_fired"] = fired
        _fire_family_drama(female, preg, "showing", world)
        # Reputation hit
        try:
            from systems.reputation import apply_reputation_event
            apply_reputation_event(female, "teen_pregnancy_visible", world)
        except Exception:
            pass

    # Birth milestone
    if weeks >= 40 and preg.get("decision") == "keep" and "birth" not in fired:
        fired.append("birth")
        preg["drama_fired"] = fired
        preg["status"] = "postpartum"
        _fire_family_drama(female, preg, "birth", world)


def _fire_family_drama(female, preg, event_type, world):
    """
    Generate grievances, trauma, and conflict events rippling through both families.
    """
    f_id      = female.get("id")
    father_id = preg.get("father_id")
    characters = world.get("characters", {})
    families   = world.get("families", {})

    f_fam_id   = female.get("family_id")
    f_family   = families.get(f_fam_id) if f_fam_id else None
    f_values   = (f_family or {}).get("values", {})
    f_strict   = f_values.get("religious_strictness", 0.0)
    f_rel_mult = 1.0 + f_strict * (RELIGIOUS_DRAMA_MULTIPLIER - 1.0)

    father     = characters.get(father_id) if father_id else None
    m_fam_id   = father.get("family_id") if father else None
    m_family   = families.get(m_fam_id) if m_fam_id else None
    m_values   = (m_family or {}).get("values", {})
    m_strict   = m_values.get("religious_strictness", 0.0)
    m_rel_mult = 1.0 + m_strict * (RELIGIOUS_DRAMA_MULTIPLIER - 1.0)

    # ── Female's parents ──
    if f_family:
        for mid in f_family.get("members", []):
            if mid == f_id:
                continue
            rel_key = f"{f_id}:{mid}"
            rel     = f_family.get("relations", {}).get(rel_key, "")
            if rel in ("parent", "child"):   # parents of female
                parent = characters.get(mid)
                if parent:
                    sev = DRAMA_TRAUMA_PARENT * f_rel_mult
                    _add_trauma(parent, f"family_pregnancy_{event_type}", f_id, sev, world)
                    _add_grievance(parent, f_id, _grievance_type(event_type, "parent_of_female"), world)

    # ── Father's parents ──
    if father and m_family:
        for mid in m_family.get("members", []):
            if mid == father_id:
                continue
            rel_key = f"{father_id}:{mid}"
            rel     = m_family.get("relations", {}).get(rel_key, "")
            if rel in ("parent", "child"):
                parent = characters.get(mid)
                if parent:
                    sev = DRAMA_TRAUMA_PARENT * m_rel_mult * 0.7  # slightly less direct
                    _add_trauma(parent, f"family_pregnancy_{event_type}", f_id, sev, world)
                    _add_grievance(parent, f_id, _grievance_type(event_type, "parent_of_father"), world)

    # ── Father himself ──
    if father:
        sev = DRAMA_TRAUMA_FATHER * f_rel_mult
        _add_trauma(father, f"pregnancy_{event_type}", f_id, sev, world)

    # ── Inter-family grievance (families now have a grudge against each other) ──
    if f_family and m_family and event_type in ("discovery", "abortion_decision", "keep_decision"):
        _inter_family_grudge(f_id, father_id, f_family, m_family, event_type, world)

    # ── Emit event for LLM/social context ──
    try:
        from core.events import emit
        emit("pregnancy_family_drama", {
            "female_id":    f_id,
            "father_id":    father_id,
            "event_type":   event_type,
            "f_strictness": f_strict,
            "m_strictness": m_strict,
            "tick":         world.get("tick", 0),
        }, world)
    except Exception:
        pass


def _grievance_type(event_type, role):
    mapping = {
        "discovery":          "family_pregnancy_shock",
        "abortion_decision":  "family_abortion_conflict",
        "adoption_decision":  "family_adoption_grief",
        "keep_decision":      "family_pregnancy_obligation",
        "showing":            "family_social_shame",
        "birth":              "family_birth_event",
    }
    return mapping.get(event_type, "family_pregnancy_drama")


def _inter_family_grudge(f_id, m_id, f_family, m_family, event_type, world):
    """Add cross-family grievances — both families blame each other."""
    characters = world.get("characters", {})
    blame_sev = 12.0
    if event_type == "abortion_decision":
        blame_sev = 18.0  # particularly inflaming

    for src_fam, tgt_id, blame_dir in [
        (f_family, m_id, "father_family_blamed"),
        (m_family, f_id, "mother_family_blamed"),
    ]:
        # Pick a parent from the source family to hold the grievance
        for mid in src_fam.get("members", []):
            c = characters.get(mid)
            if not c:
                continue
            age = c.get("age", 0)
            if age >= 30:   # only adults
                _add_grievance(c, tgt_id, blame_dir, world, severity=blame_sev)
                break   # one representative per family


def _add_trauma(c, trauma_type, perp_id, severity, world):
    try:
        from systems.trauma import add_trauma_event
        add_trauma_event(c, trauma_type, perp_id, world, severity_override=severity)
    except Exception:
        pass


def _add_grievance(c, target_id, g_type, world, severity=None):
    try:
        from systems.grievances import add_grievance
        add_grievance(c, target_id, g_type, world, severity_override=severity)
    except Exception:
        pass
