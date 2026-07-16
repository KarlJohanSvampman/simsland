"""
systems/conditioning.py

Conditioned behaviors: personality modifiers acquired through repeated
social-contract enforcement (positive and negative reinforcement).

Each character has a conditioning_profile[] — a list of entries:
  {
    "stimulus":            str,    # what triggered the conditioning
    "response_type":       str,    # anxiety | avoidance | compliance_habit |
                                   # frustration | resentment_authority |
                                   # shame | attachment_warmth | achievement_habit
    "strength":            float,  # 0-1, grows with reinforcement_count
    "source_contract_id":  str,
    "source_authority_id": str,
    "reinforcement_count": int,
    "last_reinforced_tick": int,
    "trait_converted":     bool,   # True once promoted to a real trait
  }

When strength >= TRAIT_CONVERSION_THRESHOLD and reinforcement_count >= MIN_REINFORCEMENTS,
the conditioning converts to a permanent trait modifier flagged source="conditioned".
"""

import uuid

# ── Thresholds ────────────────────────────────────────────────────────────

TRAIT_CONVERSION_THRESHOLD = 0.70  # strength must reach this
MIN_REINFORCEMENTS          = 15   # events needed before conversion

# How much each reinforcement event increases strength
STRENGTH_GAIN_POSITIVE   = 0.06   # rewards
STRENGTH_GAIN_NEGATIVE   = 0.05   # punishments (slightly slower — resistance)
STRENGTH_DECAY_PER_WEEK  = 0.02   # unconditioned stimulus fades over time

# Mapping: conditioning_response → trait awarded on conversion
RESPONSE_TO_TRAIT = {
    "compliance_habit":      "conscientious",
    "anxiety":               "anxious",
    "avoidance":             "conflict_avoidant",
    "frustration":           "easily_frustrated",
    "resentment_authority":  "rebellious",
    "shame":                 "easily_embarrassed",
    "shame_anxiety":         "easily_embarrassed",
    "attachment_warmth":     "affectionate",
    "caution":               "cautious",
    "achievement_habit":     "ambitious",
}

# Whether a reinforcement is positive or negative based on conditioning_response
POSITIVE_RESPONSES = {
    "compliance_habit", "attachment_warmth", "achievement_habit",
}


# ── Core API ──────────────────────────────────────────────────────────────

def apply_reinforcement(character, stimulus, response_type, world,
                        contract_id=None, authority_id=None, is_positive=None):
    """
    Record a reinforcement event for a given stimulus+response pair.
    Creates a new conditioning entry if one doesn't exist yet.
    """
    tick    = world.get("tick", 0)
    profile = character.setdefault("conditioning_profile", [])

    # Find or create entry for this stimulus
    entry = next(
        (e for e in profile
         if e["stimulus"] == stimulus and e["response_type"] == response_type),
        None
    )

    if entry is None:
        entry = {
            "id":                   f"cond_{uuid.uuid4().hex[:6]}",
            "stimulus":             stimulus,
            "response_type":        response_type,
            "strength":             0.0,
            "source_contract_id":   contract_id,
            "source_authority_id":  authority_id,
            "reinforcement_count":  0,
            "last_reinforced_tick": tick,
            "trait_converted":      False,
        }
        profile.append(entry)

    if is_positive is None:
        is_positive = response_type in POSITIVE_RESPONSES

    gain = STRENGTH_GAIN_POSITIVE if is_positive else STRENGTH_GAIN_NEGATIVE
    entry["strength"]             = min(1.0, entry["strength"] + gain)
    entry["reinforcement_count"] += 1
    entry["last_reinforced_tick"] = tick

    # Check for trait conversion
    if (not entry["trait_converted"] and
            entry["strength"] >= TRAIT_CONVERSION_THRESHOLD and
            entry["reinforcement_count"] >= MIN_REINFORCEMENTS):
        _convert_to_trait(character, entry, world)

    return entry


def apply_discipline(character, authority, method_id, world):
    """
    Authority applies a disciplinary method to character.
    Looks up method in definitions.json, applies immediate effects,
    and records conditioning.

    Returns the method definition or None if not found.
    """
    defs    = world.get("definitions", {})
    methods = defs.get("disciplinary_methods_registry", {})
    method  = methods.get(method_id)
    if not method:
        return None

    tick       = world.get("tick", 0)
    auth_id    = authority["id"] if isinstance(authority, dict) else authority
    char_id    = character["id"]

    # 1. Immediate relationship effects
    _apply_method_relationship_effects(character, authority, method, world)

    # 2. Conditioning reinforcement
    stimulus  = method.get("conditioning_stimulus", method_id)
    response  = method.get("conditioning_response", "avoidance")
    is_pos    = method.get("category") == "reward"

    active_contract_id = _find_relevant_contract(character, auth_id, world)
    apply_reinforcement(character, stimulus, response, world,
                        contract_id=active_contract_id,
                        authority_id=auth_id,
                        is_positive=is_pos)

    # 3. Create a new contract if the method demands one
    if "creates_contract" in method:
        _create_discipline_contract(character, authority, method, world)

    # 4. Log the discipline event
    character.setdefault("discipline_log", []).append({
        "tick":        tick,
        "method_id":   method_id,
        "authority_id": auth_id,
        "category":    method.get("category"),
    })
    character["discipline_log"] = character["discipline_log"][-30:]

    return method


def apply_reward(character, authority, method_id, world):
    """Alias for apply_discipline for reward methods — same pipeline."""
    return apply_discipline(character, authority, method_id, world)


# ── Effect appliers ───────────────────────────────────────────────────────

def _apply_method_relationship_effects(char, authority, method, world):
    auth_id = authority["id"] if isinstance(authority, dict) else authority
    rel = char.setdefault("relationships", {}).setdefault(auth_id, {})

    resentment_d = method.get("resentment_delta", 0)
    warmth_d     = method.get("warmth_delta", 0)
    trust_d      = method.get("trust_delta", 0)
    mood_d       = method.get("mood_delta", 0)
    shame_d      = method.get("shame_delta", 0)

    if resentment_d:
        rel["resentment"] = min(100, rel.get("resentment", 0) + resentment_d)
    if warmth_d:
        rel["warmth"] = min(100, rel.get("warmth", 50) + warmth_d)
    if trust_d:
        rel["trust"] = min(100, rel.get("trust", 50) + trust_d)
    if shame_d:
        char["blush_score"] = min(1.0, char.get("blush_score", 0.0) + shame_d)

    # Mood effect on character
    if mood_d:
        moods = char.setdefault("mood_states", {})
        if mood_d > 0:
            moods["happy"] = min(1.0, moods.get("happy", 0.5) + mood_d)
        else:
            moods["sad"] = min(1.0, moods.get("sad", 0.0) + abs(mood_d))


def _find_relevant_contract(char, authority_id, world):
    """Return the most recently active contract between char and authority."""
    best = None
    best_tick = -1
    for cid in char.get("social_contract_ids", []):
        contract = world.get("social_contracts", {}).get(cid, {})
        if contract.get("status") != "active":
            continue
        if authority_id not in contract.get("parties", []):
            continue
        created = contract.get("created_tick", 0)
        if created > best_tick:
            best_tick = created
            best = cid
    return best


def _create_discipline_contract(char, authority, method, world):
    """Create the contract specified by a disciplinary method."""
    from systems.social_contracts import create_authority_contract

    auth_id       = authority["id"] if isinstance(authority, dict) else authority
    contract_type = method["creates_contract"]
    raw_params    = dict(method.get("contract_params", {}))

    # Resolve relative params (e.g. deadline_delta → new absolute value)
    if "deadline_delta" in raw_params:
        # Find current curfew hour
        current_hour = 22
        for cid in char.get("social_contract_ids", []):
            c = world.get("social_contracts", {}).get(cid, {})
            for term in c.get("terms", []):
                if term.get("check_type") == "curfew":
                    current_hour = term.get("params", {}).get("deadline_hour", 22)
        raw_params["deadline_hour"] = current_hour + raw_params.pop("deadline_delta")

    expires = raw_params.pop("duration_ticks", None)
    create_authority_contract(auth_id, char["id"], contract_type, raw_params, world,
                              expires_ticks=expires)


# ── Trait conversion ──────────────────────────────────────────────────────

def _convert_to_trait(char, entry, world):
    """Promote a conditioning entry to a permanent conditioned trait."""
    trait = RESPONSE_TO_TRAIT.get(entry["response_type"])
    if not trait:
        entry["trait_converted"] = True
        return

    traits = char.setdefault("personality_traits", [])
    if trait not in traits:
        traits.append(trait)
        # Also note it as conditioned (not innate)
        char.setdefault("conditioned_traits", []).append({
            "trait":               trait,
            "source":              "conditioned",
            "stimulus":            entry["stimulus"],
            "authority_id":        entry.get("source_authority_id"),
            "acquired_tick":       world.get("tick", 0),
            "reinforcement_count": entry["reinforcement_count"],
        })

    entry["trait_converted"] = True


# ── Weekly decay tick ─────────────────────────────────────────────────────

def tick_conditioning_weekly(world):
    """
    Weekly: decay unconsolidated conditioning entries.
    Converted traits are permanent and not decayed here.
    """
    tick = world.get("tick", 0)
    for char in world.get("characters", {}).values():
        profile = char.get("conditioning_profile", [])
        for entry in profile:
            if entry.get("trait_converted"):
                continue
            weeks_idle = (tick - entry.get("last_reinforced_tick", tick)) / (24 * 7)
            decay = STRENGTH_DECAY_PER_WEEK * weeks_idle
            entry["strength"] = max(0.0, entry["strength"] - decay)


# ── Context helper ────────────────────────────────────────────────────────

def get_conditioning_context(char):
    """Return a brief summary of active conditioning for LLM context."""
    entries = []
    for e in char.get("conditioning_profile", []):
        if e["strength"] < 0.15:
            continue
        converted = " [now a trait]" if e.get("trait_converted") else ""
        entries.append(
            f"{e['response_type']} response to '{e['stimulus']}' "
            f"(strength {e['strength']:.0%}){converted}"
        )
    return entries or None
