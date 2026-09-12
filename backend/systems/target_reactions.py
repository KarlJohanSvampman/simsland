"""
systems/target_reactions.py

Whenever a character is the TARGET of an action likely to provoke a real
reaction -- a punch, a threat, an insult, a compliment, a guilt trip --
this computes a trait-weighted probability distribution over plausible
emotional reactions, samples one, and makes sure it actually reaches the
target's own next decision PROMINENTLY (at the very top of their
narrative, via the existing wake_line mechanism, brain/
cognition_scheduler.py) instead of only ever showing up as a buried
relationship/body-stat delta a few sections down. Confirmed live gap:
hostile_actions.py already emits "hostile_action_resolved" but nothing
subscribes to it, so a target never got any reactive prompt to actually
respond to being attacked -- they'd only find out passively, whenever
their own next scheduled/idle think() happened to fire.

reactions.py's SPEECH_ACT_REACTIONS already exists for the ANIMATION
layer (a flat one-reaction-per-speech-act map, same for everyone) --
this is a separate, narrative-facing layer: WHICH emotional reaction is
plausible for THIS character, weighted by their own traits, not what
canned animation plays.
"""

import random

# Base weights per provoking action/speech_act -- roughly how a typical
# person would split across these reactions with no trait influence.
REACTION_WEIGHTS = {
    "punch":          {"anger": 0.40, "fear": 0.35, "shock": 0.25},
    "kick":           {"anger": 0.40, "fear": 0.35, "shock": 0.25},
    "shove":          {"anger": 0.50, "fear": 0.20, "shock": 0.30},
    "threaten":       {"fear": 0.50, "anger": 0.35, "defiance": 0.15},
    "grab_offensive": {"fear": 0.45, "anger": 0.35, "shock": 0.20},
    "hold":           {"fear": 0.50, "anger": 0.30, "shock": 0.20},
    "wrestle":        {"anger": 0.30, "adrenaline": 0.40, "fear": 0.30},
    "insult":         {"anger": 0.40, "hurt": 0.40, "dismissive": 0.20},
    "guilt_trip":     {"guilt": 0.50, "annoyance": 0.30, "dismissive": 0.20},
    "compliment":     {"pleased": 0.60, "suspicious": 0.15, "awkward": 0.25},
    "flirt":          {"pleased": 0.45, "awkward": 0.35, "uninterested": 0.20},
    "joke":           {"amused": 0.60, "unamused": 0.40},
    "brag":           {"annoyed": 0.50, "impressed": 0.20, "indifferent": 0.30},
}

# Verb phrasing for the wake-line template, per action/speech_act.
_VERB_PHRASE = {
    "punch": "punched", "kick": "kicked", "shove": "shoved",
    "threaten": "threatened", "grab_offensive": "grabbed at",
    "hold": "grabbed and held", "wrestle": "grappled with",
    "insult": "insulted", "guilt_trip": "tried to guilt-trip",
    "compliment": "complimented", "flirt": "flirted with",
    "joke": "made a joke at", "brag": "bragged to",
}

# trait: {reaction_label: multiplier} -- only real, pickable
# trait_templates entries (confirmed against definitions.json).
_TRAIT_REACTION_BIAS = {
    "confident":    {"fear": 0.5, "dismissive": 1.6, "anger": 0.8, "awkward": 0.5, "suspicious": 0.8},
    "nervous":      {"fear": 1.7, "shock": 1.4, "dismissive": 0.4, "awkward": 1.5, "defiance": 0.5},
    "aggressive":   {"anger": 1.8, "fear": 0.5, "defiance": 1.5},
    "suspicious":   {"suspicious": 2.0, "pleased": 0.6},
    "manipulative": {"dismissive": 1.4, "hurt": 0.5, "guilt": 0.5},
    "forgiving":    {"anger": 0.5, "annoyance": 0.5, "annoyed": 0.5},
    "vindictive":   {"anger": 1.6, "defiance": 1.4},
    "charismatic":  {"awkward": 0.5, "pleased": 1.3},
    "resilient":    {"fear": 0.6, "shock": 0.6, "hurt": 0.6},
    "stubborn":     {"defiance": 1.6, "dismissive": 1.3},
}


def compute_reaction_weights(target, provocation_type):
    base = REACTION_WEIGHTS.get(provocation_type)
    if not base:
        return None
    traits = set(target.get("traits", []) + target.get("personality_traits", []))
    weights = dict(base)
    for trait in traits:
        biases = _TRAIT_REACTION_BIAS.get(trait)
        if not biases:
            continue
        for label, mult in biases.items():
            if label in weights:
                weights[label] *= mult
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def sample_reaction(target, provocation_type):
    """Weighted random pick -- returns (label, full_weight_dict) or
    (None, None) if provocation_type isn't a recognized trigger."""
    weights = compute_reaction_weights(target, provocation_type)
    if not weights:
        return None, None
    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    r = random.random()
    cumulative = 0.0
    for label, w in ranked:
        cumulative += w
        if r <= cumulative:
            return label, weights
    return ranked[0][0], weights


def flag_provocation(target, world, actor, provocation_type, outcome=None):
    """Call right after a provoking action lands on `target`. Samples a
    trait-weighted reaction, wakes the target reactively (so they get a
    real decision cycle about this instead of waiting on their next
    scheduled/idle poll), and stamps enough payload for
    cognition_scheduler.py's "provoked" wake-line template to render it
    at the very top of their next narrative."""
    label, weights = sample_reaction(target, provocation_type)
    if not label:
        return

    top = sorted(weights.items(), key=lambda kv: -kv[1])[:2]
    if len(top) > 1 and top[1][1] >= 0.2:
        reaction_hint = f"Your gut reaction: mostly {top[0][0]}, but some {top[1][0]} too."
    else:
        reaction_hint = f"Your gut reaction: {top[0][0]}."

    from brain.cognition_scheduler import wake_character
    wake_character(target, world, "provoked", payload={
        "actor_name":    actor.get("name", "someone"),
        "verb_phrase":   _VERB_PHRASE.get(provocation_type, "provoked"),
        "reaction_hint": reaction_hint,
    })
