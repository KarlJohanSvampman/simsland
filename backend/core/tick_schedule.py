# =========================================================
# TICK SCHEDULER
#
# Centralises "run every N ticks" logic so sim_loop stays
# readable and systems don't each hardcode their own modulo.
#
# Usage:
#   if every(world, 10):          # true once every 10 ticks
#       run_slow_system(world)
#
#   if every(world, 60, offset=3):  # stagger so not everything
#       run_another(world)           # fires on the same tick
#
# SCHEDULES dict maps system names to their cadence so the
# numbers live in one place rather than scattered through
# sim_loop.
# =========================================================

import os

# Real seconds between world ticks at 1x time_scale -- single source of
# truth shared by main.py's loop() (which divides this by the live
# time_scale to decide how long to sleep) and sim_loop.py's
# advance_calendar() (which adds this flat amount of simulated time per
# tick; the speedup itself comes from ticks firing more often, not from
# multiplying this value -- see systems/schema_defaults.py's time_scale
# default and api/admin.py).
TICK_RATE_SECONDS = float(os.getenv("TICK_RATE_SECONDS", "1.0"))


def every(world: dict, n: int, offset: int = 0) -> bool:
    """True once every `n` ticks, offset by `offset` to spread load."""
    return (world["tick"] + offset) % n == 0


# ── How often each category of system runs ───────────────
# EVERY_TICK  = 1   (not listed — always run)
# FAST        = 5   (perception, attention)
# MEDIUM      = 15  (memory decay, emotion, market, cooking)
# SLOW        = 60  (news, traffic, health events)
# VERY_SLOW   = 300 (elections, faction influence, hierarchy)
# WEEKLY      = only on the Monday-midnight tick

CADENCE = {
    # character-level
    "perception":            5,
    "attention":             5,
    "memory_decay":         15,
    "polarization":         15,
    "relationships":        15,   # replaces every-tick O(N²) loop
    "health":               30,
    "item_knowledge":       10,

    # world-level
    "market":               20,
    "cooking":              10,
    "traffic":              30,
    "deliveries":           10,
    "postal":               30,
    "service_workers":      10,
    "appliance_degradation":60,
    "household_monitoring": 20,
    "job_market":           60,
    "conversation_cleanup": 60,

    # rare / event-driven (default cadence; events bypass this)
    "news":                 60,
    "crisis":               60,
    "election":            300,
    "faction":             300,
    "hierarchy":           300,
    "migration":           300,
    "evictions":           120,
    "arrests":              30,
    "trials":               60,
    "fires":                10,

    # Conflict / social drama
    "grievances":           15,
    "conflicts":             5,
    "grapples":              5,
    "contract_checks":      60,

    # Body / needs
    "lt_needs":             30,   # long-term need frustration update (~30 game-min)
    "social_odor":          20,   # smell pressure scan
    "contagion":            15,   # proximity disease-spread sweep, per building group
    "child_care":           15,   # child needs oversight + baseline accountability contract
    "bedroom_assignment":   60,   # age-based bedroom ownership -- changes rarely

    # Individual wait activities (microwave, phone hold, etc.) — see
    # systems/activities.py's start_microwave/take_out_of_microwave and
    # sim_loop.py's character-wait block. Doesn't need every-tick
    # precision, just needs to catch up reasonably soon after
    # ready_at_tick passes.
    "character_wait":        5,
}

# Phone battery drain — every tick but gated by cadence to spread load
CADENCE["phone_battery"]    = 1    # every tick

# Social / calendar events (fire frequently; internally guard to once per real day/hour)
CADENCE["social_events"]    = 60
CADENCE["maybe_deadlines"]  = 30
CADENCE["calendar_events"]  = 60

# Socioeconomics — once per simulated day (~24 ticks)
CADENCE["socioeconomics"]   = 24