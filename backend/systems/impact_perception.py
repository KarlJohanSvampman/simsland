"""
systems/impact_perception.py

Did it register? The evaluation ladder from docs/relationship_impact_plan.md §5.

Six cheap yes/no checks, run in order for ONE recipient (or observer); the first
failure stops the evaluation and the number of checks passed so far is what
counts:

  1 perceivable      in range / audible / seen / actually delivered
  2 aimed at me      addressed, named, the only one it could be for, or -- for a
                     neutral observer -- I have reason to take it personally
  3 intelligible     I can parse it (a toddler only reads tone)
  4 fits my picture  of the source: hostile readings land on someone already
                     resentful, kindness is doubted by someone who distrusts them
  5 survives my      a lie or manipulation I don't believe is an attempt, not
    own evidence     the harm that was intended
  6 sensitivity      temperament and current stress against how big it is

The more covert an act (discretion 0-1), the more checks must pass before it is
read as intended:  threshold T = 3 + ceil(3 * discretion).  At or above T it is
registered with value

    V = M * (1 + 0.25 * passed) - discretion * M / 2

(M = the source's intended magnitude), capped. Pure Python, no LLM.
"""

import math

from systems.impact_kinds import DECEPTIVE_KINDS, TONE_KINDS

CHECKS_TOTAL = 6
PER_CHECK_BONUS = 0.25
VALUE_CAP = 25.0
STRAIN_THRESHOLD = 20          # resentment/hostility that primes someone to take things personally
CLARITY_MIN = 0.15

_THIN_SKINNED = {"sensitive", "anxious", "insecure", "emotional", "temperamental", "hot_tempered", "proud"}
_THICK_SKINNED = {"thick_skinned", "stoic", "calm", "easygoing", "confident", "resilient"}
_WARM = {"affectionate", "warm", "friendly", "kind", "empathetic", "romantic"}
_GUARDED = {"cold", "guarded", "distrustful", "aloof", "suspicious", "reserved"}


def threshold(discretion):
    return 3 + math.ceil(3 * max(0.0, min(1.0, discretion)))


def final_value(magnitude, passed, discretion):
    v = magnitude * (1 + PER_CHECK_BONUS * passed) - discretion * magnitude / 2
    return min(VALUE_CAP, v)


def _traits(c):
    return set(c.get("traits") or []) | set(c.get("personality_traits") or [])


def strain(rel):
    return max(rel.get("resentment", 0) or 0, rel.get("hostility", 0) or 0)


def disposition(rel):
    """How favourably R sees the source, roughly -100..100."""
    warm = ((rel.get("trust", 0) or 0) + (rel.get("friendship", 0) or 0) + (rel.get("respect", 0) or 0)) / 3
    return warm - ((rel.get("resentment", 0) or 0) + (rel.get("hostility", 0) or 0)) / 2


def evaluate(recipient, rel, ctx):
    """Returns (passed, [(name, ok), ...]).

    ctx: kind, polarity, magnitude, discretion, channel, clarity, certain,
         is_target, mentioned, only_listener, witness_closeness, volume
    """
    passed = 0
    log = []

    def step(name, ok):
        nonlocal passed
        log.append((name, bool(ok)))
        if ok:
            passed += 1
        return bool(ok)

    kind, M, d = ctx["kind"], ctx["magnitude"], ctx["discretion"]
    certain = ctx.get("certain", False)

    # 1 perceivable
    clarity = ctx.get("clarity")
    ok = certain or clarity is None or clarity >= CLARITY_MIN
    if not step("perceivable", ok):
        return passed, log

    # 2 aimed at me
    ok = (certain or ctx.get("is_target") or ctx.get("mentioned") or ctx.get("only_listener")
          or (ctx.get("witness_closeness") or 0) >= 0.3
          or strain(rel) >= STRAIN_THRESHOLD)
    if not step("aimed_at_me", ok):
        return passed, log

    # 3 intelligible
    age = recipient.get("age")
    if age is None:
        ok = True
    elif age < 4:
        ok = kind in TONE_KINDS
    elif age < 8:
        ok = d < 0.6
    else:
        ok = True
    if not step("intelligible", ok):
        return passed, log

    # 4 fits what I know of the source
    disp = disposition(rel)
    if ctx["polarity"] < 0:
        ok = disp < 20 or M >= 6
    else:
        ok = disp > -30 or M >= 6
    if not step("fits_expectation", ok):
        return passed, log

    # 5 survives my own evidence
    if kind in DECEPTIVE_KINDS:
        ok = (rel.get("trust", 0) or 0) >= 15 or (age is not None and age < 10)
    else:
        ok = True
    if not step("survives_evidence", ok):
        return passed, log

    # 6 sensitivity
    traits = _traits(recipient)
    stress = recipient.get("stress") or 0
    try:
        stress = float(stress)
    except (TypeError, ValueError):
        stress = 0.0
    if ctx["polarity"] < 0:
        sens = 1.0 + stress / 200.0
        if traits & _THIN_SKINNED:
            sens *= 1.4
        if traits & _THICK_SKINNED:
            sens *= 0.6
        ok = M * sens >= 3
    else:
        warmth = 1.0
        if traits & _WARM:
            warmth *= 1.3
        if traits & _GUARDED:
            warmth *= 0.7
        ok = M * warmth >= 2
    step("sensitivity", ok)
    return passed, log
