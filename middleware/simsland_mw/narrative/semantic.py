"""
Numbers -> meaning (spec sections 1 and 8).

The LLM never sees `hunger: 78`. It sees "very hungry". These bands are the
single place thresholds live; the option generator imports the same
constants, so what a character *feels* and what she is *offered* can't drift.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .templates import join_natural

# ---- thresholds shared with the option generator --------------------------
HUNGRY_AT = 50        # hunger: 0 = full, 100 = starving
TIRED_AT = 60         # fatigue: 0 = rested, 100 = exhausted
BLADDER_AT = 55       # bladder: 0 = empty, 100 = urgent
THIRSTY_AT = 40       # hydration: 100 = hydrated -> thirsty when AT or below
UNCLEAN_AT = 40       # hygiene: 100 = clean -> unclean when AT or below

Band = Tuple[float, Optional[str]]


def band(value: Optional[float], bands: Sequence[Band]) -> Optional[str]:
    """First phrase whose (exclusive) upper bound is above `value`."""
    if value is None:
        return None
    for upper, phrase in bands:
        if value < upper:
            return phrase
    return bands[-1][1]


HUNGER: Sequence[Band] = [(30, None), (50, "a little hungry"), (80, "quite hungry"),
                          (92, "very hungry"), (1001, "starving")]
FATIGUE: Sequence[Band] = [(30, None), (50, "somewhat tired"), (70, "quite tired"),
                           (90, "exhausted"), (1001, "so tired you can barely stay upright")]
# hydration is inverted (low = thirsty)
THIRST: Sequence[Band] = [(25, "very thirsty"), (THIRSTY_AT + 1, "thirsty"), (1001, None)]
BLADDER: Sequence[Band] = [(45, None), (70, "need the bathroom soon"),
                           (88, "really need the bathroom"), (1001, "are desperate for the bathroom")]
HYGIENE: Sequence[Band] = [(20, "feel filthy"), (UNCLEAN_AT + 1, "could do with a shower"), (1001, None)]
SICKNESS: Sequence[Band] = [(30, None), (60, "feel under the weather"), (1001, "feel properly ill")]


def describe_body(body: Dict[str, Any]) -> str:
    """'You are quite hungry and somewhat tired. You could do with a shower.'"""
    adjectives = [p for p in (
        band(body.get("hunger"), HUNGER),
        band(body.get("fatigue"), FATIGUE),
        band(body.get("hydration"), THIRST),
    ) if p]
    clauses = [p for p in (
        band(body.get("bladder"), BLADDER),
        band(body.get("hygiene"), HYGIENE),
        band(body.get("sickness"), SICKNESS),
    ) if p]
    parts: List[str] = []
    if adjectives:
        parts.append(f"You are {join_natural(adjectives)}.")
    for c in clauses:
        parts.append(f"You {c}.")
    if not parts:
        return "You feel physically fine."
    return " ".join(parts)


# ---- relationships -----------------------------------------------------------

def _affection(friendship: float) -> str:
    return band(friendship, [(20, "don't feel much warmth toward"), (45, "get along well enough with"),
                             (70, "are fond of"), (1001, "care deeply about")])


def describe_relationship(name: str, rel: Dict[str, Any], grievance_total: float = 0.0) -> str:
    """One sentence about how she sees someone. Directed: her view, not theirs."""
    labels = [l for l in rel.get("labels") or [] if l]
    if rel.get("authority_over"):
        # Simsland's own label convention is inconsistent about which side a
        # "parent"/"child" label describes; authority_over is unambiguous.
        tag = " (someone in your care)"
    else:
        tag = f" (your {labels[0].replace('_', ' ')})" if labels else ""
    if (rel.get("familiarity") or 0) < 20:
        return f"You hardly know {name}{tag}."

    friendship = rel.get("friendship") or 0
    trust = rel.get("trust")
    respect = rel.get("respect")
    head = f"You {_affection(friendship)} {name}{tag}"

    trust_phrase = band(trust, [(30, "you don't really trust them"), (55, None),
                                (80, "you trust them"), (1001, "you trust them completely")])
    if trust_phrase:
        contrast = friendship >= 45 and (trust or 0) < 55
        head += (", but " if contrast else ", and ") + trust_phrase
    if (respect or 0) < 25:
        head += ", and you don't think much of them"

    if grievance_total >= 12:
        head += f". You're carrying real resentment toward {name}"
    elif grievance_total >= 4:
        head += f". {name} has been getting on your nerves lately"
    return head + "."


# ---- money --------------------------------------------------------------------

def describe_money(finances: Optional[Dict[str, Any]], traits: Sequence[str] = ()) -> Optional[str]:
    if not finances:
        return None
    wealth = finances.get("wealth")
    weekly = finances.get("weekly_expenses") or 0
    bills = sum((b.get("amount") or 0) for b in finances.get("bills_due") or [])
    parts: List[str] = []
    if wealth is not None:
        if bills and wealth < bills:
            parts.append("Money is tight: bills are due and the household can't quite cover them")
        elif weekly and wealth < weekly:
            parts.append("Money is tight for the household right now")
        elif weekly and wealth < 2 * weekly:
            parts.append("The household is getting by, but there isn't much to spare")
    if parts and "frugal" in traits:
        parts.append("you'd rather not spend money unnecessarily")
    elif "frugal" in traits and not parts:
        parts.append("You'd rather not spend money unnecessarily")
    return ", and ".join(parts) + "." if parts else None


def describe_time(env: Dict[str, Any]) -> Optional[str]:
    tod, hour, minute = env.get("time_of_day"), env.get("hour"), env.get("minute")
    if tod is None:
        return None
    clock = f"{hour:02d}:{(minute or 0):02d}" if isinstance(hour, int) else ""
    day = f" on a {env['weekday']}" if env.get("weekday") else ""
    return f"It is {tod}{', around ' + clock if clock else ''}{day}."
