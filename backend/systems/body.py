"""
body.py — unified physical body simulation

c["body"] is the single source of truth for all physical needs.
Long-term psychological drives (socialize, play, romance, …) live in c["lt_needs"].

Body fields (all 0-100):
  hunger            0=full,        100=starving
  hydration         100=hydrated,  0=dehydrated
  bladder           0=empty,       100=urgent
  bowels            0=empty,       100=urgent
  fatigue           0=rested,      100=exhausted
  sleep_debt        0=none,        100=severely deprived (accumulates across days)
  hygiene           100=clean,     0=filthy
  odor              0=fresh,       100=very smelly  (lags hygiene — non-linear)
  mouth_hygiene     100=fresh,     0=bad breath
  recent_intake     0=empty,       100=just ate/drank (decays ~3hrs, accelerates bladder)
  stomach_discomfort 0=fine,       100=painful
  pain              0=none,        100=severe
  sickness          0=healthy,     100=very ill
"""

import math

# ── health threshold events ───────────────────────────────────────────────────
_HEALTH_THRESHOLDS = {
    "hunger":     85,
    "fatigue":    88,
    "sleep_debt": 75,
    "sickness":   60,
    "pain":       70,
}

# ── defaults ──────────────────────────────────────────────────────────────────
_BODY_DEFAULTS = {
    "hunger":             20,
    "hydration":          80,
    "bladder":            10,
    "bowels":              5,
    "fatigue":            20,
    "sleep_debt":          0,
    "hygiene":            85,
    "odor":                5,
    "mouth_hygiene":      90,
    "recent_intake":      30,
    "stomach_discomfort":  0,
    "pain":                0,
    "sickness":            0,
}


def ensure_body(c):
    body = c.setdefault("body", {})
    for k, v in _BODY_DEFAULTS.items():
        body.setdefault(k, v)
    # Remove legacy c["needs"] entirely — long-term drives live in c["lt_needs"]
    c.pop("needs", None)


# ── helpers ───────────────────────────────────────────────────────────────────

def body_energy(c):
    """0-1 energy level derived from fatigue (for backward-compat reads)."""
    return max(0.0, 1.0 - c.get("body", {}).get("fatigue", 0) / 100)

def body_hunger_norm(c):
    """0-1 hunger urgency (1=starving)."""
    return c.get("body", {}).get("hunger", 0) / 100

def body_hygiene_norm(c):
    """0-1 cleanliness (1=clean)."""
    return c.get("body", {}).get("hygiene", 100) / 100


def drain_stamina(c, amount):
    """c["stamina"] (health.py, 0.0-1.0) previously only ever decreased,
    and only via injury-template stamina_penalty -- nothing drained it
    from exertion. This is the generic exertion-cost entry point (hostile
    actions this round; a future wrestle/overtake round reuses this same
    call for its repeated-hold drain)."""
    c["stamina"] = max(0.0, c.get("stamina", 1.0) - amount)


# ── main tick ─────────────────────────────────────────────────────────────────

def update_body_needs(c, dt=1.0):
    ensure_body(c)
    b  = c["body"]
    tr = c.get("traits", [])

    # ── HUNGER ───────────────────────────────────────────────────────────────
    rate = 0.03
    if "lazy" in tr or "apathetic" in tr:
        rate *= 0.85          # less active → burns less
    if "disciplined" in tr:
        rate *= 1.05
    b["hunger"] = min(100, b["hunger"] + rate * dt)

    # ── HYDRATION ────────────────────────────────────────────────────────────
    b["hydration"] = max(0, b["hydration"] - 0.04 * dt)

    # ── RECENT INTAKE  (decays over ~3 sim-hours; food/drink sets it) ────────
    b["recent_intake"] = max(0, b["recent_intake"] - 0.009 * dt)

    # ── BLADDER  (base fill + intake spike) ──────────────────────────────────
    intake_factor = 0.5 + (b["recent_intake"] / 100) * 1.5   # 0.5 → 2.0
    hydration_factor = max(0, b["hydration"] / 100)
    b["bladder"] = min(100, b["bladder"] + 0.05 * hydration_factor * intake_factor * dt)

    # ── BOWELS ───────────────────────────────────────────────────────────────
    b["bowels"] = min(100, b["bowels"] + 0.012 * dt)

    # ── FATIGUE ──────────────────────────────────────────────────────────────
    fatigue_rate = 0.02
    if "lazy" in tr or "apathetic" in tr:
        fatigue_rate *= 0.8
    if "disciplined" in tr or "determined" in tr:
        fatigue_rate *= 0.9
    b["fatigue"] = min(100, b["fatigue"] + fatigue_rate * dt)

    # ── SLEEP DEBT ───────────────────────────────────────────────────────────
    # Accumulates when exhausted and not sleeping; recovers slowly while awake
    # after catching up (handled in activity completion)
    if b["fatigue"] > 85:
        b["sleep_debt"] = min(100, b["sleep_debt"] + 0.005 * dt)
    elif b["fatigue"] < 40:
        b["sleep_debt"] = max(0, b["sleep_debt"] - 0.002 * dt)

    # ── HYGIENE ──────────────────────────────────────────────────────────────
    decay = 0.008
    if "lazy" in tr or "apathetic" in tr:
        decay *= 1.4
    if "vain" in tr:
        decay *= 0.7
    b["hygiene"] = max(0, b["hygiene"] - decay * dt)

    # ── ODOR  (non-linear lag: rises slowly at first, accelerates below 40) ──
    hygiene_gap = max(0, 70 - b["hygiene"])  # odor starts rising below hygiene=70
    odor_rate   = (hygiene_gap / 100) ** 1.5 * 0.03
    b["odor"]   = min(100, b["odor"] + odor_rate * dt)
    # Odor drops very slowly on its own (ventilation, time)
    if b["hygiene"] > 80:
        b["odor"] = max(0, b["odor"] - 0.005 * dt)

    # ── MOUTH HYGIENE ────────────────────────────────────────────────────────
    mouth_decay = 0.015
    # Eating makes breath worse temporarily
    if b["recent_intake"] > 50:
        mouth_decay *= 1.5
    b["mouth_hygiene"] = max(0, b["mouth_hygiene"] - mouth_decay * dt)

    # ── SIDE EFFECTS ─────────────────────────────────────────────────────────
    if b["hunger"] > 95:
        b["stomach_discomfort"] = min(100, b["stomach_discomfort"] + 0.5 * dt)
    else:
        b["stomach_discomfort"] = max(0, b["stomach_discomfort"] - 0.1 * dt)

    # ── STAMINA REGEN  (passive recovery -- the only other stamina path,
    # health.py's injury stamina_penalty, is one-directional drain) ──────────
    c["stamina"] = min(1.0, c.get("stamina", 1.0) + 0.01 * dt)

    # ── APPLY SLEEP DEBT EFFECTS ─────────────────────────────────────────────
    _apply_sleep_debt_effects(c)

    clamp_body(c)
    _check_health_thresholds(c)


def _apply_sleep_debt_effects(c):
    """Sleep debt raises stress and emotional temperature baseline."""
    debt = c.get("body", {}).get("sleep_debt", 0)
    if debt < 20:
        return
    # Raise stress proportional to debt
    stress_bump = (debt - 20) / 80 * 15   # max +15 stress from sleep debt
    c["stress"] = min(100, c.get("stress", 0) + stress_bump * 0.001)


# ── activity completions ──────────────────────────────────────────────────────

def on_sleep_complete(c, duration_minutes):
    """Called when a sleep activity finishes."""
    b = c["body"]
    # Full 8hr sleep clears fatigue. Proportional for naps.
    recovery = min(1.0, duration_minutes / 480)
    b["fatigue"]    = max(0, b["fatigue"]    - 90 * recovery)
    b["sleep_debt"] = max(0, b["sleep_debt"] - 60 * recovery)
    # Hygiene decreases slightly during sleep (night sweat)
    b["hygiene"] = max(0, b["hygiene"] - 3 * recovery)


def on_shower_complete(c):
    b = c["body"]
    b["hygiene"]   = 98
    b["odor"]      = 2
    # Partial mouth hygiene improvement (steam/rinsing)
    b["mouth_hygiene"] = min(100, b["mouth_hygiene"] + 15)


def on_bath_complete(c):
    b = c["body"]
    b["hygiene"]   = 95
    b["odor"]      = 3


def on_brush_teeth_complete(c):
    b = c["body"]
    b["mouth_hygiene"] = 98


def on_wash_hands_complete(c):
    b = c["body"]
    b["hygiene"] = min(100, b["hygiene"] + 8)


def on_eat_complete(c, nutrition=0.5):
    b = c["body"]
    restore = 40 + nutrition * 40
    b["hunger"]       = max(0, b["hunger"] - restore)
    b["recent_intake"] = min(100, b["recent_intake"] + 50)


def on_drink_complete(c, hydration_value=40):
    b = c["body"]
    b["hydration"]    = min(100, b["hydration"] + hydration_value)
    b["recent_intake"] = min(100, b["recent_intake"] + 30)


def on_toilet_complete(c):
    b = c["body"]
    b["bladder"] = 5
    b["bowels"]  = max(0, b["bowels"] - 60)


# ── odor perception ───────────────────────────────────────────────────────────

def get_odor_label(odor):
    """Human-readable odor description for context builder."""
    if odor < 15:
        return None
    if odor < 35:
        return "slightly stale"
    if odor < 60:
        return "noticeably unpleasant"
    if odor < 80:
        return "strongly unpleasant"
    return "overwhelming"


def get_breath_label(mouth_hygiene):
    if mouth_hygiene > 70:
        return None
    if mouth_hygiene > 45:
        return "stale breath"
    if mouth_hygiene > 20:
        return "bad breath"
    return "very bad breath"


# ── clamping ──────────────────────────────────────────────────────────────────

def clamp_body(c):
    for k, v in c["body"].items():
        c["body"][k] = max(0, min(100, v))


# ── health threshold events ───────────────────────────────────────────────────

def _check_health_thresholds(c):
    from core.event_bus import emit
    b     = c.get("body", {})
    fired = c.setdefault("_health_events_fired", [])
    for need, threshold in _HEALTH_THRESHOLDS.items():
        key = f"{need}_critical"
        val = b.get(need, 0)
        if val >= threshold and key not in fired:
            fired.append(key)
            emit("health_threshold_crossed",
                 {"character_id": c["id"], "need": need, "value": val})
        elif val < threshold * 0.7 and key in fired:
            fired.remove(key)
