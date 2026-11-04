"""
social/standing.py -- how one character regards another (design section 2).

Directional: rel["standing"] on A's relationship with B is A's view of B, nothing to do with B's of A.

    rel["standing"] = {"score": -100..100, "confidence": 0..1, "last_updated", "last_interaction",
                       "history": [{tick, kind, delta, score, cause}]}

Standing is not affection: it is an overall assessment of the other's character, conduct and reliability. Liking,
trust and respect stay on the relationship (brain/relationships.py) and keep their own meaning.

It moves through experiences (change(kind=...)), and resists small swings: an established view (high confidence)
damps a minor incident, while a big one still lands; the same kind of thing again within a week counts for more each
time (repeated behaviour outweighs a single incident).
"""

from social.core import DAY, clamp, emit, now, rel, note

HISTORY_CAP = 80
REPEAT_WINDOW = 7 * DAY
BIG = 10

# what kinds of experience move standing, and by how much (before repetition and resistance)
DELTAS = {
    "kept_promise": 5, "broke_promise": -9, "competence": 4, "incompetence": -4, "consideration": 4,
    "selfish": -5, "support": 8, "public_humiliation": -15, "unmet_expectation": -4, "apology_with_change": 7,
    "apology": 2, "defended_me": 8, "defended_them": -3, "hypocrisy": -6, "insult": -6, "ridicule": -7,
    "provocation": -5, "bullying": -12, "threat": -14, "physical_aggression": -25, "lied": -10,
    "agreement": 5, "reconciliation": 8, "dismissed_me": -4, "listened": 3, "took_other_side": -4,
    "took_my_side": 5, "rumour": 0, "contract_violated": -8, "contract_kept": 3, "helped": 5,
}

SCALE = ((80, "extremely high regard"), (50, "strong positive regard"), (20, "generally favourable"),
         (-19, "neutral or uncertain"), (-49, "negative regard"), (-79, "very poor regard"), (-101, "extreme contempt"))


def _legacy(r):
    """What standing was before it was stored: a sum of the relationship values (the old Standing tab number)."""
    return ((r.get("friendship") or 0) + 0.5 * (r.get("trust") or 0) + 0.5 * (r.get("respect") or 0)
            + 0.3 * (r.get("warmth") or 0) - (r.get("resentment") or 0) - (r.get("hostility") or 0))


def get(c, oid, create=True):
    r = rel(c, oid, create=create)
    s = r.get("standing")
    if not isinstance(s, dict):
        if not create:
            return {"score": clamp(_legacy(r), -100, 100), "confidence": 0.0, "history": []}
        known = any(r.get(k) for k in ("friendship", "trust", "respect", "resentment", "hostility", "familiarity"))
        s = {"score": round(clamp(_legacy(r), -100, 100), 1), "confidence": 0.3 if known else 0.05,
             "last_updated": None, "last_interaction": None, "history": []}
        r["standing"] = s
    return s


def score(c, oid):
    return get(c, oid, create=False)["score"]


def label(v):
    for floor, text in SCALE:
        if v >= floor:
            return text
    return SCALE[-1][1]


def change(c, oid, world, kind=None, delta=None, cause=None):
    """Something c experienced of oid moves how c regards them. Returns the change actually applied."""
    if not oid or oid == c.get("id"):
        return 0.0
    s = get(c, oid)
    base = float(delta if delta is not None else DELTAS.get(kind, 0))
    if not base:
        return 0.0
    t = now(world)
    repeats = sum(1 for h in s["history"] if kind and h.get("kind") == kind and t - h.get("tick", 0) < REPEAT_WINDOW)
    mult = min(2.0, 1 + 0.35 * repeats)
    resist = (1 - 0.5 * s["confidence"]) if abs(base) < BIG else (1 - 0.15 * s["confidence"])
    eff = round(base * mult * resist, 2)
    s["score"] = round(clamp(s["score"] + eff, -100, 100), 2)
    s["confidence"] = round(min(1.0, s["confidence"] + 0.02 + abs(base) / 300), 3)
    s["last_updated"] = t
    s["history"].append({"tick": t, "kind": kind, "delta": eff, "score": s["score"], "cause": str(cause or kind or "")[:140]})
    del s["history"][:-HISTORY_CAP]
    emit("StandingChanged", {"observer_id": c.get("id"), "subject_id": oid, "delta": eff, "score": s["score"],
                             "kind": kind})
    note(c, oid, world, cause or (kind or "").replace("_", " "))
    return eff


def touch(c, oid, world):
    """They interacted directly."""
    if oid and oid != c.get("id"):
        get(c, oid)["last_interaction"] = now(world)
