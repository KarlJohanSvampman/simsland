"""
systems/impact_kinds.py

The taxonomy for the relationship-impact ledger (systems/relationship_ledger.py):
what kinds of intentional act there are, whether each is positive or negative,
how weighty it is by default (1-10), and how it nudges the RECIPIENT's feelings
toward the source per 10 points of final value.

Constants are plain Python so they can be tuned in one place; a world's
definitions.json may override any kind under "impact_kinds" (merged over these)
without code changes.
"""

# id: {"polarity": +1/-1, "base": 1-10, "deltas": {relationship field: change per 10 value}}
KINDS = {
    # ---- positive -----------------------------------------------------------
    "apology":        {"polarity": +1, "base": 6, "deltas": {"trust": 2, "resentment": -4, "hostility": -3, "respect": 1}},
    "forgiveness":    {"polarity": +1, "base": 6, "deltas": {"trust": 3, "resentment": -5, "hostility": -4, "friendship": 2}},
    "concession":     {"polarity": +1, "base": 5, "deltas": {"respect": 2, "resentment": -2, "trust": 1}},
    "altruism":       {"polarity": +1, "base": 7, "deltas": {"trust": 3, "respect": 3, "friendship": 2}},
    "solidarity":     {"polarity": +1, "base": 6, "deltas": {"trust": 3, "friendship": 3, "comfort": 2}},
    "compliment":     {"polarity": +1, "base": 3, "deltas": {"friendship": 1, "respect": 1, "comfort": 1}},
    "favor":          {"polarity": +1, "base": 5, "deltas": {"trust": 2, "friendship": 2}},
    "generosity":     {"polarity": +1, "base": 5, "deltas": {"trust": 2, "friendship": 2, "respect": 1}},
    "encouragement":  {"polarity": +1, "base": 4, "deltas": {"friendship": 2, "comfort": 2, "respect": 1}},
    "pride":          {"polarity": +1, "base": 5, "deltas": {"respect": 3, "friendship": 2}},
    "love":           {"polarity": +1, "base": 6, "deltas": {"friendship": 3, "comfort": 3, "trust": 2}},
    "kindness":       {"polarity": +1, "base": 4, "deltas": {"friendship": 2, "comfort": 2, "trust": 1}},
    "congratulation": {"polarity": +1, "base": 4, "deltas": {"friendship": 2, "respect": 1}},
    "personal_acknowledgement": {"polarity": +1, "base": 4, "deltas": {"friendship": 2, "comfort": 2, "trust": 1}},
    # ---- negative -----------------------------------------------------------
    "insult":         {"polarity": -1, "base": 6, "deltas": {"respect": -3, "resentment": 4, "hostility": 2, "friendship": -2}},
    "ignored":        {"polarity": -1, "base": 5, "deltas": {"respect": -2, "resentment": 3, "friendship": -2}},
    "ignored_heard":  {"polarity": -1, "base": 7, "deltas": {"respect": -3, "resentment": 5, "hostility": 2, "friendship": -3}},
    "avoidance":      {"polarity": -1, "base": 3, "deltas": {"friendship": -2, "resentment": 2}},
    "disrespect":     {"polarity": -1, "base": 5, "deltas": {"respect": -4, "resentment": 3}},
    "humiliation":    {"polarity": -1, "base": 9, "deltas": {"respect": -4, "resentment": 6, "hostility": 3, "trust": -3, "fear": 1}},
    "harassment":     {"polarity": -1, "base": 8, "deltas": {"trust": -4, "resentment": 5, "hostility": 3, "fear": 3, "comfort": -4}},
    "meanness":       {"polarity": -1, "base": 5, "deltas": {"friendship": -3, "resentment": 3}},
    "hate":           {"polarity": -1, "base": 9, "deltas": {"hostility": 6, "resentment": 5, "friendship": -5, "trust": -3}},
    "shaming":        {"polarity": -1, "base": 7, "deltas": {"respect": -3, "resentment": 5, "trust": -2}},
    "trust_breach":   {"polarity": -1, "base": 9, "deltas": {"trust": -7, "resentment": 5, "respect": -2}},
    "unfair_treatment": {"polarity": -1, "base": 6, "deltas": {"respect": -2, "resentment": 4, "trust": -2}},
    "objectification": {"polarity": -1, "base": 7, "deltas": {"respect": -4, "comfort": -4, "resentment": 3}},
    "patronizing":    {"polarity": -1, "base": 3, "deltas": {"respect": -2, "resentment": 2}},
    "provocation":    {"polarity": -1, "base": 5, "deltas": {"hostility": 3, "resentment": 2, "respect": -1}},
    "threat":         {"polarity": -1, "base": 9, "deltas": {"fear": 5, "hostility": 3, "trust": -5, "comfort": -4}},
    "intimidation":   {"polarity": -1, "base": 8, "deltas": {"fear": 5, "hostility": 2, "trust": -4, "comfort": -3}},
    "assault":        {"polarity": -1, "base": 9, "deltas": {"fear": 5, "hostility": 5, "trust": -6, "resentment": 4, "comfort": -4}},
    "manipulation":   {"polarity": -1, "base": 7, "deltas": {"trust": -4, "resentment": 3, "respect": -2}},
    "controlling":    {"polarity": -1, "base": 6, "deltas": {"resentment": 3, "comfort": -3, "respect": -2}},
    "exclusion":      {"polarity": -1, "base": 5, "deltas": {"friendship": -3, "resentment": 3}},
    "exposure":       {"polarity": -1, "base": 8, "deltas": {"trust": -5, "resentment": 5, "respect": -2}},
    "suspected_theft": {"polarity": -1, "base": 8, "deltas": {"trust": -5, "respect": -3, "resentment": 3}},
    "suspected_gossip": {"polarity": -1, "base": 5, "deltas": {"trust": -3, "resentment": 3}},
    "lie":            {"polarity": -1, "base": 5, "deltas": {"trust": -4, "resentment": 2, "respect": -1}},
    "slander":        {"polarity": -1, "base": 10, "deltas": {"trust": -5, "resentment": 6, "hostility": 3, "respect": -3}},
}

# What the speaker's chosen speech act means, when no explicit intent was given.
SPEECH_ACT_KIND = {
    "insult": "insult",
    "challenge": "provocation",
    "accuse": "provocation",
    "argue": None,                # an argument isn't automatically an offence
    "dismissive": "disrespect",
    "guilt_trip": "manipulation",
    "lie": "lie",
    "gossip": None,               # third-party pathway, not a direct impact
    "compliment": "compliment",
    "flirt": None,
    "apology": "apology",
    "apologize": "apology",
    "supportive": "encouragement",
    "comfort": "kindness",
    "thank": "kindness",
    "congratulate": "congratulation",
}

# Explicit intent from the speaker's model.
INTENT_KIND = {"hurt": "insult", "help": "kindness", "deceive": "lie"}

# Hostile actions (systems/hostile_actions.py) -> kind, and how much of the
# base weight an unsuccessful attempt still carries.
ACTION_KIND = {
    "punch": "assault", "kick": "assault", "stab": "assault", "knock": "assault",
    "shove": "assault", "threaten": "threat",
    "catch_and_hold": "intimidation", "hold_down": "intimidation",
}
OUTCOME_FACTOR = {"hit": 1.0, "evaded": 0.6, "fumble": 0.4}

# Kinds a toddler can read from tone alone.
TONE_KINDS = {"assault", "threat", "intimidation", "hate", "kindness", "love"}
DECEPTIVE_KINDS = {"lie", "slander", "manipulation"}


def kinds(world=None):
    """KINDS merged with any per-world overrides in definitions.json."""
    extra = ((world or {}).get("definitions") or {}).get("impact_kinds") or {}
    if not extra:
        return KINDS
    merged = {k: dict(v) for k, v in KINDS.items()}
    for k, v in extra.items():
        merged.setdefault(k, {}).update(v)
    return merged


def kind_for_speech(speech_act, intent=None):
    """Which kind (or None) a spoken line is, from the model's declared intent
    first, then the speech act."""
    if intent and intent.get("valence") in INTENT_KIND:
        by_act = SPEECH_ACT_KIND.get((speech_act or "").lower())
        return by_act or INTENT_KIND[intent["valence"]]
    return SPEECH_ACT_KIND.get((speech_act or "").lower())
