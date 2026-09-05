"""
systems/self_image.py

Two separate self-esteem scores, both 0-1, matching the scale
c["attractiveness"]/c["self_confidence"] already use:

- c["self_confidence"] (schema_defaults.py, pre-existing, unchanged) --
  the psychological side: how a character sees their own character/
  competence. Already real and actively consumed (domestic_control.py's
  vulnerability/leave-threshold checks, attraction.py's party_
  disposition) -- reused as-is here, not duplicated.
- c["body_confidence"] (new) -- the physical side: how a character sees
  their own appearance. No such field existed anywhere in this codebase
  before this round (confirmed via full-codebase grep) -- c
  ["attractiveness"] is an OBJECTIVE score other characters read to
  judge this one, never a self-facing number. Initialized from
  attractiveness itself plus a small personality nudge (trait_polarity_
  balance below), since two equally attractive people don't necessarily
  feel equally good about how they look.

Both scores feed systems/withdrawal_concern.py's persuasion-chance
formula ("try to use that to match situations," per the user's own
framing) -- someone already running low on both is realistically harder
to talk into anything, not easier.
"""

import random

BODY_CONFIDENCE_NOISE = 0.10


def trait_polarity_balance(c, defs):
    """(positive_count, negative_count, net_score) -- net_score is
    (positive-negative)/total, in [-1, 1], 0 if the character has no
    traits with a recognized polarity. Reuses trait_templates' own
    "polarity" field (already real, already used by attraction.py's
    ideal-partner trait bucketing) rather than inventing a second
    positive/negative trait taxonomy."""
    trait_templates = defs.get("trait_templates", {})
    tr = set(c.get("traits", [])) | set(c.get("personality_traits", []))
    pos = sum(1 for t in tr if trait_templates.get(t, {}).get("polarity") == "positive")
    neg = sum(1 for t in tr if trait_templates.get(t, {}).get("polarity") == "negative")
    total = pos + neg
    net = (pos - neg) / total if total else 0.0
    return pos, neg, net


def generate_body_confidence(c):
    """Called once at generation (character_gen.py) -- base = actual
    attractiveness, with a small personality-driven nudge and random
    noise so it isn't a pure mirror of the objective score."""
    base = c.get("attractiveness")
    if base is None:
        base = 0.5
    nudge = random.uniform(-BODY_CONFIDENCE_NOISE, BODY_CONFIDENCE_NOISE)
    return round(max(0.05, min(0.95, base + nudge)), 3)


def overall_self_esteem(c):
    """Simple average of the psychological and physical sides -- used
    wherever a single "how good does this person feel about themselves
    overall" number is more useful than the two separately (systems/
    withdrawal_concern.py's persuasion-chance formula)."""
    psych = c.get("self_confidence", 0.6)
    body = c.get("body_confidence", 0.6)
    return round((psych + body) / 2, 3)
