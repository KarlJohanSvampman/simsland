"""
body.py — unified physical body simulation

c["body"] is the single source of truth for all physical needs.
Long-term psychological drives (socialize, play, romance, …) live in c["lt_needs"].

Body fields (all 0-100 unless noted):
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
  sickness          0=healthy,     100=very ill
  energy            0=depleted,    100=full (nutrition/gain overhaul round -- see
                    on_consume_complete; decays faster with high hunger and the
                    longer a character has been awake)
  hours_awake       float hours since the last on_sleep_complete(), driven off
                    world["sim_time"] (seconds) rather than raw ticks
  nutrients_today   running sum of consumed items' nutrition (0-1 fraction of a
                    day's recommended nutrition each), uncapped, reset at the
                    real calendar midnight (see systems/nutrition.py)
  toilet_visits_needed_today  int, set by the midnight settlement, scales the
                    bowels fill rate below (excess-nutrition days need more
                    bathroom trips)
"""

import math

# ── health threshold events ───────────────────────────────────────────────────
_HEALTH_THRESHOLDS = {
    "hunger":     85,
    "fatigue":    88,
    "sleep_debt": 75,
    "sickness":   60,
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
    "sickness":            0,
    "energy":             70,
    "hours_awake":         0,
    "nutrients_today":     0,
    "toilet_visits_needed_today": 1,
}

# Fields on c["body"] that are NOT 0-100 percentages, so clamp_body() must
# leave them alone (hours_awake/nutrients_today are unbounded accumulators;
# the private trackers are timestamps/day-numbers, not meters).
_NON_PERCENT_BODY_FIELDS = {
    "hours_awake", "nutrients_today", "toilet_visits_needed_today",
    "_wake_sim_time", "_nutrients_reset_day",
}

# ── energy tuning ────────────────────────────────────────────────────────────
BASE_ENERGY_DECAY        = 0.03   # per sim-hour equivalent (dt units), before multipliers
ENERGY_PER_FULL_DAY_NUTRITION = 60  # a full day's nutrition (nutrition==1.0) restores this much energy


def ensure_body(c):
    body = c.setdefault("body", {})
    for k, v in _BODY_DEFAULTS.items():
        body.setdefault(k, v)
    # Remove legacy c["needs"] entirely — long-term drives live in c["lt_needs"]
    c.pop("needs", None)


# ── helpers ───────────────────────────────────────────────────────────────────

def body_energy(c):
    """0-1 energy level (real c["body"]["energy"] meter)."""
    return max(0.0, c.get("body", {}).get("energy", 70) / 100)

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

def update_body_needs(c, dt=1.0, world=None):
    ensure_body(c)
    b  = c["body"]
    tr = c.get("traits", [])

    # ── HOURS AWAKE  (real-seconds based, not tick-rate dependent) ───────────
    if world is not None:
        wake_at = b.get("_wake_sim_time")
        if wake_at is not None:
            b["hours_awake"] = max(0.0, (world.get("sim_time", 0.0) - wake_at) / 3600.0)

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

    # ── BOWELS  (scaled by yesterday's excess-nutrition toilet-visit load,
    # see systems/nutrition.py::settle_nutrition_day) ────────────────────────
    bowel_mult = max(1, b.get("toilet_visits_needed_today", 1))
    b["bowels"] = min(100, b["bowels"] + 0.012 * bowel_mult * dt)

    # ── FATIGUE ──────────────────────────────────────────────────────────────
    fatigue_rate = 0.02
    if "lazy" in tr or "apathetic" in tr:
        fatigue_rate *= 0.8
    if "disciplined" in tr or "determined" in tr:
        fatigue_rate *= 0.9
    # Overweight (systems/body_composition.py's dynamic obese trait) tires
    # faster -- the "become lazier" consequence of weight gain.
    if "obese" in c.get("physical_traits", []):
        fatigue_rate *= 1.2
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
    stamina_regen = 0.01
    if "obese" in c.get("physical_traits", []):
        stamina_regen *= 0.6
    c["stamina"] = min(1.0, c.get("stamina", 1.0) + stamina_regen * dt)

    # ── ENERGY  (drops faster with high hunger and the longer a character
    # has been awake; consumption/caffeine restore it -- see
    # on_consume_complete) ────────────────────────────────────────────────
    hunger_mult = 1.0 + (b["hunger"] / 100) * 1.5   # 1.0 → 2.5
    hours_awake = b.get("hours_awake", 0)
    if hours_awake >= 15:
        wake_mult = 2.0
    elif hours_awake >= 12:
        wake_mult = 1.5
    else:
        wake_mult = 1.0
    b["energy"] = max(0, b["energy"] - BASE_ENERGY_DECAY * hunger_mult * wake_mult * dt)

    # ── APPLY SLEEP DEBT EFFECTS ─────────────────────────────────────────────
    _apply_sleep_debt_effects(c)

    # ── DAILY NUTRITION/WEIGHT/ADDICTION SETTLEMENT  (real calendar-midnight
    # detection, immune to CADENCE/tick-rate drift -- see systems/nutrition.py) ──
    if world is not None:
        calendar = world.get("calendar", {})
        today_key = (calendar.get("year"), calendar.get("month"), calendar.get("day"))
        if today_key[0] is not None:
            last_key = b.get("_nutrients_reset_day")
            if last_key is not None and last_key != today_key:
                from systems.nutrition import settle_nutrition_day
                settle_nutrition_day(c, world)
            b["_nutrients_reset_day"] = today_key

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

def on_sleep_complete(c, duration_minutes, world=None):
    """Called when a sleep activity finishes."""
    b = c["body"]
    # Full 8hr sleep clears fatigue. Proportional for naps.
    recovery = min(1.0, duration_minutes / 480)
    b["fatigue"]    = max(0, b["fatigue"]    - 90 * recovery)
    b["sleep_debt"] = max(0, b["sleep_debt"] - 60 * recovery)
    # Hygiene decreases slightly during sleep (night sweat)
    b["hygiene"] = max(0, b["hygiene"] - 3 * recovery)
    # Waking moment: reset the hours-awake clock (see update_body_needs).
    b["hours_awake"] = 0.0
    if world is not None:
        b["_wake_sim_time"] = world.get("sim_time", 0.0)


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

    from systems.body_composition import record_calories_in
    record_calories_in(c, nutrition)


def on_drink_complete(c, hydration_value=40, volume=0):
    b = c["body"]
    b["hydration"]    = min(100, b["hydration"] + hydration_value)
    b["recent_intake"] = min(100, b["recent_intake"] + 30)
    if volume:
        b["bladder"] = min(100, b["bladder"] + volume)


def on_consume_complete(c, world, item_tmpl):
    """Unified item-driven consumption hook -- called by activities.py for
    every eat/drink branch once the real item template has been resolved.
    Fans out to on_eat_complete/on_drink_complete (kept for back-compat with
    any other caller) plus the new energy/nutrition-tracking/addiction/
    caffeine/alcohol/volume effects, all driven by the item's own fields."""
    ensure_body(c)
    b = c["body"]
    category   = item_tmpl.get("category")
    nutrition  = item_tmpl.get("nutrition", 0.0) or 0.0
    hydration_restore = item_tmpl.get("hydration_restore")
    energy_restore     = item_tmpl.get("energy_restore", 0) or 0
    volume             = item_tmpl.get("volume", 0) or 0
    alcohol_units       = item_tmpl.get("alcohol_units", 0) or 0
    addiction_type      = item_tmpl.get("addiction_type")

    # Only food/drink items move hunger/hydration -- medicine (painkillers)
    # and drug items (cigarettes, cocaine, ...) have neither field and are
    # handled purely through their addiction_type/drug_id hooks below.
    if category == "drink" or hydration_restore is not None or volume:
        on_drink_complete(c, hydration_value=hydration_restore or 0, volume=volume)
    elif category == "food" or nutrition:
        on_eat_complete(c, nutrition=nutrition)
        # A real plate/bowl/cutlery used for a meal -- see systems/
        # chores.py, which tracks this as a simple household-wide count
        # rather than real per-instance dishware (see that module's
        # docstring for the scoping rationale).
        if category == "food":
            household = world.get("households", {}).get(c.get("household_id"))
            if household:
                from systems.chores import add_dirty_dishes
                add_dirty_dishes(household)

    # ── nutrition-day tally (fraction of a daily requirement) ───────────────
    b["nutrients_today"] = b.get("nutrients_today", 0) + nutrition

    # ── energy gain: nutrition-driven, halved for the first 2h after waking,
    # plus an immediate flat bump from caffeine/energy-drink items ─────────
    if nutrition:
        gain = nutrition * ENERGY_PER_FULL_DAY_NUTRITION
        if b.get("hours_awake", 0) < 2:
            gain *= 0.5
        b["energy"] = min(100, b["energy"] + gain)
    if energy_restore:
        b["energy"] = min(100, b["energy"] + energy_restore)

    # ── alcohol/drugs → harassment.py's existing intoxication_state ─────────
    if alcohol_units:
        from systems.harassment import consume_alcohol
        consume_alcohol(c, alcohol_units, world)
    drug_id = item_tmpl.get("drug_id")
    if drug_id:
        from systems.harassment import consume_drug
        consume_drug(c, drug_id, world)

    # ── addiction usage tracking ─────────────────────────────────────────────
    if addiction_type:
        from systems.addictions import record_usage
        record_usage(c, addiction_type, world)


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
        if k in _NON_PERCENT_BODY_FIELDS or v is None:
            continue
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
