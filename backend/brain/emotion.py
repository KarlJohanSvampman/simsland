"""
emotion.py — emotional temperature, emotion labels, and persistent moods.

c["emotional_temperature"]  float 0-100 — current arousal/valence blend
c["emotion"]                str   — short label derived from temperature + mood
c["mood"]                   dict  — active persistent mood state or None

Moods are data-driven: they come from definitions["mood_templates"].
They persist for duration_ticks and can stack (only one active at a time;
the most negative one wins when multiple are triggered).
"""

# ── baseline emotion labels from temperature ──────────────────────────────────
EMOTION_TEMP = {
    "ecstatic":   95,
    "euphoric":   88,
    "excited":    78,
    "cheerful":   65,
    "content":    50,
    "calm":       35,
    "neutral":    20,
    "bored":      25,
    "melancholy": 40,
    "anxious":    55,
    "annoyed":    60,
    "sad":        45,
    "angry":      72,
    "furious":    88,
    "fearful":    70,
    "smug":       55,
    "suspicious": 50,
    "awkward":    45,
    "curious":    35,
    "warm":       28,
}

# ── temperature → label map (sorted by threshold descending) ─────────────────
_TEMP_TO_LABEL = [
    (90, "furious"),
    (78, "angry"),
    (65, "annoyed"),
    (55, "anxious"),
    (45, "irritable"),
    (35, "content"),
    (22, "calm"),
    (0,  "calm"),
]


def _temp_to_emotion(temp, active_mood=None):
    """Derive an emotion label from temperature, modulated by active mood."""
    if active_mood:
        flags = active_mood.get("behavior_flags", [])
        if "depressed" in flags:
            return "sad"
        if "grieving" in flags:
            return "sad"
        if "furious" in flags and temp > 70:
            return "furious"
        if "cheerful" in flags and temp < 50:
            return "cheerful"
        if "anxious" in flags and temp > 45:
            return "anxious"
        if "lonely" in flags and temp < 50:
            return "lonely"
        if "focused" in flags and temp < 40:
            return "focused"

    for threshold, label in _TEMP_TO_LABEL:
        if temp >= threshold:
            return label
    return "calm"


# ── inertia / drift ───────────────────────────────────────────────────────────

def apply_emotion_inertia(c, llm_emotion=None):
    """
    Drift emotional_temperature toward the LLM-reported emotion.
    Volatility trait modulates how fast it shifts.
    Sleep debt and stress push it upward.
    """
    current    = float(c.get("emotional_temperature", 20))
    volatility = float(c.get("volatility", 0.5))

    if llm_emotion:
        target  = EMOTION_TEMP.get(llm_emotion, current)
        current = current * (1 - 0.25 * volatility) + target * (0.25 * volatility)

    # Stress pushes temperature up
    stress = float(c.get("stress", 0))
    current += max(0, stress - 40) * 0.012

    # Sleep debt adds baseline irritability
    sleep_debt = c.get("body", {}).get("sleep_debt", 0)
    current += max(0, sleep_debt - 25) * 0.008

    # Active mood can pin a floor
    mood = c.get("mood")
    if mood:
        lo, hi = mood.get("emotional_temperature_range", [0, 100])
        current = max(lo, min(hi, current))

    # Gentle decay toward baseline
    c["emotional_temperature"] = max(0, min(100, current * 0.995))


# ── emotion label update ──────────────────────────────────────────────────────

def update_emotion(c, world=None):
    temp        = float(c.get("emotional_temperature", 20))
    active_mood = c.get("mood")
    c["emotion"] = _temp_to_emotion(temp, active_mood)

    # Tick down mood duration
    if active_mood:
        remaining = active_mood.get("remaining_ticks", 0) - 1
        if remaining <= 0:
            c["mood"] = None
        else:
            active_mood["remaining_ticks"] = remaining

    # Check if a new mood should be triggered
    if world and not c.get("mood"):
        _maybe_trigger_mood(c, world)


# ── mood triggering ───────────────────────────────────────────────────────────

def _maybe_trigger_mood(c, world):
    """
    Scan mood_templates for any whose trigger conditions are met.
    Activate the most impactful one (highest priority = most negative polarity).
    """
    templates = world.get("definitions", {}).get("mood_templates", {})
    if not templates:
        return

    body       = c.get("body", {})
    stress     = float(c.get("stress", 0))
    temp       = float(c.get("emotional_temperature", 20))
    lt_needs   = c.get("lt_needs", {})
    needs      = c.get("needs", {})

    candidates = []
    for mood_id, tmpl in templates.items():
        triggers = tmpl.get("triggers", {})
        if not _check_triggers(triggers, stress, temp, body, lt_needs, needs, c):
            continue
        candidates.append((mood_id, tmpl))

    if not candidates:
        return

    # Prefer negative moods over neutral, negative over positive, then by duration
    polarity_rank = {"negative": 0, "neutral": 1, "positive": 2}
    candidates.sort(key=lambda x: (
        polarity_rank.get(x[1].get("polarity", "neutral"), 1),
        -x[1].get("duration_ticks", 3600)
    ))

    chosen_id, chosen = candidates[0]
    c["mood"] = {
        "id":                         chosen_id,
        "name":                       chosen.get("name", chosen_id),
        "behavior_flags":             chosen.get("behavior_flags", []),
        "need_modifiers":             chosen.get("need_modifiers", {}),
        "emotional_temperature_range":chosen.get("emotional_temperature_range", [0, 100]),
        "polarity":                   chosen.get("polarity", "neutral"),
        "remaining_ticks":            chosen.get("duration_ticks", 3600),
    }

    # Apply need modifiers immediately
    _apply_mood_need_modifiers(c)


def _check_triggers(triggers, stress, temp, body, lt_needs, needs, c):
    for key, value in triggers.items():
        if key == "stress_above"          and stress <= value:          return False
        if key == "stress_below"          and stress >= value:          return False
        if key == "sleep_debt_above"      and body.get("sleep_debt", 0) <= value: return False
        if key == "sleep_debt_below"      and body.get("sleep_debt", 0) >= value: return False
        if key == "fatigue_below"         and body.get("fatigue", 0) >= value:    return False
        if key == "emotional_temperature_above" and temp <= value:      return False
        if key == "fun_need_low"          and needs.get("fun", 1.0) >= 0.35:      return False
        if key == "fun_need_high"         and needs.get("fun", 0.0) < 0.6:        return False
        if key == "social_need_low"       and needs.get("social", 1.0) >= 0.35:   return False
        if key == "lt_need_romance_high":
            nd = lt_needs.get("romance", {})
            if nd.get("frustration", 0) < 0.4:                         return False
        if key == "lt_need_socialize_high":
            nd = lt_needs.get("socialize", {})
            if nd.get("frustration", 0) < 0.4:                         return False
        if key == "lt_need_adventure_high":
            nd = lt_needs.get("adventure", {})
            if nd.get("frustration", 0) < 0.35:                        return False
        if key == "multiple_lt_needs_unmet":
            unmet = sum(1 for nd in lt_needs.values() if nd.get("frustration", 0) > 0.5)
            if unmet < 3:                                               return False
        if key == "recent_positive_event" and not c.get("_recent_positive_event"): return False
        if key == "negative_life_event"   and not c.get("_negative_life_event"):   return False
        if key == "major_loss"            and not c.get("_major_loss"):             return False
        if key == "social_failure"        and not c.get("_social_failure"):         return False
        if key == "grievance_active":
            if not c.get("grievances"):                                 return False
    return True


def _apply_mood_need_modifiers(c):
    """Shift social/fun needs by mood modifiers."""
    mood = c.get("mood")
    if not mood:
        return
    for need_key, delta in mood.get("need_modifiers", {}).items():
        current = c.get("needs", {}).get(need_key, 0.5)
        c.setdefault("needs", {})[need_key] = max(0.0, min(1.0, current + delta))


def get_emotion_label(c):
    return c.get("emotion", "calm")


# ── helper for external modules ───────────────────────────────────────────────

def set_mood_event(c, event_key, value=True):
    """
    Signal a one-time mood trigger event. These are short-lived flags checked
    during the next mood evaluation pass, then cleared.
    """
    c[f"_{event_key}"] = value
