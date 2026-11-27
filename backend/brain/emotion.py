"""
emotion.py — emotional temperature, emotion labels, and persistent moods.

c["emotional_temperature"]  float 0-100 — current arousal/valence blend
c["emotion"]                str   — short label derived from temperature + mood
c["mood"]                   dict  — active persistent mood state or None
c["emotion_causes"]         list  — what moved the temperature, and by how much: [{ts, delta, why}] (newest last)

The temperature relaxes toward a calm baseline (relax(), every update_emotion): stress and sleep debt raise the
baseline, an active mood keeps it inside its range. Until 2026-11-27 the only decay was inside apply_emotion_inertia(),
which hardly ever ran -- every push (a like, a comment, a passive health trait) only ever added heat, and everyone sat
at 100, "furious", about nothing. Every push now goes through nudge() / apply_emotion_inertia(why=...), which records
why; causes() / explain() say what someone is worked up about (the inspector, their own prompt).

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
    "agony":      92,
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

def apply_emotion_inertia(c, llm_emotion=None, why=None, world=None):
    """
    Drift emotional_temperature toward an emotion's temperature (EMOTION_TEMP). Volatility modulates how fast it
    shifts. `why` is recorded as the cause (emotion_causes). Stress and sleep debt work through relax()'s baseline.
    """
    before     = float(c.get("emotional_temperature", 20))
    current    = before
    volatility = float(c.get("volatility", 0.5))

    if llm_emotion:
        target  = EMOTION_TEMP.get(llm_emotion, current)
        current = current * (1 - 0.25 * volatility) + target * (0.25 * volatility)

    c["emotional_temperature"] = _clamp_to_mood(c, max(0.0, min(100.0, current)))
    if why:
        _note_cause(c, c["emotional_temperature"] - before, why, world)


# ── pushes, and what they were about ─────────────────────────────────────────

CAUSES_KEPT = 16
CAUSE_HALF_LIFE_S = 2 * 3600        # how long a reason keeps counting, halving every two sim hours
RELAX_HALF_LIFE_S = 45 * 60         # the temperature halves its distance to the baseline every 45 sim minutes
BASELINE = 30.0


def _clamp_to_mood(c, temp):
    mood = c.get("mood")
    if mood:
        lo, hi = mood.get("emotional_temperature_range", [0, 100])
        return max(lo, min(hi, temp))
    return temp


def _note_cause(c, delta, why, world=None):
    if not why or abs(delta) < 0.05:
        return
    causes_ = c.setdefault("emotion_causes", [])
    causes_.append({"ts": round(_now_ts(c, world), 1), "delta": round(delta, 2), "why": str(why)[:160]})
    del causes_[:-CAUSES_KEPT]


def nudge(c, delta, why, world=None):
    """Move the temperature by `delta` (clamped 0-100 and to the mood's range) and record why."""
    before = float(c.get("emotional_temperature", 20))
    c["emotional_temperature"] = _clamp_to_mood(c, max(0.0, min(100.0, before + delta)))
    _note_cause(c, c["emotional_temperature"] - before, why, world)
    return c["emotional_temperature"]


def baseline(c):
    """Where the temperature settles on its own: calm, raised by stress and by sleep debt."""
    stress = float(c.get("stress", 0) or 0)
    sleep_debt = float((c.get("body") or {}).get("sleep_debt", 0) or 0)
    return min(75.0, BASELINE + max(0.0, stress - 40) * 0.5 + max(0.0, sleep_debt - 25) * 0.25)


def relax(c, world=None):
    """Toward the baseline, by how much sim time has passed since the last time (lazy: the same however often it
    runs), then inside the active mood's range."""
    now = _now_ts(c, world)
    last = c.get("_emotion_relax_ts")
    c["_emotion_relax_ts"] = now
    temp = float(c.get("emotional_temperature", 20) or 20)
    if last is not None and now > last:
        dt = min(now - last, 12 * 3600)
        base = baseline(c)
        temp = base + (temp - base) * 0.5 ** (dt / RELAX_HALF_LIFE_S)
    c["emotional_temperature"] = round(_clamp_to_mood(c, max(0.0, min(100.0, temp))), 2)


def causes(c, world=None, limit=3):
    """What has been heating them up: [(why, weight)], the strongest first -- recent pushes count most."""
    now = _now_ts(c, world) if world is not None else c.get("_emotion_seen_ts", 0.0)
    totals = {}
    for e in c.get("emotion_causes") or []:
        age = max(0.0, now - (e.get("ts") or now))
        w = (e.get("delta") or 0) * 0.5 ** (age / CAUSE_HALF_LIFE_S)
        totals[e.get("why")] = totals.get(e.get("why"), 0.0) + w
    out = sorted(((k, round(v, 1)) for k, v in totals.items() if v >= 1.0), key=lambda kv: -kv[1])
    mood = c.get("mood")
    if mood and (mood.get("emotional_temperature_range") or [0])[0] >= 50:
        out.insert(0, (f"in a {str(mood.get('name') or mood.get('id')).lower()} mood", None))
    return out[:limit]


def explain(c, world=None):
    """'mostly because: Rebecca shouted at you; unmet needs: exercise' -- or "" when nothing stands out."""
    found = causes(c, world)
    return "; ".join(why for why, _w in found)


# ── emotion label update ──────────────────────────────────────────────────────

from core.tick_schedule import TICK_RATE_SECONDS


def _now_ts(c, world):
    """Sim time for mood expiry (core/clock.now_ts); with no world at hand, the time the character last saw."""
    if world is not None:
        from core.clock import now_ts
        c["_emotion_seen_ts"] = now_ts(world)
    return c.get("_emotion_seen_ts", 0.0)


def update_emotion(c, world=None):
    relax(c, world)
    temp        = float(c.get("emotional_temperature", 20))
    active_mood = c.get("mood")
    c["emotion"] = _temp_to_emotion(temp, active_mood)

    # A mood lasts until its expiry time (sim seconds) -- a lazy value, not a per-tick countdown, so it ends at the same
    # moment however often this runs. A mood from an older save (remaining_ticks only) is given its expiry now.
    if active_mood:
        now = _now_ts(c, world)
        if "expires_ts" not in active_mood:
            active_mood["expires_ts"] = now + (active_mood.get("remaining_ticks", 0) - 1) * TICK_RATE_SECONDS
        if now >= active_mood["expires_ts"]:
            c["mood"] = None
        elif world is not None:
            from brain import agent_wake
            agent_wake.wake_at(c, world, active_mood["expires_ts"], "mood_ends")

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
    # Avoid immediately re-triggering a mood that just expired.
    if "_mood_cooldown_until" in c and "_mood_cooldown_until_ts" not in c:     # an older save: in ticks
        c["_mood_cooldown_until_ts"] = _now_ts(c, world) + ((c.pop("_mood_cooldown_until") or 0)
                                                             - (world.get("tick", 0) or 0)) * TICK_RATE_SECONDS
    if _now_ts(c, world) < (c.get("_mood_cooldown_until_ts") or float("-inf")):
        from brain import agent_wake          # a new mood can come once the cooldown is over
        agent_wake.wake_at(c, world, c["_mood_cooldown_until_ts"], "mood_cooldown")
        return

    body       = c.get("body", {})
    stress     = float(c.get("stress", 0))
    temp       = float(c.get("emotional_temperature", 20))
    lt_needs   = c.get("lt_needs", {})

    candidates = []
    for mood_id, tmpl in templates.items():
        triggers = tmpl.get("triggers", {})
        if not _check_triggers(triggers, stress, temp, body, lt_needs, c):
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
        "expires_ts":                 _now_ts(c, world) + chosen.get("duration_ticks", 3600) * TICK_RATE_SECONDS,
    }

    # what it is about (emotion_causes): the heaviest grievance for an angry mood, else the mood itself
    about = chosen.get("name", chosen_id)
    if chosen.get("triggers", {}).get("grievance_active"):
        g = max(c.get("grievances") or [{}], key=lambda g: g.get("weight", 0) or 0)
        who = ((world.get("characters") or {}).get(g.get("caused_by")) or {}).get("name", "someone")
        about = f"{who.split(' ')[0]}: {str(g.get('event_type') or 'what they did').replace('_', ' ')}"
    _note_cause(c, max(0.0, c["mood"]["emotional_temperature_range"][0] - temp), about, world)

    # Apply need modifiers immediately
    _apply_mood_need_modifiers(c)
    # Cooldown before another mood can trigger.
    c["_mood_cooldown_until_ts"] = _now_ts(c, world) + chosen.get("duration_ticks", 3600) * TICK_RATE_SECONDS


def _check_triggers(triggers, stress, temp, body, lt_needs, c):
    for key, value in triggers.items():
        if key == "stress_above"          and stress <= value:          return False
        if key == "stress_below"          and stress >= value:          return False
        if key == "sleep_debt_above"      and body.get("sleep_debt", 0) <= value: return False
        if key == "sleep_debt_below"      and body.get("sleep_debt", 0) >= value: return False
        if key == "fatigue_below"         and body.get("fatigue", 0) >= value:    return False
        if key == "emotional_temperature_above" and temp <= value:      return False
        # fun_need_low = play lt_need frustration > 0.65 (unsatisfied)
        if key == "fun_need_low":
            if lt_needs.get("play", {}).get("frustration", 0) <= 0.65: return False
        # fun_need_high = play lt_need frustration < 0.4 (well satisfied)
        if key == "fun_need_high":
            if lt_needs.get("play", {}).get("frustration", 1) >= 0.4:  return False
        # social_need_low = socialize lt_need frustration > 0.65
        if key == "social_need_low":
            if lt_needs.get("socialize", {}).get("frustration", 0) <= 0.65: return False
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
            # A single minor grievance shouldn't keep someone furious forever:
            # only a genuinely heavy one (or several compounding) qualifies.
            if not any((g.get("weight", 0) or 0) >= 10 for g in c.get("grievances", [])): return False
    return True


def _apply_mood_need_modifiers(c):
    """
    Mood need_modifiers shift lt_need frustration.
    Keys: "social" → "socialize", "fun" → "play".
    Positive delta in template = more satisfying → frustration goes DOWN.
    """
    mood = c.get("mood")
    if not mood:
        return
    _KEY_MAP = {"social": "socialize", "fun": "play"}
    lt_needs = c.setdefault("lt_needs", {})
    for need_key, delta in mood.get("need_modifiers", {}).items():
        lt_key = _KEY_MAP.get(need_key, need_key)
        nd = lt_needs.get(lt_key)
        if nd is not None:
            # positive old-style delta means more satisfaction → lower frustration
            nd["frustration"] = max(0.0, min(1.0, nd["frustration"] - delta))


def get_emotion_label(c):
    return c.get("emotion", "calm")


# ── helper for external modules ───────────────────────────────────────────────

def set_mood_event(c, event_key, value=True):
    """
    Signal a one-time mood trigger event. These are short-lived flags checked
    during the next mood evaluation pass, then cleared.
    """
    c[f"_{event_key}"] = value
