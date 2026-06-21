# =========================================================
# ITEM KNOWLEDGE
# Per-character memory of where items are stored.
# Confidence decays over time; organized traits slow decay.
# When confidence drops below FORGET_THRESHOLD the character
# no longer knows where to look and must search.
# =========================================================

# ---- Confidence decay per tick ----
# Base: ~231 sim-days at 1.0 to reach forget threshold
_BASE_DECAY   = 0.000005

# Forget threshold — below this = "lost, need to search"
FORGET_THRESHOLD = 0.25

# ---- Trait multipliers on decay rate ----
# Lower = remembers longer
_TRAIT_DECAY = {
    "meticulous":    0.2,
    "organized":     0.3,
    "pragmatic":     0.4,
    "scatterbrained": 2.5,
    "chaotic":       2.0,
    "impulsive":     1.6,
}


def ensure_item_knowledge(c):
    c.setdefault("item_knowledge", {})


def _decay_rate(c):
    traits = set(c.get("traits", []))
    rate   = _BASE_DECAY
    for trait, mult in _TRAIT_DECAY.items():
        if trait in traits:
            rate *= mult
            break
    return rate


def record_item_location(c, item_type, container_id, room_id, tick):
    """
    Call whenever a character retrieves an item from a container.
    Resets confidence to 1.0 and stamps the retrieval tick.
    """
    ensure_item_knowledge(c)
    c["item_knowledge"][item_type] = {
        "container_id":        container_id,
        "room_id":             room_id,
        "last_retrieved_tick": tick,
        "confidence":          1.0,
    }


def get_known_location(c, item_type):
    """
    Returns the location dict if confidence >= FORGET_THRESHOLD, else None.
    None means the character must search for the item.
    """
    ensure_item_knowledge(c)
    loc = c["item_knowledge"].get(item_type)
    if loc and loc.get("confidence", 0) >= FORGET_THRESHOLD:
        return loc
    return None


def update_item_knowledge(c, world):
    """
    Decay confidence for all known item locations.
    Should be called every tick in the main sim loop.
    Age of the record accelerates decay slightly so very old
    memories fade faster than recent ones.
    """
    ensure_item_knowledge(c)
    rate = _decay_rate(c)
    tick = world.get("tick", 0)

    for item_type, loc in c["item_knowledge"].items():
        conf = loc.get("confidence", 0)
        if conf <= 0:
            continue
        last       = loc.get("last_retrieved_tick", tick)
        age_ticks  = max(0, tick - last)
        # Age factor: up to 4× faster decay after ~90 sim-days of not touching it
        age_factor = 1.0 + min(3.0, age_ticks / 86400.0)
        loc["confidence"] = max(0.0, conf - rate * age_factor)
