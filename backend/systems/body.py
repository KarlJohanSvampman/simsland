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
import random

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
    "cold_exposure":       0,   # systems/weather.py
    "heat_exposure":       0,   # systems/weather.py
}

# Confirmed live bug: EVERY character got the exact same fixed bladder=10/
# bowels=5 starting point (via ensure_body()'s plain setdefault loop below)
# -- with a household generated all at once, every member's bladder then
# rises on nearly the same real-world formula, so they all cross the
# "need to go" threshold within moments of each other, forever, with only
# one toilet to share. Randomizing these two fields specifically (not the
# rest of _BODY_DEFAULTS -- no other need showed this symptom) at first
# creation staggers the household's bathroom schedule from the start.
_RANDOMIZED_ON_INSERT = {
    "bladder": (0, 70),
    "bowels":  (0, 60),
}

# Fields on c["body"] that are NOT 0-100 percentages, so clamp_body() must
# leave them alone (hours_awake/nutrients_today are unbounded accumulators;
# the private trackers are timestamps/day-numbers, not meters).
_NON_PERCENT_BODY_FIELDS = {
    "hours_awake", "nutrients_today", "toilet_visits_needed_today",
    "_wake_sim_time", "_nutrients_reset_day",
    "_sleep_hours_today", "sleep_hours_log", "_stimulant_until_tick",
}

# ── energy tuning ────────────────────────────────────────────────────────────
# Confirmed live bug: update_body_needs(c, dt=1.0, world=world) is called
# once per real TICK (1 tick == 1 real second, brain/agent_loop.py::
# update_agent -> update_internal_state, dispatched every tick for every
# non-off-grid character) -- but the awake-state fatigue_rate/
# BASE_ENERGY_DECAY constants below were flat, un-tick-scaled numbers
# (0.02 and 0.03) that only made sense if this function ran roughly once
# per sim-HOUR, not once per second. Verified directly (docker-exec,
# calling update_body_needs 3600 times to simulate 1 real hour): fatigue
# hit 92/100 and energy hit 0/100 within that single simulated hour --
# every character should have been pegged at max fatigue/zero energy
# within about an hour of waking, every single day. This was almost
# entirely masked by an unrelated problem (Ollama running slow/
# unreachable for much of this session, causing most per-tick agent
# decisions to be abandoned past AGENT_WAIT_BUDGET_SECONDS -- see
# sim_loop.py -- which meant update_body_needs's mutations often never
# actually persisted), not by any correct scaling in the formula itself.
#
# Per the user's explicit ask: awake, unmedicated, no sleep debt, a
# character should be comfortable through a normal day, start feeling it
# (see body_intentions.py's new hours_awake-driven nagging) from roughly
# 16-18h awake, and only hit FULLY fatigued + FULLY out of energy at
# 48h awake. Rescaled to a real 48-hour (172800-tick) linear baseline;
# the existing hunger_mult/wake_mult multipliers on energy (and the new
# sleep-debt multiplier below) still apply on TOP of this, so a hungry
# or already sleep-deprived character bottoms out sooner than 48h --
# which is the intended, realistic outcome.
AWAKE_FATIGUE_RATE_PER_TICK = 100 / 172800
BASE_ENERGY_DECAY = 100 / 172800   # before hunger_mult/wake_mult/debt_mult
ENERGY_PER_FULL_DAY_NUTRITION = 60  # a full day's nutrition (nutrition==1.0) restores this much energy

# A character's own carried sleep_debt (0-100, see the real weekly
# hours-slept measurement in _settle_daily_sleep_debt below) speeds up
# BOTH fatigue accrual and energy drain while awake -- "when you're
# behind on sleep you feel it faster during the day," not just "you need
# a longer catch-up sleep tonight" (see compute_needed_sleep_ticks for
# that half of it). 0 debt -> no change; 100 debt -> 60% faster.
SLEEP_DEBT_AWAKE_RATE_MULTIPLIER_MAX = 0.6

# A caffeinated item (item_templates' real "caffeine" flag -- coffee/
# tea/soda/energy drinks) suppresses fatigue accrual for a real,
# temporary window -- "activate themselves to stay awake" per the user's
# own framing, not just an instant flat energy top-up (which is all
# these items did before). Energy still drains close to normal (caffeine
# masks tiredness, it doesn't feed you) -- only a small extra easing.
# caffeine_strength on the item ("high", e.g. energy drinks) gets a
# longer window; anything else (coffee/tea/soda) gets the base one.
STIMULANT_FATIGUE_MULTIPLIER = 0.15
STIMULANT_ENERGY_DECAY_MULTIPLIER = 0.7
STIMULANT_DURATION_TICKS = {"base": 3 * 3600, "high": 5 * 3600}

# Real, measured daily sleep-debt recalibration (replaces the old crude
# fatigue>85/<40 drift below with an actual hours-slept-vs-optimal
# comparison) -- see _settle_daily_sleep_debt(). 7h/night is the
# documented optimal; each missing hour adds real, lasting debt.
OPTIMAL_SLEEP_HOURS_PER_NIGHT = 7.0
SLEEP_DEBT_PER_MISSING_HOUR = 8.0
SLEEP_DEBT_RECOVERY_PER_SURPLUS_HOUR = 4.0   # sleeping MORE than optimal pays debt down faster too

# Sleep now starts with a real, fatigue/energy/debt-aware duration
# (systems/activities.py::start_activity, action_router.py::_route_sleep)
# instead of a flat ~8h every time regardless of how much recovery is
# actually needed -- see compute_needed_sleep_ticks(). This is also the
# direct fix for a confirmed live bug: a character whose sleep was
# interrupted for a bathroom trip and then "resumed" via a fresh
# start_activity(c, world, "sleep") call got a brand-new flat ~8h sleep
# stacked on top of whatever they'd already slept, even with fatigue
# already mostly cleared -- landing them asleep again until mid/late
# afternoon. A floor keeps even an almost-fully-rested top-up sleep
# realistically short-but-real; a ceiling keeps a very sleep-deprived
# night from swallowing multiple real days in one sitting -- leftover
# debt simply carries into the following night(s) instead, the same
# real, self-correcting "distributed over the coming nights" catch-up
# the user asked about, with no separate 7-day repayment schedule
# needed -- the per-tick recovery-rate math already does it.
SLEEP_MIN_DURATION_TICKS = 90 * 60      # 1.5h floor
SLEEP_MAX_DURATION_TICKS = 11 * 3600    # 11h ceiling

# ── general body-need rate constants ─────────────────────────────────────────
# Confirmed live bug, same root cause and same fix shape as the fatigue/
# energy rescale above: hunger/hydration/bladder/bowels/hygiene/
# mouth_hygiene all carried flat, un-tick-scaled rate constants (0.03,
# 0.04, 0.05, 0.012, 0.008, 0.015) left over from before dt became
# "always exactly 1 real tick" -- confirmed LIVE (docker-exec against the
# actual running world, not just a synthetic test): both real characters
# in the live sim were sitting at hunger=100/hydration=0 -- maxed out --
# despite having eaten/drunk recently by their own schedules. Only
# recent_intake (0.009/tick, whose own comment already says "decays over
# ~3 sim-hours") was correctly scaled -- confirmed by the math
# (100/0.009 ticks ≈ 3.09h) -- and is used here as the calibration
# reference for the others: rate = 100 / (target_hours * 3600).
# Documented target timescales (real-world-ish approximations, easy to
# retune): hunger/hydration ~10h to run out from empty/full; bladder
# ~3.5h to fill at typical recent-intake/hydration levels; bowels ~16h;
# hygiene ~20h to need a shower; mouth_hygiene ~14h. Odor/
# stomach_discomfort/stamina are left untouched -- odor's own rate
# already derives from hygiene_gap (a nonlinear term bounded 0-1), so it
# slows down for free once hygiene does; stomach_discomfort only fires
# once hunger is already critical (now correctly much rarer), and
# stamina wasn't part of the reported symptom.
HUNGER_RATE_PER_TICK        = 100 / (10 * 3600)
HYDRATION_RATE_PER_TICK     = 100 / (10 * 3600)
BLADDER_BASE_RATE_PER_TICK  = 0.012
BOWELS_RATE_PER_TICK        = 100 / (16 * 3600)
HYGIENE_DECAY_PER_TICK      = 100 / (20 * 3600)
MOUTH_HYGIENE_DECAY_PER_TICK = 100 / (14 * 3600)

# ── sleep recovery tuning ─────────────────────────────────────────────────────
# Fixed a real bug: update_body_needs() ran unconditionally every tick
# regardless of activity, so fatigue kept RISING and energy kept DRAINING
# for the entire duration of a sleep activity -- only "fixed" in one lump
# sum at on_sleep_complete(), meaning a character got MORE tired while
# asleep until the exact instant they woke up, and an INTERRUPTED sleep
# (e.g. systems/director_mode.py's interrupt_attention, which clears
# c["activity"] directly without ever calling complete_activity()) got
# zero recovery credit at all, however long they'd actually been asleep.
# Rates calibrated so a full 8-hour (28800-tick) sleep clears roughly what
# on_sleep_complete() used to grant in one shot (fatigue -90, sleep_debt
# -60) -- energy recovering from sleep is new behavior (nothing restored
# it from sleep before at all, only eating/caffeine), matching the
# ordinary expectation that sleep is what energy is *for*.
SLEEP_FATIGUE_RECOVERY_PER_TICK    = 90 / 28800
SLEEP_ENERGY_RECOVERY_PER_TICK     = 100 / 28800
SLEEP_DEBT_RECOVERY_PER_TICK_ASLEEP = 60 / 28800
# Per the user's explicit ask: stress should genuinely wind down overnight
# too, not just fatigue/energy -- a real full 8-hour sleep takes a real
# but not total bite out of it (30 of 100), since stress is driven by a lot
# more than just tiredness and sleep alone shouldn't zero it out.
SLEEP_STRESS_RECOVERY_PER_TICK      = 30 / 28800


def ensure_body(c):
    body = c.setdefault("body", {})
    for k, v in _BODY_DEFAULTS.items():
        if k in _RANDOMIZED_ON_INSERT and k not in body:
            body[k] = random.uniform(*_RANDOMIZED_ON_INSERT[k])
        else:
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
    is_asleep = (c.get("activity") or {}).get("type") == "sleep"

    # ── HOURS AWAKE  (real-seconds based, not tick-rate dependent) ───────────
    if world is not None:
        wake_at = b.get("_wake_sim_time")
        if wake_at is not None:
            b["hours_awake"] = max(0.0, (world.get("sim_time", 0.0) - wake_at) / 3600.0)

    # ── HUNGER ───────────────────────────────────────────────────────────────
    rate = HUNGER_RATE_PER_TICK
    if "lazy" in tr or "apathetic" in tr:
        rate *= 0.85          # less active → burns less
    if "disciplined" in tr:
        rate *= 1.05
    b["hunger"] = min(100, b["hunger"] + rate * dt)

    # ── HYDRATION ────────────────────────────────────────────────────────────
    b["hydration"] = max(0, b["hydration"] - HYDRATION_RATE_PER_TICK * dt)

    # ── RECENT INTAKE  (decays over ~3 sim-hours; food/drink sets it) ────────
    b["recent_intake"] = max(0, b["recent_intake"] - 0.009 * dt)

    # ── BLADDER  (base fill + intake spike) ──────────────────────────────────
    intake_factor = 0.5 + (b["recent_intake"] / 100) * 1.5   # 0.5 → 2.0
    hydration_factor = max(0, b["hydration"] / 100)
    b["bladder"] = min(100, b["bladder"] + BLADDER_BASE_RATE_PER_TICK * hydration_factor * intake_factor * dt)

    # ── BOWELS  (scaled by yesterday's excess-nutrition toilet-visit load,
    # see systems/nutrition.py::settle_nutrition_day) ────────────────────────
    bowel_mult = max(1, b.get("toilet_visits_needed_today", 1))
    b["bowels"] = min(100, b["bowels"] + BOWELS_RATE_PER_TICK * bowel_mult * dt)

    # ── STRESS  (winds down while genuinely asleep -- see the user's
    # explicit ask; awake-state stress changes are driven by other
    # systems throughout the codebase and are untouched here) ──────────────
    if is_asleep:
        c["stress"] = max(0, c.get("stress", 0) - SLEEP_STRESS_RECOVERY_PER_TICK * dt)

    # Real per-tick tally of actual hours slept today -- accumulated
    # regardless of whether the sleep session completes naturally or gets
    # interrupted (a bathroom break, etc.), feeding the real daily
    # sleep-debt recalibration below rather than on_sleep_complete()'s own
    # lump-sum, which wouldn't see a short/interrupted segment correctly.
    if is_asleep:
        b["_sleep_hours_today"] = b.get("_sleep_hours_today", 0.0) + dt / 3600.0

    # Real, temporary stimulant window (coffee/tea/soda/energy drinks --
    # see on_consume_complete) -- suppresses fatigue accrual and eases
    # energy drain while active, a real "push through it" effect rather
    # than caffeine just being an instant flat energy top-up.
    stimulant_active = world is not None and world.get("tick", 0) < b.get("_stimulant_until_tick", 0)

    # Carried sleep debt makes awake hours feel harder -- both fatigue and
    # energy move faster while debt is elevated (see
    # SLEEP_DEBT_AWAKE_RATE_MULTIPLIER_MAX above).
    debt_mult = 1.0 + (b.get("sleep_debt", 0) / 100) * SLEEP_DEBT_AWAKE_RATE_MULTIPLIER_MAX

    # ── FATIGUE ──────────────────────────────────────────────────────────────
    if is_asleep:
        b["fatigue"] = max(0, b["fatigue"] - SLEEP_FATIGUE_RECOVERY_PER_TICK * dt)
    else:
        fatigue_rate = AWAKE_FATIGUE_RATE_PER_TICK
        if "lazy" in tr or "apathetic" in tr:
            fatigue_rate *= 0.8
        if "disciplined" in tr or "determined" in tr:
            fatigue_rate *= 0.9
        # Overweight (systems/body_composition.py's dynamic obese trait) tires
        # faster -- the "become lazier" consequence of weight gain.
        if "obese" in c.get("physical_traits", []):
            fatigue_rate *= 1.2
        fatigue_rate *= debt_mult
        if stimulant_active:
            fatigue_rate *= STIMULANT_FATIGUE_MULTIPLIER
        b["fatigue"] = min(100, b["fatigue"] + fatigue_rate * dt)

    # ── SLEEP DEBT ───────────────────────────────────────────────────────────
    # Recovers while actually asleep. The real, measured day-to-day debt
    # level itself is recalibrated once per real day against actual hours
    # slept vs. the 7h/night optimal (_settle_daily_sleep_debt, called
    # from the daily-settlement block below) -- this per-tick branch is
    # now just the "asleep -> pays down" half; awake no longer drifts it
    # off a crude fatigue-threshold proxy.
    if is_asleep:
        b["sleep_debt"] = max(0, b["sleep_debt"] - SLEEP_DEBT_RECOVERY_PER_TICK_ASLEEP * dt)

    # ── HYGIENE ──────────────────────────────────────────────────────────────
    decay = HYGIENE_DECAY_PER_TICK
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
    mouth_decay = MOUTH_HYGIENE_DECAY_PER_TICK
    # Eating makes breath worse temporarily
    if b["recent_intake"] > 50:
        mouth_decay *= 1.5
    b["mouth_hygiene"] = max(0, b["mouth_hygiene"] - mouth_decay * dt)

    # ── SIDE EFFECTS ─────────────────────────────────────────────────────────
    # Same flat-per-tick bug as the others above (0.5/0.1 previously meant
    # 100 -> full discomfort in ~3 min flat, and back down in ~17 min) --
    # rescaled to a real ~2h-to-max / ~1h-to-ease timescale.
    if b["hunger"] > 95:
        b["stomach_discomfort"] = min(100, b["stomach_discomfort"] + (100 / (2 * 3600)) * dt)
    else:
        b["stomach_discomfort"] = max(0, b["stomach_discomfort"] - (100 / (1 * 3600)) * dt)

    # ── STAMINA REGEN  (passive recovery -- the only other stamina path,
    # health.py's injury stamina_penalty, is one-directional drain) ──────────
    stamina_regen = 0.01
    if "obese" in c.get("physical_traits", []):
        stamina_regen *= 0.6
    c["stamina"] = min(1.0, c.get("stamina", 1.0) + stamina_regen * dt)

    # ── ENERGY  (drops faster with high hunger and the longer a character
    # has been awake; consumption/caffeine restore it while awake -- see
    # on_consume_complete -- and sleep restores it while asleep) ───────────
    if is_asleep:
        b["energy"] = min(100, b["energy"] + SLEEP_ENERGY_RECOVERY_PER_TICK * dt)
    else:
        hunger_mult = 1.0 + (b["hunger"] / 100) * 1.5   # 1.0 → 2.5
        hours_awake = b.get("hours_awake", 0)
        if hours_awake >= 15:
            wake_mult = 2.0
        elif hours_awake >= 12:
            wake_mult = 1.5
        else:
            wake_mult = 1.0
        energy_decay = BASE_ENERGY_DECAY * hunger_mult * wake_mult * debt_mult
        if stimulant_active:
            energy_decay *= STIMULANT_ENERGY_DECAY_MULTIPLIER
        b["energy"] = max(0, b["energy"] - energy_decay * dt)

    # ── APPLY SLEEP DEBT EFFECTS ─────────────────────────────────────────────
    _apply_sleep_debt_effects(c)

    # ── DAILY NUTRITION/WEIGHT/ADDICTION SETTLEMENT  (real calendar-midnight
    # detection, immune to CADENCE/tick-rate drift -- see systems/nutrition.py) ──
    #
    # Confirmed live bug: today_key was a plain (year, month, day) TUPLE,
    # but b["_nutrients_reset_day"] round-trips through Postgres/Redis as
    # JSON -- which has no tuple type, so it comes back as a LIST on the
    # very next load. [2026,8,27] != (2026,8,27) in Python even though
    # every element matches, so this "once per day" guard was actually
    # true on EVERY call after the first (update_internal_state runs
    # every tick for every character) -- crashing weight_kg to its floor
    # within minutes of a fresh reset instead of drifting over real days.
    # String-keyed, matching every other day-gate this session (jobs.py::
    # maybe_fire, body_composition.py, contagion.py, libido.py) to avoid
    # this exact class of bug recurring a third way.
    if world is not None:
        calendar = world.get("calendar", {})
        today_key = f"{calendar.get('year')}-{calendar.get('month')}-{calendar.get('day')}"
        if calendar.get("year") is not None:
            last_key = b.get("_nutrients_reset_day")
            if last_key is not None and last_key != today_key:
                from systems.nutrition import settle_nutrition_day
                settle_nutrition_day(c, world)
                _settle_daily_sleep_debt(c)
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


# Confirmed live bug (player report: a character stuck at stress=100 for
# hours, cycling through negative moods with no way out): every stress
# INCREASE in this codebase (sleep debt above, lt_needs frustration,
# waiting, expectations missed, weather exposure, claustrophobia, ...) is
# real, but nothing ever brought it back down passively -- the only
# decreases were tied to specific event completions (satisfying a leisure
# need, finishing sleep, ...), which a depressed/avoidant mood's own
# behavior_flags make the character LESS likely to go pursue in the first
# place. That combination is a genuine trap: maxed stress helps trigger a
# negative mood, the mood discourages the actions that would lower
# stress, and stress has no other way down -- so once it hits 100 it can
# stay there for however long the mood template's duration_ticks says,
# then likely trigger straight into another one. This is the real-world
# "stress fades with time, given no new stressors" baseline every other
# body meter effectively already has (hunger/fatigue/etc. all move both
# ways); stress was the one exception.
_STRESS_PASSIVE_DECAY_PER_TICK = 0.2   # at CADENCE["health"] cadence -- ~100->0 over ~4h with nothing re-adding it


def decay_stress(c, world=None):
    """Cadence-driven (CADENCE["health"], see sim_loop.py) passive stress
    recovery. Purely additive-safe: any system that's still actively
    generating real stress this same tick (sleep debt, an unmet need,
    weather exposure, ...) reapplies its own increase independently, so
    an ongoing real problem keeps winning out over this -- this only
    ever un-sticks stress that's stopped being actively re-caused."""
    stress = c.get("stress", 0)
    if stress <= 0:
        return
    c["stress"] = max(0, stress - _STRESS_PASSIVE_DECAY_PER_TICK)


def _settle_daily_sleep_debt(c):
    """Real, measured recalibration of sleep_debt against actual hours
    slept yesterday vs. OPTIMAL_SLEEP_HOURS_PER_NIGHT -- called once per
    real calendar day (update_body_needs' existing daily-settlement
    block, alongside settle_nutrition_day). Replaces the old crude
    fatigue>85/<40 awake-drift with a real accounting of hours actually
    slept; a real rolling week of them is kept (sleep_hours_log) for
    anything that wants to look at the pattern, not just the single
    derived debt number."""
    b = c["body"]
    slept = b.get("_sleep_hours_today", 0.0)
    deficit = OPTIMAL_SLEEP_HOURS_PER_NIGHT - slept
    if deficit > 0:
        b["sleep_debt"] = min(100, b.get("sleep_debt", 0) + deficit * SLEEP_DEBT_PER_MISSING_HOUR)
    else:
        b["sleep_debt"] = max(0, b.get("sleep_debt", 0) - (-deficit) * SLEEP_DEBT_RECOVERY_PER_SURPLUS_HOUR)
    log = b.setdefault("sleep_hours_log", [])
    log.append(round(slept, 2))
    del log[:-7]
    b["_sleep_hours_today"] = 0.0


def compute_needed_sleep_ticks(c):
    """Real, fatigue/energy/sleep_debt-aware sleep duration -- ticks
    needed to fully clear whichever of the three is furthest from its
    rested target, using the SAME per-tick recovery rates sleep already
    applies gradually while asleep. Used at the moment a sleep activity
    STARTS (systems/activities.py::start_activity, action_router.py::
    _route_sleep) instead of a flat ~8h every time -- a character who's
    mostly already rested (e.g. resuming after a bathroom break near the
    end of a night's sleep) gets a real, short top-up; a genuinely
    sleep-deprived character gets a real, longer night. A floor keeps
    even a near-fully-rested top-up realistically non-instant; a ceiling
    keeps one sitting from swallowing multiple real days -- leftover
    debt simply carries into the following night(s), the real,
    self-correcting version of "distribute the catch-up over the coming
    nights" with no separate repayment schedule needed."""
    b = c.get("body", {})
    fatigue_ticks = b.get("fatigue", 0) / SLEEP_FATIGUE_RECOVERY_PER_TICK
    energy_ticks = (100 - b.get("energy", 70)) / SLEEP_ENERGY_RECOVERY_PER_TICK
    debt_ticks = b.get("sleep_debt", 0) / SLEEP_DEBT_RECOVERY_PER_TICK_ASLEEP
    needed = max(fatigue_ticks, energy_ticks, debt_ticks)
    return int(max(SLEEP_MIN_DURATION_TICKS, min(SLEEP_MAX_DURATION_TICKS, needed)))


# ── activity completions ──────────────────────────────────────────────────────

def on_sleep_complete(c, duration_minutes, world=None):
    """Called when a sleep activity finishes naturally (the "using"->
    "finishing" transition in systems/activities.py). Fatigue/sleep_debt/
    energy recovery itself now happens gradually every tick while asleep
    (see update_body_needs()'s is_asleep branch) rather than as a lump sum
    here -- this used to be the ONLY place any of that recovery happened,
    which meant an interrupted sleep (cleared directly via e.g.
    systems/director_mode.py's interrupt_attention, never reaching this
    function) got zero recovery credit no matter how long the character
    had actually been asleep. Applying it again here would double-count
    it for a sleep that runs to natural completion, so this now only
    handles genuine wake-up bookkeeping."""
    b = c["body"]
    recovery = min(1.0, duration_minutes / 480)
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

    # ── caffeine: a real, temporary "push through it" window, not just
    # the flat energy_restore bump above -- see STIMULANT_* constants.
    # caffeine_strength == "high" (energy drinks) gets the longer window.
    if item_tmpl.get("caffeine") and world is not None:
        strength = "high" if item_tmpl.get("caffeine_strength") == "high" else "base"
        window = STIMULANT_DURATION_TICKS[strength]
        b["_stimulant_until_tick"] = max(
            b.get("_stimulant_until_tick", 0), world.get("tick", 0) + window
        )

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
    # Jittered, not a fixed value -- a hard reset to the same number for
    # everyone after every use quietly re-synchronizes the household's
    # bathroom schedule right back into lockstep over time, undoing the
    # randomized starting point above.
    b["bladder"] = random.uniform(2, 8)
    b["bowels"]  = max(0, b["bowels"] - random.uniform(50, 65))


def on_vomit_complete(c, world=None):
    """A real, physical consequence of finally being sick -- stomach
    emptied (hungrier afterward, 0=full/100=starving), hygiene takes a
    real hit, and some genuine relief (a bit less stressed, the
    "vomiting" hazard's current episode resets so the very next tick
    doesn't immediately demand another one)."""
    b = c["body"]
    b["hunger"] = min(100, b.get("hunger", 0) + 15)
    b["hygiene"] = max(0, b.get("hygiene", 100) - 20)
    b["mouth_hygiene"] = max(0, b.get("mouth_hygiene", 100) - 15)
    c["stress"] = max(0, c.get("stress", 0) - 5)

    state = c.get("condition_state", {})
    for cond_key, cond_state in state.items():
        if cond_state.get("current_symptom") == "vomiting":
            tick = world.get("tick", 0) if world else 0
            cond_state["last_manifestation_tick"] = tick


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
