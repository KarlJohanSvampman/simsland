"""
systems/impulse.py

Impulse control system.

Each character has an impulse_state:
  anger_pressure (0-1):  accumulates from grievances, frustration, humiliation,
                         relationship resentment, romantic rivalry.
  self_control   (0-1):  derived from traits; stable but can degrade under stress.
  last_outburst_tick:    cooldown guard.

Traits:
  high_self_control  → self_control +0.40, threshold ×1.60
  low_self_control   → self_control -0.35, threshold ×0.55
  hot_tempered       → anger gain ×1.50, but decays faster

Pressure sources (called by other systems):
  add_anger_pressure(c, amount, source, world)

Tick:
  tick_impulse(world) — called every sim tick (fast — no loops over all chars,
  only chars with pressure > 0.1).  Decays pressure, checks boilover.

Boilover:
  When anger_pressure > OUTBURST_THRESHOLD (adjusted by self_control):
    → _trigger_outburst(c, world)
    Selects the highest-grievance target and emits one of:
      - "threat"          (verbal threat — low escalation)
      - "shove"           (physical — mild, public humiliation)
      - "assault"         (attack — serious, legal + reputation consequences)
    Severity escalates with pressure overage and aggression traits.
    Outburst resets anger_pressure partially (doesn't fully clear — resentment lingers).
"""

import random

# ── Constants ─────────────────────────────────────────────────────────────
OUTBURST_THRESHOLD    = 0.75    # base boilover point
ANGER_DECAY_PER_TICK  = 0.00008 # slow natural decay
ANGER_DECAY_FAST      = 0.00020 # hot_tempered — spikes fast, cools faster
OUTBURST_COOLDOWN     = 60 * 60 * 6   # 6 game hours between outbursts (ticks)
SELF_CONTROL_BASE     = 0.50


# ── Public API ────────────────────────────────────────────────────────────

def init_impulse_state(c):
    """Derive self_control from traits and initialise impulse_state."""
    traits = set(c.get("traits", []) + c.get("personality_traits", []))

    sc = SELF_CONTROL_BASE
    if "high_self_control" in traits:
        sc += 0.40
    if "low_self_control" in traits:
        sc -= 0.35
    if "hot_tempered" in traits:
        sc -= 0.25
    if "patient" in traits or "calm" in traits:
        sc += 0.15
    if "aggressive" in traits:
        sc -= 0.20
    sc = round(max(0.05, min(0.95, sc)), 3)

    # Sexism level — only meaningful for male actors
    sex = c.get("sex", "male")
    sl = 0.0
    if sex == "male":
        sl = 0.15   # population baseline (low but non-zero)
        if "sexist" in traits:
            sl += 0.40
        if "egalitarian" in traits:
            sl = max(0.0, sl - 0.30)
        if "compassionate" in traits or "empathetic" in traits:
            sl = max(0.0, sl - 0.15)
        sl = round(min(1.0, sl), 3)

    imp = c.setdefault("impulse_state", {
        "anger_pressure":     0.0,
        "self_control":       sc,
        "sexism_level":       sl,
        "last_outburst_tick": 0,
    })
    imp["self_control"] = sc
    imp["sexism_level"]  = sl
    return imp


def add_anger_pressure(c, amount, source, world):
    """
    Increase anger pressure on character c.
    amount: 0-1 raw addition (will be scaled by trait modifiers).
    source: string label for the cause (used in event/context).
    """
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    imp = c.setdefault("impulse_state", {
        "anger_pressure": 0.0, "self_control": SELF_CONTROL_BASE,
        "last_outburst_tick": 0,
    })

    # Trait scaling
    gain = amount
    if "hot_tempered" in traits:
        gain *= 1.50
    if "aggressive" in traits:
        gain *= 1.25
    if "high_self_control" in traits:
        gain *= 0.60
    if "patient" in traits or "calm" in traits:
        gain *= 0.70
    if "sensitive" in traits:
        gain *= 1.20

    imp["anger_pressure"] = round(min(1.0, imp.get("anger_pressure", 0.0) + gain), 4)


def tick_impulse(world):
    """
    Fast tick — decay anger pressure and check for boilover.
    Only processes chars with non-trivial pressure.
    """
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    tick = world.get("tick", 0)

    for c in chars.values():
        if c.get("is_offscreen"):
            continue
        imp = c.get("impulse_state")
        if not imp or imp.get("anger_pressure", 0) < 0.05:
            continue

        traits = set(c.get("traits", []) + c.get("personality_traits", []))
        decay = ANGER_DECAY_FAST if "hot_tempered" in traits else ANGER_DECAY_PER_TICK
        imp["anger_pressure"] = round(max(0.0, imp["anger_pressure"] - decay), 5)

        # Boilover check
        sc = imp.get("self_control", SELF_CONTROL_BASE)
        threshold = OUTBURST_THRESHOLD * (0.5 + sc)   # range ~0.53 (low SC) to ~0.95 (high SC)

        if imp["anger_pressure"] < threshold:
            continue
        cooldown_ok = (tick - imp.get("last_outburst_tick", 0)) >= OUTBURST_COOLDOWN
        if not cooldown_ok:
            continue

        _trigger_outburst(c, imp, threshold, world)


# ── Internal ──────────────────────────────────────────────────────────────

def _trigger_outburst(c, imp, threshold, world):
    """Select target and act type; emit outburst event."""
    cid   = c["id"]
    tick  = world.get("tick", 0)
    traits = set(c.get("traits", []) + c.get("personality_traits", []))

    # Pick highest-grievance target who is present in the world
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {ch["id"]: ch for ch in chars}

    # Domestic abuser: preferentially target intimate partner
    try:
        from systems.domestic_control import get_domestic_target
        override = get_domestic_target(c, chars)
        if override and override in chars:
            target = chars[override]
            _apply_outburst_consequences(c, target, "assault", world)
            imp["anger_pressure"] = round(imp["anger_pressure"] * 0.45, 4)
            imp["last_outburst_tick"] = tick
            try:
                from core.event_bus import emit
                emit("impulsive_outburst", {"actor_id": cid, "target_id": override,
                     "act_type": "domestic_assault", "pressure": imp["anger_pressure"], "tick": tick})
            except Exception:
                pass
            return
    except Exception:
        pass

    from systems.grievances import get_grievance_score
    best_target_id = None
    best_score     = 0.0
    for oid, rel in c.get("relationships", {}).items():
        if oid not in chars:
            continue
        score = get_grievance_score(c, oid)
        # Weight by resentment too
        score += rel.get("resentment", 0) * 0.3
        if score > best_score:
            best_score     = score
            best_target_id = oid

    if not best_target_id:
        # No clear target — spill into environment (property damage / general aggression)
        imp["anger_pressure"] *= 0.5
        imp["last_outburst_tick"] = tick
        try:
            from core.event_bus import emit
            emit("impulsive_outburst", {
                "actor_id":  cid,
                "target_id": None,
                "act_type":  "general_aggression",
                "pressure":  imp["anger_pressure"],
                "tick":      tick,
            })
        except Exception:
            pass
        return

    target = chars[best_target_id]
    pressure_over  = imp["anger_pressure"] - threshold
    aggression_mod = 0.20 if "aggressive" in traits else 0.0

    # Determine act severity
    # Sexism modifier — male actor targeting female raises aggression
    sexism_mod = 0.0
    if c.get("sex") == "male" and target.get("sex") in ("female", "intersex"):
        sl = imp.get("sexism_level", 0.0)
        sexism_mod = sl * 0.30   # up to +0.30 on severity roll

    severity_roll = pressure_over + aggression_mod + sexism_mod + random.gauss(0, 0.05)
    if severity_roll < 0.15:
        act_type = "threat"          # verbal
    elif severity_roll < 0.40:
        act_type = "shove"           # physical minor
    else:
        act_type = "assault"         # serious

    # Apply consequences
    _apply_outburst_consequences(c, target, act_type, world)

    # Partial reset — anger lingers but not at peak
    imp["anger_pressure"] = round(imp["anger_pressure"] * 0.45, 4)
    imp["last_outburst_tick"] = tick

    try:
        from core.event_bus import emit
        emit("impulsive_outburst", {
            "actor_id":   cid,
            "target_id":  best_target_id,
            "act_type":   act_type,
            "pressure":   imp["anger_pressure"],
            "tick":       tick,
        })
    except Exception:
        pass


def _apply_outburst_consequences(actor, target, act_type, world):
    """Apply relationship, reputation, and legal consequences."""
    from systems.grievances  import add_grievance
    from systems.reputation  import apply_reputation_event

    aid = actor["id"]
    tid = target["id"]

    # Target gets a grievance against actor
    sev_map = {"threat": 12.0, "shove": 16.0, "assault": 22.0}
    add_grievance(target, aid, act_type if act_type != "shove" else "threatened",
                  world, severity=sev_map[act_type])

    # Actor reputation hit (public acts visible to bystanders)
    rep_hit = {"threat": 0.05, "shove": 0.08, "assault": 0.15}
    apply_reputation_event(actor, act_type, world,
                           severity=rep_hit[act_type], observer_id=tid)

    # Physical acts: target may be injured
    if act_type in ("shove", "assault"):
        health = target.setdefault("health", {})
        if act_type == "assault":
            health["pain"] = min(1.0, health.get("pain", 0.0) + 0.30)
            health.setdefault("conditions", [])
            if "bruised" not in health["conditions"]:
                health["conditions"].append("bruised")
        # Shove: minor chance of pain
        elif random.random() < 0.30:
            health["pain"] = min(1.0, health.get("pain", 0.0) + 0.10)

    # Assault: legal record
    if act_type == "assault":
        try:
            legal = actor.setdefault("legal", {})
            legal.setdefault("record", []).append({
                "offense": "assault",
                "tick":    world.get("tick", 0),
                "victim":  tid,
            })
            # Emit for law system pickup
            from core.event_bus import emit
            emit("fight_physical", {
                "parties": [aid, tid],
                "winner":  None,
                "loser":   tid,
                "context": "impulsive_assault",
                "tick":    world.get("tick", 0),
            })
        except Exception:
            pass


# ── Pressure feed from grievances ────────────────────────────────────────

def sync_anger_from_grievances(c, world):
    """
    Called periodically: translate grievance score into anger pressure.
    High total grievance → higher anger pressure floor.
    """
    from systems.grievances import get_grievance_score

    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {ch["id"]: ch for ch in chars}

    max_score = 0.0
    for oid in c.get("relationships", {}):
        if oid in chars:
            sc = get_grievance_score(c, oid)
            if sc > max_score:
                max_score = sc

    # CONFRONT_THRESHOLD (30) → maps to ~0.60 anger pressure
    pressure_from_grievances = min(0.80, max_score / 50.0)

    imp = c.setdefault("impulse_state", {
        "anger_pressure": 0.0, "self_control": SELF_CONTROL_BASE,
        "last_outburst_tick": 0,
    })
    # Nudge anger pressure toward the grievance floor (don't snap — drift)
    current = imp.get("anger_pressure", 0.0)
    if pressure_from_grievances > current:
        imp["anger_pressure"] = round(
            current + (pressure_from_grievances - current) * 0.05, 4
        )


# ── Context helper ────────────────────────────────────────────────────────

def get_impulse_context(c, world):
    imp = c.get("impulse_state", {})
    pressure = imp.get("anger_pressure", 0.0)
    if pressure < 0.30:
        return {}
    sc = imp.get("self_control", 0.5)
    threshold = OUTBURST_THRESHOLD * (0.5 + sc)
    lines = []
    if pressure >= threshold * 0.85:
        lines.append(f"NEAR BOILOVER — anger_pressure={pressure:.2f}, threshold={threshold:.2f}")
    elif pressure >= 0.50:
        lines.append(f"elevated anger (pressure={pressure:.2f})")
    else:
        lines.append(f"simmering frustration (pressure={pressure:.2f})")
    return {"impulse": lines}
