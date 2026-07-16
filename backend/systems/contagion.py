"""
contagion.py — Disease transmission, hygiene and food safety system
====================================================================

Transmission modes
  airborne   — 3 radius rings (close/medium/far), particles linger N ticks
  contact    — physical touch / shared surfaces
  sexual     — intimate contact only
  fecal_oral — contaminated food/water/unwashed hands

Hygiene model
  After every toilet visit characters *should* wash hands. Compliance rates:
    - after defecation:  ~90% (miss 10%)
    - after urination:   ~60% (miss 40%)
    - after flush miss:  slightly higher germ load
  Surfaces (toilet handle, door handle) retain germs for a window of ticks.

Food safety
  Each food item/prop tracks freshness. Badly prepped or aged food carries
  bacterial load that is evaluated at consumption.

Contagious runtime state on character
  char["contagion_state"] = {
    "is_contagious": bool,
    "transmission_mode": ["airborne", "contact", ...],
    "contagious_radius_tiles": 3.0,         # shrinks as disease resolves
    "airborne_linger_ticks": 12,
    "particle_cloud": {tile_key: expire_tick},  # tiles with lingering particles
    "contagious_since_tick": int,
    "contagious_until_tick": int             # estimated, based on condition duration
  }
"""

import random
import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Radius rings in tiles (e.g. 1 tile ≈ 1 metre)
RADIUS_CLOSE  = 1.0    # 0–1 tile   → highest infection risk
RADIUS_MEDIUM = 2.5    # 1–2.5 tile → medium risk
RADIUS_FAR    = 5.0    # 2.5–5 tile → low risk (airborne only)

# Per-interval (per-tick) infection probability at each ring for airborne
AIRBORNE_RISK = {
    "close":  0.08,
    "medium": 0.03,
    "far":    0.01,
}
# Multiplier applied for contact/sexual modes (contact range only)
CONTACT_RISK_MULTIPLIER  = 2.5
SEXUAL_RISK_MULTIPLIER   = 5.0

# Ticks particles linger after infected person leaves a tile (airborne)
AIRBORNE_LINGER_TICKS = 12   # ~30 min at 1 tick = ~2.5 min

# Hand-wash compliance after toilet
HANDWASH_AFTER_DEFECATION_CHANCE = 0.90
HANDWASH_AFTER_URINATION_CHANCE  = 0.60
SURFACE_GERM_LINGER_TICKS        = 30   # ticks until touch-surface is safe

# Food safety
FOOD_BACTERIAL_THRESHOLD = 0.60   # 0-1; above this: risk of gut infection

# Which conditions are transmissible and how
TRANSMISSIBLE_CONDITIONS = {
    "common_cold":             {"modes": ["airborne", "contact"],
                                "linger_ticks": 12, "base_contagious_days": 5},
    "influenza":               {"modes": ["airborne", "contact"],
                                "linger_ticks": 18, "base_contagious_days": 6},
    "coronavirus":             {"modes": ["airborne", "contact"],
                                "linger_ticks": 24, "base_contagious_days": 10},
    "aggressive_gut_bacteria": {"modes": ["fecal_oral", "contact"],
                                "linger_ticks": 0,  "base_contagious_days": 7},
    "std_chlamydia":           {"modes": ["sexual"],
                                "linger_ticks": 0,  "base_contagious_days": 999},
    "std_gonorrhea":           {"modes": ["sexual"],
                                "linger_ticks": 0,  "base_contagious_days": 999},
    "std_herpes":              {"modes": ["sexual", "contact"],
                                "linger_ticks": 0,  "base_contagious_days": 999},
    "std_hiv":                 {"modes": ["sexual", "contact"],   # blood contact
                                "linger_ticks": 0,  "base_contagious_days": 999},
    "std_syphilis":            {"modes": ["sexual", "contact"],
                                "linger_ticks": 0,  "base_contagious_days": 999},
    "borrelia":                {"modes": [],   # tick-borne only, not person-to-person
                                "linger_ticks": 0,  "base_contagious_days": 0},
}


# ---------------------------------------------------------------------------
# Contagious state init
# ---------------------------------------------------------------------------

def init_contagion_state(char):
    char.setdefault("contagion_state", {
        "is_contagious": False,
        "transmission_modes": [],
        "contagious_radius_tiles": 0.0,
        "airborne_linger_ticks": 0,
        "particle_cloud": {},
        "contagious_since_tick": None,
        "contagious_until_tick": None,
        "hand_dirty": False,
        "hand_dirty_since_tick": None,
        "touched_dirty_surface_tick": None,
    })
    char.setdefault("toilet_hygiene_log", [])


# ---------------------------------------------------------------------------
# Set / update contagious state when a disease is acquired
# ---------------------------------------------------------------------------

def update_contagious_state(char, tick, defs=None):
    """
    Recalculate whether the character is currently contagious based on their
    active physical_health conditions. Call after any condition change.
    """
    cs = char.setdefault("contagion_state", {})
    active = char.get("physical_health", [])
    condition_states = char.get("condition_state", {})

    is_contagious = False
    modes = set()
    max_radius = 0.0
    max_linger = 0
    contagious_until = None

    for cond_key in active:
        tcfg = TRANSMISSIBLE_CONDITIONS.get(cond_key)
        if not tcfg or not tcfg["modes"]:
            continue

        cstate = condition_states.get(cond_key, {})
        days_elapsed = cstate.get("days_elapsed", 0)
        contagious_days = tcfg["base_contagious_days"]

        if days_elapsed <= contagious_days:
            is_contagious = True
            modes.update(tcfg["modes"])
            if "airborne" in tcfg["modes"]:
                # Radius decays linearly over contagious period
                fraction = max(0.0, 1.0 - days_elapsed / max(contagious_days, 1))
                radius = RADIUS_FAR * fraction
                max_radius = max(max_radius, radius)
                max_linger = max(max_linger, tcfg.get("linger_ticks", AIRBORNE_LINGER_TICKS))
                until_tick = tick + (contagious_days - days_elapsed) * 24
                if contagious_until is None or until_tick < contagious_until:
                    contagious_until = until_tick
            else:
                max_radius = max(max_radius, RADIUS_CLOSE)

    cs["is_contagious"]         = is_contagious
    cs["transmission_modes"]    = list(modes)
    cs["contagious_radius_tiles"] = max_radius
    cs["airborne_linger_ticks"] = max_linger
    cs["contagious_until_tick"] = contagious_until
    if is_contagious and cs.get("contagious_since_tick") is None:
        cs["contagious_since_tick"] = tick


# ---------------------------------------------------------------------------
# Particle cloud (airborne)
# ---------------------------------------------------------------------------

def emit_particles(char, current_tile, tick):
    """
    Called each tick for characters who are airborne-contagious.
    Marks the current tile and surrounding tiles with expiry ticks.
    """
    cs = char.get("contagion_state", {})
    if "airborne" not in cs.get("transmission_modes", []):
        return

    cloud = cs.setdefault("particle_cloud", {})
    linger = cs.get("airborne_linger_ticks", AIRBORNE_LINGER_TICKS)

    # current tile + adjacent (approximate by tile_key offsets)
    tx, ty = _parse_tile(current_tile)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            dist = math.sqrt(dx*dx + dy*dy)
            if dist <= cs.get("contagious_radius_tiles", RADIUS_FAR):
                tile_key = _make_tile(tx + dx, ty + dy)
                cloud[tile_key] = tick + linger


def sweep_expired_particles(char, tick):
    """Remove expired particle cloud entries."""
    cs = char.get("contagion_state", {})
    cloud = cs.get("particle_cloud", {})
    expired = [k for k, exp in cloud.items() if exp <= tick]
    for k in expired:
        del cloud[k]


def get_particle_risk(infected_char, target_tile, tick):
    """Return per-tick airborne infection risk for a target at target_tile."""
    cs = infected_char.get("contagion_state", {})
    cloud = cs.get("particle_cloud", {})
    if target_tile not in cloud or cloud[target_tile] <= tick:
        return 0.0
    return AIRBORNE_RISK.get("far", 0.01)  # lingering particles = far-ring risk


# ---------------------------------------------------------------------------
# Distance-based risk (live proximity)
# ---------------------------------------------------------------------------

def get_proximity_risk(infected_char, source_tile, target_tile, tick):
    """
    Returns per-tick infection probability for a target character standing at
    target_tile while the infected character is at source_tile.
    """
    cs = infected_char.get("contagion_state", {})
    if not cs.get("is_contagious"):
        return 0.0

    modes = cs.get("transmission_modes", [])
    dist = _tile_distance(source_tile, target_tile)

    risk = 0.0
    if "airborne" in modes:
        if dist <= RADIUS_CLOSE:
            risk = max(risk, AIRBORNE_RISK["close"])
        elif dist <= RADIUS_MEDIUM:
            risk = max(risk, AIRBORNE_RISK["medium"])
        elif dist <= RADIUS_FAR:
            risk = max(risk, AIRBORNE_RISK["far"])

    if "contact" in modes and dist <= RADIUS_CLOSE:
        risk = max(risk, AIRBORNE_RISK["close"] * CONTACT_RISK_MULTIPLIER)

    return risk


def get_sexual_risk(infected_char):
    """Risk per sexual encounter tick for sexually-transmitted conditions."""
    cs = infected_char.get("contagion_state", {})
    if not cs.get("is_contagious"):
        return 0.0
    modes = cs.get("transmission_modes", [])
    if "sexual" in modes:
        return AIRBORNE_RISK["close"] * SEXUAL_RISK_MULTIPLIER
    return 0.0


# ---------------------------------------------------------------------------
# Attempt infection
# ---------------------------------------------------------------------------

def attempt_infection(source_char, target_char, risk, world, mode="airborne"):
    """
    Roll to see if target_char contracts a disease from source_char.
    Risk is amplified by target's immune_modifier and age.
    Returns the condition key if infection occurs, else None.
    """
    if not source_char.get("contagion_state", {}).get("is_contagious"):
        return None

    # Import here to avoid circular import
    try:
        from systems.health import immune_modifier, _remember
    except ImportError:
        immune_modifier = lambda c: 1.0
        _remember = lambda *a: None

    mod = immune_modifier(target_char)
    effective_risk = min(0.99, risk * mod)

    if random.random() > effective_risk:
        return None

    # Pick which condition to transmit
    active = source_char.get("physical_health", [])
    eligible = [c for c in active if mode in TRANSMISSIBLE_CONDITIONS.get(c, {}).get("modes", [])]
    if not eligible:
        return None

    condition = random.choice(eligible)
    if condition not in target_char.get("physical_health", []):
        target_char.setdefault("physical_health", []).append(condition)
        update_contagious_state(target_char, world.get("tick", 0))
        _remember(target_char,
                  f"Contracted {condition.replace('_', ' ')} from contact.",
                  0.75, ["health", "contagion", condition], "health", world.get("tick", 0))
        return condition
    return None


# ---------------------------------------------------------------------------
# Tick: proximity sweep (called from sim_loop for all chars in same location)
# ---------------------------------------------------------------------------

def tick_contagion_location(chars_in_location, world):
    """
    Call once per tick for each group of characters sharing a location.
    Handles proximity-based airborne/contact spread.
    chars_in_location: list of char dicts all in the same tile/room.
    """
    tick = world.get("tick", 0)
    contagious = [c for c in chars_in_location
                  if c.get("contagion_state", {}).get("is_contagious")]
    if not contagious:
        return

    for source in contagious:
        src_tile = source.get("location_tile", "0,0")
        emit_particles(source, src_tile, tick)
        sweep_expired_particles(source, tick)

        for target in chars_in_location:
            if target is source:
                continue
            tgt_tile = target.get("location_tile", "0,0")
            risk = get_proximity_risk(source, src_tile, tgt_tile, tick)
            if risk > 0:
                attempt_infection(source, target, risk, world, mode="airborne")

        # Also check lingering particle cloud for targets
        for target in chars_in_location:
            if target is source:
                continue
            tgt_tile = target.get("location_tile", "0,0")
            linger_risk = get_particle_risk(source, tgt_tile, tick)
            if linger_risk > 0:
                attempt_infection(source, target, linger_risk, world, mode="airborne")


# ---------------------------------------------------------------------------
# Hand hygiene
# ---------------------------------------------------------------------------

def toilet_visit(char, visit_type, tick, flush=True):
    """
    Call when a character uses the toilet.
    visit_type: "defecation" | "urination"
    Determines whether they wash hands and whether they flush.
    """
    cs = char.setdefault("contagion_state", {})

    # Flush compliance
    did_flush = flush
    if visit_type == "urination":
        did_flush = flush and random.random() < 0.75   # forget to flush 25%
    elif visit_type == "defecation":
        did_flush = flush and random.random() < 0.95   # forget 5%

    # Hand washing compliance
    if visit_type == "defecation":
        washes = random.random() < HANDWASH_AFTER_DEFECATION_CHANCE
    else:
        washes = random.random() < HANDWASH_AFTER_URINATION_CHANCE

    if washes:
        wash_hands(char, tick)
    else:
        # Hands now dirty — set germ flag
        cs["hand_dirty"] = True
        cs["hand_dirty_since_tick"] = tick
        # Log for immune system daily roll
        char.setdefault("daily_log", {})["hand_hygiene_missed"] = True

    # Log the visit
    char.setdefault("toilet_hygiene_log", []).append({
        "tick": tick, "type": visit_type,
        "flushed": did_flush, "washed": washes
    })

    return {"flushed": did_flush, "washed": washes}


def wash_hands(char, tick, method="soap_water"):
    """Character washes hands. Clears hand_dirty state."""
    cs = char.setdefault("contagion_state", {})
    cs["hand_dirty"] = False
    cs["hand_dirty_since_tick"] = None
    # Sanitizer is faster but less thorough — still clears for our purposes
    return True


def use_hand_sanitizer(char, tick):
    return wash_hands(char, tick, method="sanitizer")


def handle_dirty_hands_contact(source_char, target_char, world):
    """
    When a character with dirty hands touches another or prepares food,
    attempt fecal-oral transmission of gut bacteria.
    """
    cs = source_char.get("contagion_state", {})
    if not cs.get("hand_dirty"):
        return None
    risk = 0.05   # per contact event
    return attempt_infection(source_char, target_char, risk, world, mode="fecal_oral")


# ---------------------------------------------------------------------------
# Food safety
# ---------------------------------------------------------------------------

def evaluate_food_safety(food_item, char, world):
    """
    Called when a character consumes a food item/uses a food prop.
    food_item should have: freshness (0-1), prep_quality (0-1), bacterial_load (0-1)
    Returns None if safe, or a condition key if food poisoning occurs.
    """
    try:
        from systems.health import immune_modifier, _remember
    except ImportError:
        immune_modifier = lambda c: 1.0
        _remember = lambda *a: None

    if not isinstance(food_item, dict):
        return None

    freshness    = food_item.get("freshness", 1.0)
    prep_quality = food_item.get("prep_quality", 1.0)
    bacterial    = food_item.get("bacterial_load", 0.0)

    # Build a composite risk score
    # Aged food, poor prep, or high bacterial load all increase risk
    risk = (1.0 - freshness) * 0.4 + (1.0 - prep_quality) * 0.3 + bacterial * 0.3

    if "sensitive_stomach" in char.get("physical_traits", []):
        risk *= 1.5

    if risk <= 0.05:
        return None   # safe

    mod = immune_modifier(char)
    effective_risk = min(0.95, risk * mod)

    if random.random() < effective_risk:
        condition = "aggressive_gut_bacteria"
        if condition not in char.get("physical_health", []):
            char.setdefault("physical_health", []).append(condition)
            update_contagious_state(char, world.get("tick", 0))
            _remember(char, "Got food poisoning from contaminated food.", 0.80,
                      ["health", "food_safety"], "health", world.get("tick", 0))
        return condition
    return None


def age_food_items(world, ticks_per_day=24):
    """
    Decay freshness of all placed food items/props each day.
    Call once per in-game day.
    """
    tick = world.get("tick", 0)
    for item in world.get("placed_items", {}).values():
        if not item.get("is_food"):
            continue
        freshness = item.get("freshness", 1.0)
        # Decay rate: ~5% per day at room temperature; refrigerated slows 5x
        decay = 0.05 if not item.get("refrigerated") else 0.01
        item["freshness"] = max(0.0, freshness - decay)
        # High bacterial load once very old
        if item["freshness"] < 0.2:
            item["bacterial_load"] = min(1.0, item.get("bacterial_load", 0.0) + 0.10)


# ---------------------------------------------------------------------------
# Fecal-oral: dirty surfaces
# ---------------------------------------------------------------------------

def mark_surface_dirty(world, surface_id, tick):
    """Mark a surface (toilet handle, door handle) as contaminated."""
    surfaces = world.setdefault("dirty_surfaces", {})
    surfaces[surface_id] = {"contaminated_since": tick, "expires": tick + SURFACE_GERM_LINGER_TICKS}


def touch_surface(char, world, surface_id):
    """Character touches a potentially contaminated surface."""
    surfaces = world.get("dirty_surfaces", {})
    tick = world.get("tick", 0)
    entry = surfaces.get(surface_id)
    if entry and entry.get("expires", 0) > tick:
        cs = char.setdefault("contagion_state", {})
        cs["hand_dirty"] = True
        cs["touched_dirty_surface_tick"] = tick


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _parse_tile(tile_key):
    try:
        parts = str(tile_key).split(",")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def _make_tile(x, y):
    return f"{x},{y}"


def _tile_distance(a, b):
    ax, ay = _parse_tile(a)
    bx, by = _parse_tile(b)
    return math.sqrt((ax - bx)**2 + (ay - by)**2)
